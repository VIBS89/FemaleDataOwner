"""Rutas HTTP de ConverData-API.

    uvicorn converdata_api.main:app --app-dir api     (desde la raíz de DataAgent, un solo worker: OP-03)

La identidad sale solo del token de sesión (cookie `cd_session` o `Authorization: Bearer`); ninguna ruta acepta
`user_id` ni credenciales fuera de `/auth/login` (OP-03).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from converdata.catalog.ids import table_key
from converdata.cli import load_dotenv, use_system_certificates
from converdata.config import ServerConfig
from converdata.models.discovery import AnswerEnvelope
from converdata.models.knowledge import BusinessRule
from converdata.observability.logging import configure_logging, log_event
from converdata.observability.metrics import Metrics

from converdata_api.audit import FileAuditSink
from converdata_api.connector import Connector, DemoConnector, LoginFailed, SqlConnector, server_from_host
from converdata_api.curation import CurationStore, demand_by_asset, metrics_report
from converdata_api.demo import seed_stewards
from converdata_api.mcp_mount import build_mcp_mount
from converdata_api.runtime import AgentRuntime, ShownTrace
from converdata_api.settings import ApiSettings
from converdata_api.vault import Credential, Session, SessionVault

COOKIE = "cd_session"


# --- cuerpos de petición -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    login: str | None = Field(None, max_length=128)  # vacío con auth=windows
    password: str | None = Field(None, max_length=256)
    auth: Literal["sql", "windows"] = "sql"
    servers: list[str] | None = None  # None = todos los del inventario, con la misma credencial
    # Primer arranque (inventario vacío): servidor al que se conecta el agente
    host: str | None = Field(None, max_length=256)
    alias: str | None = Field(None, max_length=80)
    environment: Literal["produccion", "qa", "desarrollo", "dr"] = "desarrollo"
    trust_server_certificate: bool = False


class DiscoverRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[str] = Field(default_factory=list, max_length=10)


class FeedbackRequest(BaseModel):
    trace_id: str
    asset_key: str
    verdict: Literal["confirm", "reject"]
    comment: str | None = Field(None, max_length=500)


class BuildRequest(BaseModel):
    enrich: bool = False


class ServerIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    host: str = Field(min_length=1, max_length=256)
    alias: str = Field(min_length=1, max_length=80)
    environment: Literal["produccion", "qa", "desarrollo", "dr"] = "desarrollo"
    is_reference: bool = False
    databases: list[str] = Field(default_factory=lambda: ["*"])
    trust_server_certificate: bool = False


class InventoryRequest(BaseModel):
    servers: list[ServerIn]


class EscalateRequest(BaseModel):
    trace_id: str
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


class GoldenAction(BaseModel):
    action: Literal["approve", "retire"]


class StewardIn(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    domains: list[str] = Field(default_factory=lambda: ["*"])


class StewardsRequest(BaseModel):
    stewards: list[StewardIn]


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
    vault = SessionVault(settings.session_ttl_s)
    audit = FileAuditSink(settings.audit_dir)
    runtime = AgentRuntime(settings, connector, vault, audit)
    curation = CurationStore(settings.curation_dir, settings.data_root, settings.notify_webhook, settings.public_url)
    runtime.curation = curation
    if settings.demo:
        seed_stewards(curation)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    metrics = Metrics()
    logger = configure_logging(settings.log_dir, event_log=settings.event_log) if settings.log_dir else None

    mcp_mount = build_mcp_mount(runtime, vault, settings) if settings.mcp_enabled else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if mcp_mount is None:
            yield
        else:
            async with mcp_mount[1]():  # gestor de sesiones de /mcp
                yield

    app = FastAPI(title="ConverData API", version="0.1.0", description="Enterprise Data Discovery Agent",
                  lifespan=lifespan)
    app.state.runtime = runtime
    app.state.curation = curation
    app.add_middleware(MetricsMiddleware, metrics=metrics, logger=logger)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

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

    def admin_session(session: Session = Depends(current_session)) -> Session:
        if not session.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador de datos puede hacer esto")
        return session

    def domains_of(session: Session) -> list[str] | None:
        """Dominios que puede curar: `["*"]` para data_admin, los suyos para un steward, None para consumer (F24)."""
        if session.is_admin:
            return ["*"]
        return curation.steward_domains(session.user_id)

    def roles_of(session: Session) -> list[str]:
        roles = ["consumer"]
        if domains_of(session) is not None:
            roles.append("steward")
        if session.is_admin:
            roles.append("data_admin")
        return roles

    def steward_session(session: Session = Depends(current_session)) -> Session:
        if domains_of(session) is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "La vista Curación es solo para responsables de datos")
        return session

    def can_curate(session: Session, domain: str | None) -> bool:
        domains = domains_of(session)
        return domains is not None and ("*" in domains or (domain or "") in domains)

    def domain_of(service, asset_key: str) -> str | None:
        copies = service.deps.catalog.copies(table_key(asset_key))
        return copies[0].domain if copies else None

    def check_rate(session: Session) -> None:
        if not limiter.check(session.id):
            metrics.increment("rate_limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Hiciste más de {settings.rate_limit_per_minute} preguntas en un minuto; espera un momento")

    def require_service():
        if runtime.service is None:
            detail = runtime.load_error or "Aún no hay catálogo: un administrador debe descubrir los esquemas"
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
            "load_error": runtime.load_error,
            "catalog": runtime.catalog_stats(),
            "build": {"status": runtime.job.status, "finished_at": runtime.job.finished_at},
            "llm": settings.models_path is not None,
            "demo": settings.demo,
            "windows_auth": settings.allow_windows_auth and not settings.demo,
        }

    # --- autenticación (OP-03) ---------------------------------------------------------------------
    @app.post("/login")  # OP-04
    @app.post("/auth/login")
    def login(body: LoginRequest, response: Response):
        windows = body.auth == "windows"
        if windows and not settings.allow_windows_auth:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La autenticación de Windows no está habilitada")
        if not windows and not (body.login and body.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escribe tu usuario y contraseña de base de datos")
        login_name = None if windows else body.login.strip()

        first_run = not runtime.inventory.servers
        if first_run:
            if not body.host:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indica el servidor SQL Server al que se conecta el agente")
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
        for server in targets:
            cred = Credential(server.id, login_name, body.password if not windows else None)
            try:
                infos.append(connector.identify(server, cred))
                ok.append((server, cred))
            except LoginFailed as exc:
                errors[server.alias] = str(exc)
        if not ok:
            audit.event("login_failed", login_name or "windows", servers=list(errors))
            metrics.increment("login_failed")
            detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail or "No se pudo iniciar sesión")

        user_id = infos[0].sql_login
        can_build = any(i.can_build for i in infos) or user_id.lower() in settings.admins
        if first_run:
            if not can_build:  # el primer servidor solo lo registra quien puede descubrir sus esquemas
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "Para la configuración inicial se necesita un login con VIEW ANY DEFINITION o sysadmin")
            runtime.save_inventory([s for s, _ in ok])
        roles = ["consumer", "data_admin"] if can_build else ["consumer"]
        session = vault.create(user_id, [c for _, c in ok], roles)
        audit.event("login", user_id, servers=session.servers, roles=roles_of(session), failed=list(errors))
        response.set_cookie(COOKIE, session.id, httponly=True, samesite="lax", secure=settings.cookie_secure,
                            max_age=settings.session_ttl_s, path="/")
        ok_ids = {s.id for s, _ in ok}
        visible = runtime.visible_ids(session)
        catalog_objects = runtime.service.deps.catalog.objects if runtime.service else []
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=settings.session_ttl_s)
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
    def discover(body: DiscoverRequest, session: Session = Depends(current_session), service=Depends(require_service)):
        check_rate(session)
        asked_at = time.time()
        envelope = service.run(body.question, runtime.user_context(session), history=body.history, client="web")
        remember(envelope, body.question, session, service, asked_at)
        return envelope.model_dump(by_alias=True, mode="json")

    @app.post("/discover/stream")
    def discover_stream(body: DiscoverRequest, session: Session = Depends(current_session),
                        service=Depends(require_service)):
        """Lo mismo por SSE: un evento `step` por nodo del grafo y al final `answer` (F12, OP-04 CA8)."""
        check_rate(session)
        user = runtime.user_context(session)
        asked_at = time.time()

        def events():
            for kind, payload in service.stream(body.question, user, history=body.history, client="web"):
                if kind == "answer":
                    remember(AnswerEnvelope.model_validate(payload), body.question, session, service, asked_at)
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

    @app.post("/discover/feedback")
    def feedback(body: FeedbackRequest, session: Session = Depends(current_session)):
        trace = runtime.shown(body.trace_id)
        if trace is None or trace.user_id != session.user_id or body.asset_key not in trace.asset_keys:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa respuesta ya no está disponible para calificarla")
        steward = runtime.service is not None and can_curate(session, domain_of(runtime.service, body.asset_key))
        return runtime.record_feedback(session, body.trace_id, trace, body.asset_key, body.verdict, body.comment,
                                       steward=steward)

    # --- escalamiento al responsable (F24, HU-30) --------------------------------------------------
    @app.post("/curation/requests")
    def escalate(body: EscalateRequest, session: Session = Depends(current_session)):
        trace = runtime.shown(body.trace_id)
        if trace is None or trace.user_id != session.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa respuesta ya no está disponible para escalarla")
        req = curation.create_request(session.user_id, body.trace_id, trace.question, trace.domain or "sin_dominio",
                                      sorted(trace.asset_keys), body.note)
        audit.event("curation_request", session.user_id, request_id=req["id"], domain=req["domain"], trace_id=body.trace_id)
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
                shown_answer = {
                    "kind": answer["kind"], "at": answer["at"], "note": answer.get("note"),
                    "asset_key": key if visible else None,
                    "needs_access": bool(key) and not visible,
                }
            out.append({"id": r["id"], "created_at": r["created_at"], "status": r["status"], "question": r["question"],
                        "domain": r["domain"], "answer": shown_answer})
        return {"items": out}

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
            items.append({k: r.get(k) for k in ("id", "created_at", "status", "user_id", "question", "domain", "shown",
                                                 "note", "answer")})
        return {"items": items}

    @app.post("/curation/requests/{request_id}/answer")
    def curation_answer(request_id: str, body: AnswerRequest, session: Session = Depends(steward_session),
                        service=Depends(require_service)):
        req = next((r for r in curation.requests() if r["id"] == request_id), None)
        if req is None or not can_curate(session, req["domain"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada")
        if body.kind == "asset":
            if not body.asset_key or not service.deps.catalog.exists(body.asset_key):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Elige un activo que exista en el catálogo")
            if body.description:
                curation.set_description(service.deps.catalog, body.asset_key, body.description, None)
            runtime.steward_golden(req["question"], body.asset_key)  # F24 CA1: entra de inmediato
        answered = curation.answer_request(request_id, session.user_id, body.kind,
                                           body.asset_key if body.kind == "asset" else None, body.note)
        runtime.reload()  # la siguiente pregunta equivalente ya encuentra la respuesta
        audit.event("curation_answer", session.user_id, request_id=request_id, answer_kind=body.kind,
                    asset_key=body.asset_key, domain=req["domain"])
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
                             service=Depends(require_service)):
        if not service.deps.catalog.exists(body.asset_key):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo no encontrado")
        if not can_curate(session, domain_of(service, body.asset_key)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No eres responsable del dominio de este activo")
        copies = curation.set_description(service.deps.catalog, body.asset_key, body.description, body.synonyms)
        runtime.reload()
        audit.event("curation_description", session.user_id, asset_key=body.asset_key, copies=copies)
        return {"ok": True, "copies": copies}

    # --- reglas de negocio gestionadas (HU-28, F23 CA4) ----------------------------------------------
    def rule_scope(session: Session, service, asset_keys: list[str]) -> None:
        for key in asset_keys:
            if not service.deps.catalog.exists(key):
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Activo no encontrado: {key}")
            if not can_curate(session, domain_of(service, key)):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"No eres responsable del dominio de {key}")

    @app.get("/curation/rules")
    def curation_rules(session: Session = Depends(steward_session), service=Depends(require_service)):
        rules = [r for r in curation.curated_rules()
                 if all(can_curate(session, domain_of(service, k)) for k in r.applies_to if service.deps.catalog.exists(k))]
        return {"items": [r.model_dump(exclude_none=True) for r in rules]}

    @app.put("/curation/rules")
    def curation_rule_upsert(body: RuleRequest, session: Session = Depends(steward_session),
                             service=Depends(require_service)):
        rule_scope(session, service, body.applies_to)
        existing = next((r for r in curation.curated_rules() if r.id == body.id), None)
        if existing is not None:  # no se pisa una regla de otro dominio
            rule_scope(session, service, [k for k in existing.applies_to if service.deps.catalog.exists(k)])
        rule = BusinessRule(id=body.id, text=body.text, applies_to=body.applies_to, domain=body.domain,
                            source=f"steward:{session.user_id}", owner=session.user_id, reviewed=True)
        curation.upsert_rule(rule)
        runtime.reload()
        audit.event("curation_rule", session.user_id, rule_id=body.id, assets=len(body.applies_to))
        return {"ok": True, "rule": rule.model_dump(exclude_none=True)}

    @app.delete("/curation/rules/{rule_id}")
    def curation_rule_delete(rule_id: str, session: Session = Depends(steward_session), service=Depends(require_service)):
        rule = next((r for r in curation.curated_rules() if r.id == rule_id), None)
        if rule is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Regla no encontrada")
        rule_scope(session, service, [k for k in rule.applies_to if service.deps.catalog.exists(k)])
        curation.delete_rule(rule_id)
        runtime.reload()
        audit.event("curation_rule_deleted", session.user_id, rule_id=rule_id)
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

    @app.put("/admin/inventory")
    def put_inventory(body: InventoryRequest, session: Session = Depends(admin_session)):
        """Reemplaza el inventario. Los servidores nuevos se prueban con la misma credencial de la sesión."""
        if not body.servers:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "El inventario necesita al menos un servidor")
        if len({s.id for s in body.servers}) != len(body.servers):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hay identificadores de servidor repetidos")
        servers = [ServerConfig(**s.model_dump(), auth="sql") for s in body.servers]
        template = next((c for c in (vault.credential(session, sid) for sid in session.servers) if c), None)
        results = {}
        for server in servers:
            if server.id in session.servers or template is None:
                continue
            cred = Credential(server.id, template.login, template.password)
            try:
                connector.identify(server, cred)
                vault.add_credential(session, cred)
                results[server.id] = "conectado"
            except LoginFailed as exc:
                results[server.id] = str(exc)
        runtime.save_inventory(servers)
        session.servers = [s for s in session.servers if runtime.inventory.server(s)]
        runtime.forget(session)
        audit.event("inventory_updated", session.user_id, servers=[s.id for s in servers])
        return {"ok": True, "connections": results}

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
    def audit_log(limit: int = 100, kind: str | None = None, session: Session = Depends(admin_session)):
        return {"items": audit.recent(max(1, min(limit, 500)), kind=kind)}

    @app.get("/me/history")
    def my_history(limit: int = 30, session: Session = Depends(current_session)):
        """Preguntas propias registradas en la auditoría (cada usuario solo ve las suyas)."""
        rows = audit.recent(max(1, min(limit, 200)), user_id=session.user_id, kind="question")
        return {"items": [{k: r.get(k) for k in ("ts", "trace_id", "question", "status", "confidence")} for r in rows]}

    if mcp_mount is not None:
        app.mount("/", mcp_mount[0])  # al final: solo atiende `/mcp`, las rutas de la API tienen prioridad

    return app


app = create_app()
