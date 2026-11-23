"""Rutas HTTP de ConverData-API.

    uvicorn converdata_api.main:app --app-dir api     (desde la raíz de DataAgent, un solo worker: OP-03)

La identidad sale solo del token de sesión (cookie `cd_session` o `Authorization: Bearer`); ninguna ruta acepta
`user_id` ni credenciales fuera de `/auth/login` (OP-03).
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hmac
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from converdata.catalog.ids import table_key
from converdata.curation import human_edits, plan_dictionary
from converdata.cli import load_dotenv, use_system_certificates
from converdata.config import ServerConfig
from converdata.flows.catalog_build import OWN_DATABASES
from converdata.metadata.sqlserver import SYSTEM_DATABASES
from converdata.models.discovery import AnswerEnvelope
from converdata.models.knowledge import BusinessRule
from converdata.observability.logging import configure_logging, log_event
from converdata.observability.metrics import Metrics
from converdata.storage.connection import describe as describe_connection

from converdata_api.audit import open_audit
from converdata_api.connector import Connector, DemoConnector, LoginFailed, SqlConnector, server_from_host
from converdata_api.curation import CurationDesk, demand_by_asset, metrics_report
from converdata_api.demo import seed_stewards
from converdata_api.documentation import MANUAL, DocumentationLibrary, DocumentNotFound
from converdata_api.mcp_mount import build_mcp_mount
from converdata_api.pii import find_pii
from converdata_api.tokens import TokenLedger
from converdata_api.runtime import AgentRuntime, ShownTrace
from converdata_api.security import (InsecureConfiguration, LoginThrottle, SecurityMiddleware, inventory_violations,
                                     production_violations, valid_host, valid_identifier, valid_login)
from converdata_api.settings import ApiSettings
from converdata_api.vault import Credential, Session, SessionVault

COOKIE = "cd_session"


# --- cuerpos de petición -----------------------------------------------------------------------------
def _check_host(value: str | None) -> str | None:
    if value is not None and not valid_host(value.strip()):
        raise ValueError("Nombre de servidor no válido")
    return value


def _check_databases(value: list[str]) -> list[str]:
    if not all(valid_identifier(d) for d in value):
        raise ValueError("Nombre de base de datos no válido")
    return value


ShortText = Annotated[str, Field(max_length=2000)]
ServerId = Annotated[str, Field(max_length=64)]
DatabaseName = Annotated[str, Field(min_length=1, max_length=128)]


class LoginRequest(BaseModel):
    login: str | None = Field(None, max_length=128)  # vacío con auth=windows
    password: str | None = Field(None, max_length=256)
    auth: Literal["sql", "windows"] = "sql"
    servers: list[ServerId] | None = Field(None, max_length=100)  # None = todos los del inventario
    # Primer arranque (inventario vacío): servidor al que se conecta el agente
    host: str | None = Field(None, max_length=256)
    alias: str | None = Field(None, max_length=80)
    environment: Literal["produccion", "qa", "desarrollo", "dr"] = "desarrollo"
    trust_server_certificate: bool = False
    setup_token: str | None = Field(None, max_length=256)  # secreto del instalador (CONVERDATA_SETUP_TOKEN)

    _host = field_validator("host")(_check_host)

    @field_validator("login")
    @classmethod
    def _login(cls, value: str | None) -> str | None:
        # Va dentro de la cadena de conexión: sin `;{}=` ni caracteres de control (security.valid_login).
        if value is not None and value.strip() and not valid_login(value.strip()):
            raise ValueError("Usuario no válido")
        return value


class DiscoverRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[ShortText] = Field(default_factory=list, max_length=10)


class FeedbackRequest(BaseModel):
    trace_id: str = Field(max_length=64)
    asset_key: str = Field(max_length=400)
    verdict: Literal["confirm", "reject"]


class BuildRequest(BaseModel):
    enrich: bool = False


class ServerIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    host: str = Field(min_length=1, max_length=256)
    alias: str = Field(min_length=1, max_length=80)
    environment: Literal["produccion", "qa", "desarrollo", "dr"] = "desarrollo"
    is_reference: bool = False
    databases: list[DatabaseName] = Field(default_factory=lambda: ["*"], max_length=500)
    trust_server_certificate: bool = False

    _host = field_validator("host")(_check_host)
    _databases = field_validator("databases")(_check_databases)


class InventoryRequest(BaseModel):
    servers: list[ServerIn] = Field(max_length=200)


class ProbeRequest(BaseModel):
    """Un servidor nuevo (`host`) o uno del inventario (`server_id`, con su propia configuración)."""

    host: str | None = Field(None, max_length=256)
    server_id: ServerId | None = None
    trust_server_certificate: bool = False

    _host = field_validator("host")(_check_host)


class ConnectRequest(BaseModel):
    """Añade (`host`) o actualiza (`server_id`) un servidor con las bases elegidas y lanza el descubrimiento."""

    server_id: ServerId | None = None
    host: str | None = Field(None, max_length=256)
    alias: str | None = Field(None, max_length=80)
    environment: Literal["produccion", "qa", "desarrollo", "dr"] = "desarrollo"
    trust_server_certificate: bool = False
    databases: list[DatabaseName] = Field(min_length=1, max_length=500)  # ["*"] = todas, también las futuras
    enrich: bool = False

    _host = field_validator("host")(_check_host)
    _databases = field_validator("databases")(_check_databases)


class EscalateRequest(BaseModel):
    trace_id: str = Field(max_length=64)
    note: str | None = Field(None, max_length=500)


class AnswerRequest(BaseModel):
    kind: Literal["asset", "no_source"]
    asset_key: str | None = Field(None, max_length=400)
    description: str | None = Field(None, max_length=1000)  # opcional: también documenta el activo elegido
    note: str | None = Field(None, max_length=1000)


class DescriptionRequest(BaseModel):
    asset_key: str = Field(max_length=400)
    description: str = Field(min_length=3, max_length=1000)
    synonyms: list[str] | None = Field(None, max_length=12)


class RuleRequest(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{2,40}$")
    text: str = Field(min_length=5, max_length=1000)
    applies_to: list[str] = Field(min_length=1, max_length=20)
    domain: str | None = Field(None, max_length=80)


class DictionaryRequest(BaseModel):
    csv: str = Field(min_length=10, max_length=2_000_000)


class StewardIn(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    domains: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=lambda: ["*"], max_length=50)

    @field_validator("login")
    @classmethod
    def _login(cls, value: str) -> str:
        if not valid_login(value.strip()):
            raise ValueError("Usuario no válido")
        return value


class StewardsRequest(BaseModel):
    stewards: list[StewardIn] = Field(max_length=500)


class MetricsMiddleware:
    """ASGI: peticiones, errores y latencia por ruta (HU-22). Solo la plantilla de la ruta y números, nunca el contenido."""

    def __init__(self, app, metrics: Metrics, logger: logging.Logger | None = None):
        self.app, self.metrics, self.logger = app, metrics, logger

    @staticmethod
    def route_name(scope) -> str:
        path = scope["path"]
        if path == "/mcp" or path.startswith("/mcp/"):
            return "mcp"
        route = scope.get("route")
        template = getattr(route, "path", None)
        if not template:
            return "otras"
        return re.sub(r"[^a-z0-9_.]+", "_", template.lower()).strip("_") or "raiz"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started, code, error_type = time.perf_counter(), 500, None

        async def tracking_send(message):
            nonlocal code
            if message["type"] == "http.response.start":
                code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            error_type = type(exc).__name__  # solo el tipo: el texto puede llevar SQL o valores (D5)
            raise
        finally:
            name = self.route_name(scope)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if name != "health_metrics":
                self.metrics.observe_request(name, elapsed_ms, ok=code < 500)
            if self.logger is not None:  # HU-21: ni ruta con parámetros, ni cabeceras, ni cuerpo
                fields = {"route": name, "method": scope["method"], "http_status": code, "duration_ms": round(elapsed_ms, 1)}
                if error_type:
                    fields["error_type"] = error_type
                log_event(self.logger, "http.request", logging.ERROR if code >= 500 else logging.INFO, **fields)


class RateLimiter:
    """OP-04: N preguntas por minuto y sesión, en memoria del proceso (un solo worker)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def create_app(settings: ApiSettings | None = None, connector: Connector | None = None) -> FastAPI:
    if settings is None:
        load_dotenv()
        use_system_certificates()
        settings = ApiSettings.from_env()
    if connector is None:
        connector = DemoConnector(settings.demo_fixtures) if settings.demo else SqlConnector()
    if settings.production:
        problems = production_violations(settings)
        if problems:
            raise InsecureConfiguration(problems)
    vault = SessionVault(settings.session_ttl_s, max_age_s=settings.session_max_age_s,
                         max_per_user=settings.max_sessions_per_user)
    audit = open_audit(settings)
    if settings.production:
        integrity = audit.verify()  # en SQL Server: la cuenta del servicio no puede modificar ni borrar la auditoría
        if not integrity.ok:
            raise InsecureConfiguration([e for f in integrity.files for e in f.errors])
    runtime = AgentRuntime(settings, connector, vault, audit)
    if settings.production:
        problems = inventory_violations(runtime.inventory.servers, settings)
        if problems:
            raise InsecureConfiguration(problems)
    curation = CurationDesk(runtime.curation, settings.notify_webhook, settings.public_url)
    if settings.demo:
        seed_stewards(curation)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    login_throttle = LoginThrottle(settings.login_max_failures, settings.login_window_s, settings.login_lockout_s)
    ip_throttle = LoginThrottle(settings.login_ip_max_failures, settings.login_window_s, settings.login_lockout_s)
    metrics = Metrics()
    tokens = TokenLedger(settings.token_limit_daily)
    runtime.usage_listeners += [tokens.record_call, lambda _role, tin, tout: metrics.add_tokens(tin, tout)]
    app_tokens = tokens
    logger = configure_logging(settings.log_dir, event_log=settings.event_log) if settings.log_dir else None

    tool_limiter = RateLimiter(settings.rate_limit_per_minute * 4)  # herramientas de detalle: un agente encadena varias

    @contextlib.contextmanager
    def mcp_guard(user, tool: str):
        """`/mcp` pasa por los mismos topes que la web (HU-19, OP-04): ritmo por usuario, tope diario y atribución."""
        from converdata.integration.mcp.server import ToolDenied

        if not (limiter if tool == "discover" else tool_limiter).check(f"user:{user.user_id.lower()}"):
            metrics.increment("rate_limited")
            raise ToolDenied("Demasiadas llamadas en un minuto; espera un momento.")
        if tool == "discover" and tokens.exceeded(user.user_id):
            metrics.increment("token_limit")
            raise ToolDenied("Alcanzaste el tope diario de tokens de IA; se restablece mañana (UTC). "
                             "Puedes seguir usando search_catalog y las fichas de activos.")
        with tokens.as_user(user.user_id):
            yield

    mcp_mount = build_mcp_mount(runtime, vault, settings, guard=mcp_guard) if settings.mcp_enabled else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            if mcp_mount is None:
                yield
            else:
                async with mcp_mount[1]():  # gestor de sesiones de /mcp
                    yield
        finally:
            runtime.drain(10.0)  # las confirmaciones pendientes de publicar en la BD terminan antes de apagar

    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.production else {}
    app = FastAPI(title="ConverData API", version="0.1.0", description="Enterprise Data Discovery Agent",
                  lifespan=lifespan, **docs)
    app.state.runtime = runtime
    app.state.tokens = app_tokens
    app.state.curation = curation
    app.add_middleware(MetricsMiddleware, metrics=metrics, logger=logger)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["authorization", "content-type"])
    # La última añadida es la más externa: cabeceras de seguridad también en errores, CORS y `/mcp`.
    app.add_middleware(SecurityMiddleware, settings=settings, on_block=metrics.increment)

    # --- dependencias ------------------------------------------------------------------------------
    def current_session(request: Request) -> Session:
        token = request.cookies.get(COOKIE)
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        session = vault.get(token)
        if session is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicia sesión con tu usuario de base de datos")
        return session

    def denied(request: Request, session: Session, needs: str) -> None:
        """Los intentos sobre rutas de otro rol quedan en la auditoría (solo la plantilla de la ruta)."""
        metrics.increment("access_denied")
        route = getattr(request.scope.get("route"), "path", None) or "otras"
        audit.event("access_denied", session.user_id, route=route, method=request.method, needs=needs)

    def client_ip(request: Request) -> str:
        if settings.trust_proxy:  # el proxy propio añade el origen real al final de la lista
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
            if forwarded:
                return forwarded
        return request.client.host if request.client else "desconocido"

    def admin_session(request: Request, session: Session = Depends(current_session)) -> Session:
        if not session.is_admin:
            denied(request, session, "data_admin")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador de datos puede hacer esto")
        return session

    def identity_trusted(server_ids) -> bool:
        """¿Vale el nombre del login para dar un rol? Quien administra un servidor de desarrollo o de QA puede crear
        allí un login con cualquier nombre. Por eso los roles que se asignan por nombre (lista de administradores y
        responsables) solo cuentan si la sesión validó ese login en un servidor de producción, cuando el inventario
        tiene alguno (F14)."""
        production = {s.id for s in runtime.inventory.servers if s.environment == "produccion"}
        return not production or bool(production & set(server_ids))

    def domains_of(session: Session) -> list[str] | None:
        """Dominios que puede curar: `["*"]` para data_admin, los suyos para un steward, None para consumer (F24)."""
        if session.is_admin:
            return ["*"]
        if not identity_trusted(session.servers):
            return None
        return curation.steward_domains(session.user_id)

    def roles_of(session: Session) -> list[str]:
        roles = ["consumer"]
        if domains_of(session) is not None:
            roles.append("steward")
        if session.is_admin:
            roles.append("data_admin")
        return roles

    def steward_session(request: Request, session: Session = Depends(current_session)) -> Session:
        if domains_of(session) is None:
            denied(request, session, "steward")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "La vista Curación es solo para responsables de datos")
        return session

    def can_curate(session: Session, domain: str | None) -> bool:
        domains = domains_of(session)
        return domains is not None and ("*" in domains or (domain or "") in domains)

    def domain_of(service, asset_key: str) -> str | None:
        copies = service.deps.catalog.copies(table_key(asset_key))
        return copies[0].domain if copies else None

    def require_curable(session: Session, service, asset_key: str) -> None:
        """El activo existe y es de un dominio que la sesión cura. Si no lo cura, solo sabe que existe quien ya puede
        verlo con sus permisos de SQL (403); para los demás responde igual que si no existiera (404, F14)."""
        catalog = service.deps.catalog
        if catalog.exists(asset_key):
            if can_curate(session, domain_of(service, asset_key)):
                return
            if catalog.is_visible(asset_key, runtime.visible_ids(session)):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "No eres responsable del dominio de este activo")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo no encontrado")

    def manages_rule(session: Session, service, rule: BusinessRule) -> bool:
        """Una regla la gestiona quien cura todos sus activos. Si sus activos ya no existen (tabla retirada o
        renombrada), solo quien cura el dominio de la regla."""
        keys = [k for k in rule.applies_to if service.deps.catalog.exists(k)]
        if not keys:
            return can_curate(session, rule.domain)
        return all(can_curate(session, domain_of(service, k)) for k in keys)

    @contextlib.contextmanager
    def applying(kind: str, user_id: str, **data):
        """Audita antes de aplicar (sin registro no hay cambio, F11). Si el cambio falla, deja constancia de que lo
        anunciado no se aplicó."""
        audit.event(kind, user_id, **data)
        try:
            yield
        except Exception as exc:
            with contextlib.suppress(Exception):
                audit.event(f"{kind}_failed", user_id, error_type=type(exc).__name__, **data)
            raise

    def check_rate(session: Session) -> None:
        if not limiter.check(f"user:{session.user_id.lower()}"):  # por usuario: abrir más sesiones no da más cupo
            metrics.increment("rate_limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Hiciste más de {settings.rate_limit_per_minute} preguntas en un minuto; espera un momento")

    DEGRADED_NOTE = "Alcanzaste el tope diario de IA: esta respuesta salió sin IA generativa (búsqueda determinista)."

    def pick_service(session: Session, service):
        """(servicio, degradado): con el tope agotado, rechaza o responde sin LLM según `token_limit_mode` (HU-19)."""
        if not tokens.exceeded(session.user_id):
            return service, False
        if settings.token_limit_mode == "deterministic":
            metrics.increment("token_limit_deterministic")
            return runtime.deterministic_service() or service, True
        metrics.increment("token_limit")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Alcanzaste el tope diario de {tokens.limit:,} tokens de IA; se restablece mañana (UTC). "
                            "Puedes seguir explorando el catálogo.")

    def require_service():
        runtime.refresh()  # si el Builder publicó un catálogo nuevo en la BD, se carga aquí (como mucho cada 15 s)
        if runtime.service is None:
            detail = ("No se pudo cargar el catálogo; avisa a un administrador" if runtime.load_error
                      else "Aún no hay catálogo: un administrador debe descubrir los esquemas")
            raise HTTPException(status.HTTP_409_CONFLICT, detail)
        return runtime.service

    def user_payload(session: Session) -> dict:
        return {"user_id": session.user_id, "roles": roles_of(session), "domains": domains_of(session), "servers": [
            {"id": s, "alias": runtime.inventory.alias(s)} for s in session.servers
        ]}

    # --- estado ------------------------------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/health/metrics")
    def health_metrics(session: Session = Depends(admin_session)):
        """Contadores para el monitoreo (HU-22, OP-05): peticiones, errores, p50/p95 y bloqueos; sin contenido de preguntas."""
        return metrics.snapshot()

    @app.get("/setup/status")
    def setup_status():
        """Público: lo necesario para pintar el login y la pantalla de primer arranque (sin hosts)."""
        return {
            "has_inventory": bool(runtime.inventory.servers),
            "servers": [{"id": s.id, "alias": s.alias, "environment": s.environment} for s in runtime.inventory.servers],
            "has_catalog": runtime.service is not None,
            "load_error": "No se pudo cargar el catálogo; revisa el log del servidor" if runtime.load_error else None,
            "setup_token_required": bool(settings.setup_token) and not runtime.inventory.servers,
            "catalog": runtime.catalog_stats(),
            "build": {"status": runtime.job.status, "finished_at": runtime.job.finished_at},
            "llm": settings.models_path is not None,
            "demo": settings.demo,
            "windows_auth": settings.allow_windows_auth and not settings.demo,
        }

    # --- autenticación (OP-03) ---------------------------------------------------------------------
    @app.post("/login")  # OP-04
    @app.post("/auth/login")
    def login(body: LoginRequest, request: Request, response: Response):
        windows = body.auth == "windows"
        if windows and not settings.allow_windows_auth:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La autenticación de Windows no está habilitada")
        if not windows and not (body.login and body.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escribe tu usuario y contraseña de base de datos")
        login_name = None if windows else body.login.strip()
        login_key, ip_key = f"login:{(login_name or 'windows').lower()}", f"ip:{client_ip(request)}"
        wait = max(login_throttle.retry_after(login_key), ip_throttle.retry_after(ip_key))
        if wait:  # bloqueado: ni siquiera se prueba la credencial contra SQL Server
            metrics.increment("login_locked")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "Demasiados intentos fallidos; espera unos minutos antes de volver a intentar",
                                headers={"Retry-After": str(wait)})

        first_run = not runtime.inventory.servers
        if first_run:
            if not body.host:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indica el servidor SQL Server al que se conecta el agente")
            # Quien registra el primer servidor decide a dónde viajarán las credenciales de todos: exige el secreto
            # del instalador cuando está configurado (obligatorio en qa/prod).
            if settings.setup_token and not hmac.compare_digest((body.setup_token or "").encode(), settings.setup_token.encode()):
                audit.event("setup_denied", login_name or "windows")
                ip_throttle.failure(ip_key)
                raise HTTPException(status.HTTP_403_FORBIDDEN, "El código de instalación no es correcto")
            if settings.production and body.trust_server_certificate:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "En este ambiente el certificado del servidor debe validarse")
            targets = [server_from_host(body.host.strip(), body.alias, body.environment, body.trust_server_certificate,
                                        runtime.inventory)]
        else:
            wanted = set(body.servers) if body.servers else None
            targets = [s for s in runtime.inventory.servers if wanted is None or s.id in wanted]
            if not targets:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Elige al menos un servidor")

        ok: list[tuple[ServerConfig, Credential]] = []
        errors: dict[str, str] = {}
        infos = []
        bad_credentials = False
        for server in targets:
            cred = Credential(server.id, login_name, body.password if not windows else None)
            try:
                infos.append(connector.identify(server, cred))
                ok.append((server, cred))
            except LoginFailed as exc:
                errors[server.alias] = str(exc)
                bad_credentials = bad_credentials or exc.credentials
        if not ok:
            audit.event("login_failed", login_name or "windows", servers=list(errors))
            metrics.increment("login_failed")
            if bad_credentials:  # un servidor caído no cuenta para el bloqueo
                locked = login_throttle.failure(login_key)
                locked = ip_throttle.failure(ip_key) or locked
                if locked:
                    audit.event("login_locked", login_name or "windows", lockout_s=settings.login_lockout_s)
            detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail or "No se pudo iniciar sesión")

        user_id = infos[0].sql_login
        listed = user_id.lower() in settings.admins and identity_trusted([s.id for s, _ in ok])
        sql_admin = any(i.can_build for i in infos)
        # Con `admins_only` (obligatorio en qa/prod) ser sysadmin de un servidor cualquiera no da el rol de administrador.
        can_build = listed if settings.admins_only else (sql_admin or listed)
        if first_run:
            if not (can_build and (sql_admin or listed)):  # el primer servidor solo lo registra quien puede descubrirlo
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "Para la configuración inicial se necesita un login con VIEW ANY DEFINITION o sysadmin")
            with applying("inventory_updated", user_id, first_run=True,
                          servers=[{"id": s.id, "host": s.host, "trust_server_certificate": s.trust_server_certificate}
                                   for s, _ in ok]):
                runtime.save_inventory([s for s, _ in ok], by=user_id)
        roles = ["consumer", "data_admin"] if can_build else ["consumer"]
        session = vault.create(user_id, [c for _, c in ok], roles)
        login_throttle.success(login_key)
        try:
            audit.event("login", user_id, servers=session.servers, roles=roles_of(session), failed=list(errors))
        except Exception:  # fail-closed: sin registro de auditoría no hay sesión
            vault.drop(session.id)
            raise
        lifetime = min(settings.session_ttl_s, settings.session_max_age_s or settings.session_ttl_s)
        response.set_cookie(COOKIE, session.id, httponly=True, samesite="lax", secure=settings.cookie_secure,
                            max_age=lifetime, path="/")
        ok_ids = {s.id for s, _ in ok}
        visible = runtime.visible_ids(session)
        catalog_objects = runtime.service.deps.catalog.objects if runtime.service else []
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=lifetime)
        return {  # OP-04: {session_id, expires_at, servers: [{alias, ok}], databases[]}
            "session_id": session.id, "token": session.id, "expires_at": expires.isoformat(timespec="seconds"),
            "servers": [{"alias": s.alias, "ok": s.id in ok_ids} for s in targets],
            "databases": sorted({o.database for o in catalog_objects if o.id in visible}),
            "user": user_payload(session), "warnings": errors,
        }

    @app.post("/logout")
    @app.post("/auth/logout")
    def logout(response: Response, session: Session = Depends(current_session)):
        runtime.forget(session)
        vault.drop(session.id)
        audit.event("logout", session.user_id)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/auth/me")
    def me(session: Session = Depends(current_session)):
        return user_payload(session)

    # --- DiscoverFlow (F22) ------------------------------------------------------------------------
    def remember(envelope: AnswerEnvelope, question: str, session: Session, service, asked_at: float) -> None:
        disc = envelope.discovery
        keys: set[str] = set()
        domain = None
        if disc is not None:
            keys = {c.asset_key for c in disc.candidates} | {a.asset_key for a in disc.alternatives}
            if disc.candidates:
                domain = domain_of(service, disc.candidates[0].asset_key)
        runtime.remember(envelope.trace_id, ShownTrace(session.user_id, question, keys, domain, asked_at))

    @app.post("/discover")
    def discover(body: DiscoverRequest, response: Response, session: Session = Depends(current_session),
                 service=Depends(require_service)):
        check_rate(session)
        run_service, degraded = pick_service(session, service)
        asked_at = time.time()
        with tokens.as_user(session.user_id):
            envelope = run_service.run(body.question, runtime.user_context(session), history=body.history, client="web")
        if degraded:
            envelope.assumptions.append(DEGRADED_NOTE)
        remember(envelope, body.question, session, service, asked_at)
        response.headers["X-Trace-Id"] = envelope.trace_id  # OP-05: para cruzar con la auditoría y los logs
        return envelope.model_dump(by_alias=True, mode="json")

    @app.post("/discover/stream")
    def discover_stream(body: DiscoverRequest, session: Session = Depends(current_session),
                        service=Depends(require_service)):
        """Lo mismo por SSE: un evento `step` por nodo del grafo y al final `answer` (F12, OP-04 CA8)."""
        check_rate(session)
        run_service, degraded = pick_service(session, service)
        user = runtime.user_context(session)
        asked_at = time.time()

        def events():
            steps = run_service.stream(body.question, user, history=body.history, client="web")
            while True:
                with tokens.as_user(session.user_id):  # cada paso corre en un hilo con su propio contexto
                    try:
                        kind, payload = next(steps)
                    except StopIteration:
                        break
                if kind == "answer":
                    if degraded:
                        payload.setdefault("assumptions", []).append(DEGRADED_NOTE)
                    remember(AnswerEnvelope.model_validate(payload), body.question, session, service, asked_at)
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

    @app.post("/discover/feedback")
    def feedback(body: FeedbackRequest, session: Session = Depends(current_session)):
        check_rate(session)  # cada voto reindexa las confirmaciones
        trace = runtime.shown(body.trace_id)
        if trace is None or trace.user_id != session.user_id or body.asset_key not in trace.asset_keys:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa respuesta ya no está disponible para calificarla")
        steward = runtime.service is not None and can_curate(session, domain_of(runtime.service, body.asset_key))
        return runtime.record_feedback(session, body.trace_id, trace, body.asset_key, body.verdict, steward=steward)

    # --- escalamiento al responsable (F24, HU-30) --------------------------------------------------
    @app.post("/curation/requests")
    def escalate(body: EscalateRequest, session: Session = Depends(current_session)):
        trace = runtime.shown(body.trace_id)
        if trace is None or trace.user_id != session.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa respuesta ya no está disponible para escalarla")
        domain = trace.domain or "sin_dominio"
        with applying("curation_request", session.user_id, domain=domain, trace_id=body.trace_id):
            req = curation.create_request(session.user_id, body.trace_id, trace.question, domain,
                                          sorted(trace.asset_keys), body.note)
        return {"id": req["id"], "domain": req["domain"], "status": req["status"]}

    @app.get("/me/requests")
    def my_requests(session: Session = Depends(current_session)):
        """Mis dudas escaladas. La respuesta sigue filtrada por mis permisos (F24 §Permisos)."""
        ids = runtime.visible_ids(session)
        out = []
        for r in reversed(curation.requests()):
            if r["user_id"] != session.user_id:
                continue
            answer = r.get("answer")
            shown_answer = None
            if answer:
                key = answer.get("asset_key")
                visible = bool(key and runtime.service and runtime.service.deps.catalog.is_visible(key, ids))
                needs_access = bool(key) and not visible
                shown_answer = {
                    # Sin acceso al activo solo se le dice que lo pida: la nota libre podría nombrar objetos (F24).
                    "kind": answer["kind"], "at": answer["at"], "note": None if needs_access else answer.get("note"),
                    "asset_key": key if visible else None,
                    "needs_access": needs_access,
                }
            out.append({"id": r["id"], "created_at": r["created_at"], "status": r["status"], "question": r["question"],
                        "domain": r["domain"], "answer": shown_answer})
        return {"items": out}

    def reject_pii(*texts: str | None) -> None:
        """OP-06 CA5: lo que escribe un responsable se indexa, lo ven todos y viaja al LLM; no puede llevar datos personales."""
        found = sorted({kind for text in texts if text for kind in find_pii(text)})
        if found:
            metrics.increment("pii_rejected")
            raise HTTPException(422,
                                "El texto parece contener datos personales (" + ", ".join(found) + "). Describe el dato "
                                "sin ejemplos reales.")

    # --- vista Curación del responsable (F24, HU-30, HU-31) -----------------------------------------
    @app.get("/curation/requests")
    def curation_inbox(status_: Literal["open", "answered", "all"] = Query("open", alias="status"),
                       session: Session = Depends(steward_session)):
        """Bandeja del responsable: dudas escaladas de sus dominios, la más reciente primero."""
        items = []
        for r in reversed(curation.requests()):
            if not can_curate(session, r["domain"]):
                continue
            if status_ == "open" and r["status"] != "open" or status_ == "answered" and r["status"] == "open":
                continue
            item = {k: r.get(k) for k in ("id", "created_at", "status", "user_id", "question", "domain", "shown",
                                          "note", "answer")}
            # Lo que vio quien preguntó puede incluir activos de otros dominios: aquí solo los que este responsable cura.
            item["shown"] = [k for k in r.get("shown") or []
                             if runtime.service is not None and can_curate(session, domain_of(runtime.service, k))]
            items.append(item)
        return {"items": items}

    @contextlib.contextmanager
    def curating():
        """Una edición de curación de principio a fin: las comprobaciones y la escritura corren bajo un solo candado
        y sobre el catálogo vigente (si el Builder publicó entre tanto, primero se carga lo suyo)."""
        with runtime.editing() as service:
            if service is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "Aún no hay catálogo: un administrador debe descubrir los esquemas")
            yield service

    @app.post("/curation/requests/{request_id}/answer")
    def curation_answer(request_id: str, body: AnswerRequest, session: Session = Depends(steward_session),
                        _service=Depends(require_service)):
        with curating() as service:
            req = next((r for r in curation.requests() if r["id"] == request_id), None)
            if req is None or not can_curate(session, req["domain"]):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada")
            if body.kind == "asset":
                # El activo debe ser de un dominio que este responsable cura: si no, podría documentar cualquier tabla.
                if (not body.asset_key or not service.deps.catalog.exists(body.asset_key)
                        or not can_curate(session, domain_of(service, body.asset_key))):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                        "Elige un activo de tus dominios que exista en el catálogo")
            reject_pii(body.description, body.note)
            with applying("curation_answer", session.user_id, request_id=request_id, answer_kind=body.kind,
                          asset_key=body.asset_key, domain=req["domain"], described=bool(body.description)):
                if body.kind == "asset":
                    if body.description:
                        runtime.write_descriptions(
                            human_edits(service.deps.catalog, body.asset_key, body.description, None),
                            session.user_id, "curation")
                    # F24 CA1: entra de inmediato; la siguiente pregunta equivalente ya encuentra la respuesta.
                    runtime.steward_golden(req["question"], body.asset_key, session.user_id)
                # Solo si lo anterior se escribió: una solicitud no queda "respondida" con un cambio que falló.
                answered = curation.answer_request(request_id, session.user_id, body.kind,
                                                   body.asset_key if body.kind == "asset" else None, body.note)
        return {"ok": True, "request": answered}

    @app.get("/curation/review")
    def curation_review(domain: str | None = None, limit: int = 100, session: Session = Depends(steward_session),
                        service=Depends(require_service)):
        """Cola de revisión: tablas y columnas sin descripción o con descripción generada, por demanda (F24)."""
        demand = demand_by_asset(audit.recent(5000, kind="question"))
        seen: set[str] = set()
        items = []
        for o in service.deps.catalog.objects:
            if o.asset_key in seen or (domain and o.domain != domain) or not can_curate(session, o.domain):
                continue
            seen.add(o.asset_key)
            base = {"database": o.database, "table": o.name, "domain": o.domain}
            if o.description_source == "generated" or not o.description:
                items.append({**base, "asset_key": o.asset_key, "kind": "table", "column": None, "data_type": None,
                              "description": o.description, "description_source": o.description_source,
                              "demand": demand.get(o.asset_key, 0)})
            for c in o.columns:
                if c.description_source == "generated" or not c.description:
                    key = o.column_asset_key(c.name)
                    items.append({**base, "asset_key": key, "kind": "column", "column": c.name, "data_type": c.type,
                                  "description": c.description, "description_source": c.description_source,
                                  "demand": demand.get(key, 0)})
        items.sort(key=lambda i: (-i["demand"], i["asset_key"].lower()))
        return {"items": items[: max(1, min(limit, 500))]}

    @app.put("/curation/description")
    def curation_description(body: DescriptionRequest, session: Session = Depends(steward_session),
                             _service=Depends(require_service)):
        with curating() as service:
            require_curable(session, service, body.asset_key)
            reject_pii(body.description, *(body.synonyms or []))
            with applying("curation_description", session.user_id, asset_key=body.asset_key):
                copies = runtime.write_descriptions(
                    human_edits(service.deps.catalog, body.asset_key, body.description, body.synonyms),
                    session.user_id, "curation")
        return {"ok": True, "copies": copies}

    @app.get("/curation/history")
    def curation_history(asset_key: str = Query(max_length=400), session: Session = Depends(steward_session),
                         service=Depends(require_service)):
        """Versiones de la descripción de un activo con su autor y su fecha (RF-34). Sale del historial temporal de la
        BD `ConverData`; sin ella (desarrollo) no hay historial. Lo lee quien cura el activo y además puede verlo con
        sus permisos de SQL: ser responsable no da lectura de lo que el login no alcanza (F14)."""
        require_curable(session, service, asset_key)
        if not service.deps.catalog.is_visible(asset_key, runtime.visible_ids(session)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo no encontrado")
        if runtime.repository is None:
            return {"available": False, "items": []}
        items = []
        for row in runtime.repository.description_history(asset_key):
            environment, _, rest = row["physical_id"].partition(":")
            items.append({
                "description": row["description"], "description_source": row["description_source"],
                "modified_by": row["modified_by"], "environment": environment,
                "server_alias": runtime.inventory.alias(rest.split(".")[0]),
                "valid_from": row["valid_from"].isoformat(timespec="seconds") + "Z",
                "valid_to": row["valid_to"].isoformat(timespec="seconds") + "Z" if row["valid_to"] else None,
            })
        items.reverse()  # lo más reciente primero
        return {"available": True, "items": items[:200]}

    # --- diccionario de datos (HU-25, F23 CA1) --------------------------------------------------------
    @app.post("/curation/dictionary")
    def curation_dictionary(body: DictionaryRequest, session: Session = Depends(steward_session),
                            _service=Depends(require_service)):
        reject_pii(body.csv)
        with curating() as service:
            plan = plan_dictionary(service.deps.catalog, body.csv,
                                   lambda key: can_curate(session, domain_of(service, key)))
            # "Fuera de tu dominio" solo para lo que este login ya puede ver; lo demás, como si no existiera (F14).
            visible = runtime.visible_ids(session)
            hidden = [k for k in plan.forbidden if not service.deps.catalog.is_visible(k, visible)]
            plan.forbidden = [k for k in plan.forbidden if k not in hidden]
            plan.unknown += hidden
            if not plan.edits:  # el mismo archivo dos veces no hace nada: ni escribe ni reindexa (F23 CA5)
                report = plan.report(0)
            else:
                with applying("curation_dictionary_started", session.user_id, size=len(body.csv)):
                    report = plan.report(runtime.write_descriptions(plan.edits, session.user_id, "dictionary"))
        audit.event("curation_dictionary", session.user_id, applied=report["applied"], skipped_human=report["skipped_human"],
                    unknown=len(report["unknown"]), unchanged=report["unchanged"])
        report["unknown"], report["forbidden"] = report["unknown"][:50], report["forbidden"][:50]
        return report

    # --- reglas de negocio gestionadas (HU-28, F23 CA4) ----------------------------------------------
    def rule_scope(session: Session, service, asset_keys: list[str]) -> None:
        for key in asset_keys:
            require_curable(session, service, key)

    @app.get("/curation/rules")
    def curation_rules(session: Session = Depends(steward_session), service=Depends(require_service)):
        rules = [r for r in runtime.curated_rules() if manages_rule(session, service, r)]
        return {"items": [r.model_dump(exclude_none=True) for r in rules]}

    @app.put("/curation/rules")
    def curation_rule_upsert(body: RuleRequest, session: Session = Depends(steward_session),
                             _service=Depends(require_service)):
        reject_pii(body.text)
        with curating() as service:
            rule_scope(session, service, body.applies_to)
            existing = next((r for r in service.deps.knowledge.rules if r.id == body.id), None)
            # No se pisa una regla de otro dominio ni una importada con el catálogo (y no se dice a qué activo aplica).
            if existing is not None and (existing not in runtime.curated_rules() or not manages_rule(session, service, existing)):
                raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una regla con ese identificador")
            rule = BusinessRule(id=body.id, text=body.text, applies_to=body.applies_to, domain=body.domain,
                                source=f"steward:{session.user_id}", owner=session.user_id, reviewed=True)
            with applying("curation_rule", session.user_id, rule_id=body.id, assets=len(body.applies_to)):
                runtime.upsert_rule(rule, session.user_id)
        return {"ok": True, "rule": rule.model_dump(exclude_none=True)}

    @app.delete("/curation/rules/{rule_id}")
    def curation_rule_delete(rule_id: str, session: Session = Depends(steward_session), _service=Depends(require_service)):
        with curating() as service:
            rule = next((r for r in runtime.curated_rules() if r.id == rule_id), None)
            if rule is None or not manages_rule(session, service, rule):  # la de otro dominio responde como inexistente
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Regla no encontrada")
            with applying("curation_rule_deleted", session.user_id, rule_id=rule_id):
                runtime.delete_rule(rule_id, session.user_id)
        return {"ok": True}

    # --- impacto (F25, HU-23) ------------------------------------------------------------------------
    @app.get("/admin/metrics")
    def admin_metrics(days: int = 30, session: Session = Depends(admin_session)):
        days = max(1, min(days, 365))
        return metrics_report(audit.recent(20000, days=days + 1), curation.requests(), days)

    # --- explorador del catálogo -------------------------------------------------------------------
    def visible_objects(session: Session, service):
        ids = runtime.visible_ids(session)
        return [o for o in service.deps.catalog.objects if o.id in ids]

    @app.get("/catalog/databases")
    def catalog_databases(session: Session = Depends(current_session), service=Depends(require_service)):
        groups: dict[tuple[str, str, str], dict] = {}
        for o in visible_objects(session, service):
            g = groups.setdefault((o.environment, o.server, o.database), {
                "database": o.database, "server": o.server, "server_alias": runtime.inventory.alias(o.server),
                "environment": o.environment, "domain": o.domain, "tables": 0, "views": 0, "procedures": 0, "columns": 0,
            })
            g[{"table": "tables", "view": "views", "procedure": "procedures"}[o.kind]] += 1
            g["columns"] += len(o.columns)
        return sorted(groups.values(), key=lambda g: (g["database"], g["environment"]))

    @app.get("/catalog/objects")
    def catalog_objects(
        database: str | None = None, q: str | None = None, kind: Literal["table", "view", "procedure"] | None = None,
        limit: int = 200, session: Session = Depends(current_session), service=Depends(require_service),
    ):
        needle = (q or "").strip().lower()
        rows = []
        for o in visible_objects(session, service):
            if (database and o.database != database) or (kind and o.kind != kind):
                continue
            if needle:
                hay = " ".join([o.asset_key, o.description or "", *o.synonyms, *(c.name for c in o.columns)]).lower()
                if needle not in hay:
                    continue
            rows.append({
                "id": o.id, "asset_key": o.asset_key, "kind": o.kind, "database": o.database, "schema": o.schema_,
                "name": o.name, "environment": o.environment, "server_alias": runtime.inventory.alias(o.server),
                "description": o.description, "description_source": o.description_source, "row_count": o.row_count,
                "columns": len(o.columns), "pii_columns": sum(c.pii for c in o.columns),
            })
        rows.sort(key=lambda r: r["asset_key"].lower())
        return {"total": len(rows), "items": rows[: max(1, min(limit, 1000))]}

    @app.get("/catalog/object")
    def catalog_object(id: str, session: Session = Depends(current_session), service=Depends(require_service)):
        if id not in runtime.visible_ids(session):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Objeto no encontrado")
        return object_detail(service.deps.catalog.get(id), session, service)

    @app.get("/assets/{asset_key:path}")
    def asset(asset_key: str, session: Session = Depends(current_session), service=Depends(require_service)):
        """Ficha del activo (F12) por `asset_key` de tabla o columna; usa la copia de referencia si el usuario la ve."""
        ids = runtime.visible_ids(session)
        copies = service.deps.catalog.visible_copies(table_key(asset_key), ids)
        if not copies:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo no encontrado")
        ref = next((c for c in copies if runtime.inventory.is_reference(c.environment, c.server)), copies[0])
        return object_detail(ref, session, service)

    def object_detail(o, session: Session, service) -> dict:
        catalog, knowledge, owners = service.deps.catalog, service.deps.knowledge, service.deps.owners
        data = o.model_dump(by_alias=True, mode="json")
        data["server_alias"] = runtime.inventory.alias(o.server)
        ids = runtime.visible_ids(session)
        # F14: una FK hacia una tabla que el usuario no ve revelaría su nombre y su llave.
        data["foreign_keys"] = [fk for fk in data.get("foreign_keys", []) if catalog.is_visible(fk["ref"], ids)]
        data["business_rules"] = [  # de la tabla y de sus columnas; ocultas si aplican a objetos no visibles (F14)
            {"id": r.id, "text": r.text, "reviewed": r.reviewed, "applies_to": r.applies_to}
            for r in knowledge.rules
            if any(table_key(a) == o.asset_key for a in r.applies_to)
            and all(catalog.is_visible(a, ids) for a in r.applies_to)
        ]
        dom = owners.for_asset(o.asset_key)
        data["owners"] = {
            "business": dom.business_owner.name if dom and dom.business_owner else None,
            "technical": dom.technical_owner.name if dom and dom.technical_owner else None,
        }
        data["referenced_by"] = sorted({
            other.asset_key for other in catalog.objects
            if other.id in ids for fk in other.foreign_keys if table_key(fk.ref) == o.asset_key
        })
        data["copies"] = [
            {"id": c.id, "environment": c.environment, "server_alias": runtime.inventory.alias(c.server)}
            for c in catalog.visible_copies(o.asset_key, ids) if c.id != o.id
        ]
        return data

    # --- administración: inventario, construcción y auditoría --------------------------------------
    @app.get("/admin/inventory")
    def get_inventory(session: Session = Depends(admin_session)):
        return {"servers": [
            {**s.model_dump(include={"id", "host", "alias", "environment", "is_reference", "databases",
                                     "trust_server_certificate"}),
             "connected": s.id in session.servers}
            for s in runtime.inventory.servers
        ]}

    CERTIFICATE_REQUIRED = "En este ambiente el certificado del servidor debe validarse"
    # La BD de trabajo no se cataloga a sí misma, se llame como se llame (igual que `AgentRuntime._run_build`).
    excluded_databases = {d.lower() for d in SYSTEM_DATABASES | OWN_DATABASES}
    if settings.db:
        excluded_databases.add(describe_connection(settings.db).split("/")[-1].lower())

    def session_credential(session: Session, server_id: str) -> Credential | None:
        """La credencial con la que se prueba un servidor: la de la sesión si ya lo validó; si no, la misma plantilla
        (login y contraseña con los que inició sesión) que usa `PUT /admin/inventory` con los servidores nuevos."""
        own = vault.credential(session, server_id)
        if own is not None:
            return own
        template = next((c for c in (vault.credential(session, sid) for sid in session.servers) if c), None)
        return None if template is None else Credential(server_id, template.login, template.password)

    # Un solo cambio de inventario a la vez: entre leerlo y guardarlo se prueba una conexión (segundos), y sin esto
    # dos administradores a la vez se pisarían el uno al otro.
    inventory_lock = threading.Lock()

    @contextlib.contextmanager
    def replacing_inventory(session: Session, servers: list[ServerConfig], **data):
        """Cambiar un host redirige las credenciales de todos los usuarios: queda el antes y el después, y antes de
        aplicar. Dentro del bloque se prueban las conexiones; al salir sin error se guarda el inventario."""
        def described(items):
            return [{"id": s.id, "host": s.host, "trust_server_certificate": s.trust_server_certificate} for s in items]

        try:
            with applying("inventory_updated", session.user_id, servers=described(servers),
                          previous=described(runtime.inventory.servers), **data):
                yield
                runtime.save_inventory(servers, by=session.user_id)
        finally:  # también si no se guardó: la sesión no conserva credenciales de servidores fuera del inventario
            session.servers = [s for s in session.servers if runtime.inventory.server(s)]
            runtime.forget(session)

    def already_inventoried(host: str) -> ServerConfig | None:
        return next((s for s in runtime.inventory.servers if (s.host or "").strip().lower() == host.lower()), None)

    @app.put("/admin/inventory")
    def put_inventory(body: InventoryRequest, session: Session = Depends(admin_session)):
        """Reemplaza el inventario. Los servidores nuevos se prueban con la misma credencial de la sesión."""
        if not body.servers:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "El inventario necesita al menos un servidor")
        if len({s.id for s in body.servers}) != len(body.servers):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hay identificadores de servidor repetidos")
        if settings.production and any(s.trust_server_certificate for s in body.servers):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, CERTIFICATE_REQUIRED)
        servers = [ServerConfig(**s.model_dump(), auth="sql") for s in body.servers]
        results = {}
        with inventory_lock, replacing_inventory(session, servers):
            for server in servers:
                cred = None if server.id in session.servers else session_credential(session, server.id)
                if cred is None:
                    continue
                try:
                    connector.identify(server, cred)
                    vault.add_credential(session, cred)
                    results[server.id] = "conectado"
                except LoginFailed as exc:
                    results[server.id] = str(exc)
        return {"ok": True, "connections": results}

    @app.post("/admin/inventory/probe")
    def probe_inventory(body: ProbeRequest, session: Session = Depends(admin_session)):
        """Asistente "Conectar base de datos", paso 1: con la credencial de la sesión, ¿conecta el servidor y qué bases
        de usuario tiene? Por cada una, si el login entra y cuántas tablas y vistas ve. No guarda nada."""
        if bool(body.host) == bool(body.server_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indica el servidor: un host nuevo o uno del inventario")
        if body.server_id:
            server = runtime.inventory.server(body.server_id)
            if server is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Servidor no encontrado")
        else:
            if settings.production and body.trust_server_certificate:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, CERTIFICATE_REQUIRED)
            host = body.host.strip()
            existing = already_inventoried(host)
            if existing is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Ese servidor ya está en el inventario como «{existing.alias}»; "
                                                              "ábrelo desde su fila para añadirle bases")
            server = server_from_host(host, None, "desarrollo", body.trust_server_certificate, runtime.inventory)
        cred = session_credential(session, server.id)
        if cred is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Tu sesión no tiene una credencial que probar; vuelve a iniciar sesión")
        if not limiter.check(f"probe:{session.user_id.lower()}"):  # cada sondeo abre conexiones con tu credencial
            metrics.increment("rate_limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados sondeos en un minuto; espera un momento")
        # Antes de conectar: la credencial del administrador viaja a ese host (sin registro no viaja, F11).
        audit.event("inventory_probe", session.user_id, host=server.host, server_id=body.server_id,
                    trust_server_certificate=server.trust_server_certificate)
        try:
            found = connector.probe(server, cred)
        except LoginFailed as exc:  # su mensaje nunca lleva host, login ni texto del driver
            return {"connected": False, "error": str(exc), "databases": []}
        except Exception as exc:
            log_event(logging.getLogger(__name__), "inventory.probe_failed", logging.WARNING,
                      error_type=type(exc).__name__)
            return {"connected": False, "error": "No se pudo leer el servidor", "databases": []}
        return {"connected": True, "error": None, "databases": [
            dataclasses.asdict(d) for d in found if d.name.lower() not in excluded_databases]}

    @app.post("/admin/inventory/connect", status_code=status.HTTP_202_ACCEPTED)
    def connect_inventory(body: ConnectRequest, session: Session = Depends(admin_session)):
        """Asistente, paso 2: añade un servidor (o cambia las bases de uno del inventario) sin reenviar el resto del
        inventario, comprueba que la credencial de la sesión entra y lanza el descubrimiento."""
        if bool(body.host) == bool(body.server_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indica el servidor: un host nuevo o uno del inventario")
        databases = ["*"] if "*" in body.databases else list(dict.fromkeys(body.databases))
        refused = sorted(d for d in databases if d.lower() in excluded_databases)
        if refused:  # las de sistema y la propia BD de trabajo no se catalogan, aunque lleguen escritas a mano
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Estas bases no se pueden catalogar: {', '.join(refused)}")
        if not limiter.check(f"probe:{session.user_id.lower()}"):  # cada intento envía tu credencial a ese servidor
            metrics.increment("rate_limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos en un minuto; espera un momento")
        with inventory_lock:
            return connect_locked(body, session, databases)

    def connect_locked(body: ConnectRequest, session: Session, databases: list[str]):
        if runtime.job.status == "running":
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay un descubrimiento en curso; espera a que termine")
        current = list(runtime.inventory.servers)
        if body.server_id:
            existing = runtime.inventory.server(body.server_id)
            if existing is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Servidor no encontrado")
            server = existing.model_copy(update={"databases": databases})
            servers = [server if s.id == server.id else s for s in current]
        else:
            if settings.production and body.trust_server_certificate:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, CERTIFICATE_REQUIRED)
            alias = (body.alias or "").strip()
            if not alias:  # el host nunca se muestra a los usuarios: ven solo el nombre visible
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escribe el nombre visible del servidor")
            host = body.host.strip()
            existing = already_inventoried(host)
            if existing is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Ese servidor ya está en el inventario como «{existing.alias}»")
            reference = not any(s.is_reference and s.environment == body.environment for s in current)
            server = server_from_host(host, alias, body.environment, body.trust_server_certificate,
                                      runtime.inventory).model_copy(update={"databases": databases,
                                                                            "is_reference": reference})
            servers = current + [server]
        cred = session_credential(session, server.id)
        if cred is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Tu sesión no tiene una credencial que probar; vuelve a iniciar sesión")
        with replacing_inventory(session, servers, via="connect", server_id=server.id, databases=databases):
            try:
                connector.identify(server, cred)
            except LoginFailed as exc:  # no se guarda un servidor al que la credencial no entra
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No se pudo conectar con tu credencial: {exc}")
            vault.add_credential(session, cred)
        running = runtime.job if runtime.job.status == "running" else None
        job = runtime.start_build(session, body.enrich)
        if job is running:  # otro administrador lo lanzó mientras se probaba la conexión: ese no incluye este servidor
            raise HTTPException(status.HTTP_409_CONFLICT, "El servidor quedó guardado, pero hay otro descubrimiento en "
                                                          "curso; lanza «Descubrir esquemas» cuando termine")
        return {"ok": True, "server": {"id": server.id, "alias": server.alias}, "job": job.__dict__}

    @app.get("/admin/stewards")
    def get_stewards(session: Session = Depends(admin_session)):
        """Responsables de datos por login y dominio (F24; mientras no haya grupos de AD, HU-13)."""
        domains = sorted({o.domain for o in runtime.service.deps.catalog.objects if o.domain}) if runtime.service else []
        return {"stewards": curation.stewards(), "domains": domains}

    @app.put("/admin/stewards")
    def put_stewards(body: StewardsRequest, session: Session = Depends(admin_session)):
        """Reemplaza la lista de responsables. Da y quita un rol: queda en la auditoría antes de aplicarse."""
        wanted = [s.model_dump() for s in body.stewards]
        with applying("stewards_updated", session.user_id, previous=curation.stewards(),
                      stewards=[{"login": s["login"].strip().lower(), "domains": s["domains"]} for s in wanted]):
            return {"ok": True, "stewards": curation.save_stewards(wanted, by=session.user_id)}

    @app.post("/admin/catalog/build", status_code=status.HTTP_202_ACCEPTED)
    def start_build(body: BuildRequest, session: Session = Depends(admin_session)):
        if not runtime.inventory.servers:
            raise HTTPException(status.HTTP_409_CONFLICT, "No hay servidores en el inventario")
        job = runtime.start_build(session, body.enrich)
        return job.__dict__

    @app.get("/admin/catalog/build")
    def build_status(session: Session = Depends(admin_session)):
        return runtime.job.__dict__

    @app.get("/admin/audit")
    def audit_log(limit: int = 100, kind: str | None = Query(None, max_length=40),
                  session: Session = Depends(admin_session)):
        audit.event("audit_read", session.user_id, filter=kind, limit=limit)  # quién consulta la auditoría (F11)
        return {"items": audit.recent(max(1, min(limit, 500)), kind=kind)}

    @app.get("/admin/audit/verify")
    def audit_verify(session: Session = Depends(admin_session)):
        """Comprueba la cadena de hashes de la auditoría (evidencia de manipulación, OP-05)."""
        report = audit.verify()
        if not report.ok:
            metrics.increment("audit_chain_broken")
        return {"ok": report.ok, "head": report.head, "files": [
            {"name": f.name, "rows": f.rows, "legacy": f.legacy, "head": f.head, "errors": f.errors} for f in report.files]}

    # --- documentación interna (manual, wiki y arquitectura) ------------------------------------------------
    # Solo `data_admin`: describe los controles de seguridad, lo que aún no cubren y la deuda. Ningún otro rol de la API
    # (consumer, steward) tiene que ver con mantener la solución. Cada lectura se audita antes de entregarla (F11);
    # el índice solo lleva títulos y rutas. Lo que se sirve es la lista fija de `documentation.py`.
    def library() -> DocumentationLibrary:
        return DocumentationLibrary(settings.docs_dir)

    @app.get("/admin/docs")
    def docs_index(session: Session = Depends(admin_session)):
        """Índice para navegar: páginas Markdown (título, ruta y carpeta) y diagramas de arquitectura."""
        docs = library()
        return {"pages": [dataclasses.asdict(d) for d in docs.pages()],
                "diagrams": [{"path": d.path, "title": d.title} for d in docs.diagrams()]}

    @app.get("/admin/docs/page")
    def docs_page(path: Annotated[str, Query(max_length=300)], session: Session = Depends(admin_session)):
        try:
            page = library().page(path)
        except DocumentNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa página no está en la documentación de este servidor")
        audit.event("doc_read", session.user_id, path=page.path, doc="page")  # sin registro no se entrega
        return {"path": page.path, "title": page.title, "markdown": page.body.decode("utf-8"),
                "updated_at": page.updated_at}

    @app.get("/admin/docs/diagram")
    def docs_diagram(path: Annotated[str, Query(max_length=300)], session: Session = Depends(admin_session)):
        """Diagrama de `docs/architecture/*.html`. Va como texto dentro de JSON, nunca como `text/html`: abierto
        directamente no se ejecuta en el origen de la web. La web lo pinta en un `iframe` con `sandbox` (origen opaco)."""
        try:
            diagram = library().diagram(path)
        except DocumentNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese diagrama no está en la documentación de este servidor")
        audit.event("doc_read", session.user_id, path=diagram.path, doc="diagram")
        return {"path": diagram.path, "title": diagram.title, "html": diagram.body.decode("utf-8"),
                "updated_at": diagram.updated_at}

    @app.get("/admin/manual")
    def manual(session: Session = Depends(admin_session)):
        """El manual de desarrollo solo (la ruta que usaba la web antes del visor de documentación)."""
        try:
            page = library().page(MANUAL)
        except DocumentNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "El manual de desarrollo no está instalado en este servidor")
        audit.event("manual_read", session.user_id)  # sin registro no se entrega; un 404 no cuenta como lectura
        return {"markdown": page.body.decode("utf-8"), "updated_at": page.updated_at}

    @app.get("/admin/sessions")
    def sessions_list(session: Session = Depends(admin_session)):
        """Sesiones activas, sin tokens ni credenciales."""
        def iso(ts: float) -> str:
            return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")
        return {"items": [{"user_id": s.user_id, "roles": s.roles, "servers": s.servers, "created_at": iso(s.created_at),
                           "last_seen": iso(s.last_seen), "current": s.id == session.id} for s in vault.sessions()]}

    @app.delete("/admin/sessions/{user_id}")
    def sessions_revoke(user_id: str, session: Session = Depends(admin_session)):
        """Cierra todas las sesiones de un usuario (baja o incidente); sus tokens dejan de servir de inmediato."""
        for s in vault.sessions():
            if s.user_id.lower() == user_id.lower():
                runtime.forget(s)
        revoked = vault.drop_user(user_id)
        audit.event("sessions_revoked", session.user_id, target=user_id, count=revoked)
        return {"ok": True, "revoked": revoked}

    @app.get("/me/history")
    def my_history(limit: int = 30, session: Session = Depends(current_session)):
        """Preguntas propias registradas en la auditoría (cada usuario solo ve las suyas)."""
        rows = audit.recent(max(1, min(limit, 200)), user_id=session.user_id, kind="question")
        return {"items": [{k: r.get(k) for k in ("ts", "trace_id", "question", "status", "confidence")} for r in rows]}

    if mcp_mount is not None:
        app.mount("/", mcp_mount[0])  # al final: solo atiende `/mcp`, las rutas de la API tienen prioridad

    return app


app = create_app()
