"""Estado del proceso: inventario, DiscoverService del catálogo actual, visibilidad por sesión y la construcción del catálogo.

El primer arranque no tiene catálogo: un admin inicia sesión con su usuario de BD, lanza el CatalogBuildFlow con esa
credencial y, al terminar, el DiscoverService se carga con lo descubierto (F1, F18). Cada reconstrucción sube `version`
y las visibilidades se recalculan con la credencial de cada sesión (F14).

Con `DISCOVERY_DATA_AGENT_DB` definida todo el estado vive en la BD `DiscoveryDataAgent` (OP-02, HU-09): el catálogo y el conocimiento se
cargan de ella en memoria (no hay copia en el disco del servidor), se vuelven a cargar cuando otro proceso publica
(el Builder programado) y cada edición de curación escribe sus filas (`KnowledgeWriter`). Sin la variable (desarrollo y
modo demo), `data_root` es el catálogo y la curación edita sus archivos.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from discovery_data_agent.application.catalog_refresh import refresh_catalog
from discovery_data_agent.bootstrap import Stores, build_service, build_service_from_snapshot, open_stores
from discovery_data_agent.catalog.ids import physical_id
from discovery_data_agent.catalog.store import CatalogSnapshot
from discovery_data_agent.config import Inventory, ServerConfig
from discovery_data_agent.curation import (DescriptionEdit, golden_id, has_literals, question_template, resolve_golden,
                                 steward_rules, strip_literals, tally)
from discovery_data_agent.flows.discover import DiscoverService
from discovery_data_agent.models.identity import UserContext
from discovery_data_agent.models.knowledge import BusinessRule, GoldenDiscovery
from discovery_data_agent.storage.connection import describe

from discovery_data_agent_api.connector import Connector
from discovery_data_agent_api.demo import apply_fixture_knowledge, demo_inventory
from discovery_data_agent_api.demo_history import HISTORY_MARKER, seed_history
from discovery_data_agent_api.pii import find_pii
from discovery_data_agent_api.settings import ApiSettings
from discovery_data_agent_api.vault import Session, SessionVault

log = logging.getLogger(__name__)
MAX_TRACES = 500
FIGURE_TIMEOUT_S = 15  # tope de una consulta de cifras; pasado ese tiempo se responde sin el número
FIGURE_MAX_ROWS = 50  # un total, o los grupos de un desglose: nunca un volcado de filas
FIGURE_CONCURRENCY = 2  # cifras calculándose a la vez en toda la API: no se carga la operación del banco
ASK_TIMEOUT_S = 30  # fase 1b: una consulta con varias uniones o un periodo largo puede tardar más que una cifra
ASK_SLOT_WAIT_S = 10  # espera por un turno de ejecución: una pregunta encadena sondeos y la consulta final


@dataclass
class BuildJob:
    status: str = "idle"  # idle | running | ok | error
    started_at: str | None = None
    finished_at: str | None = None
    triggered_by: str | None = None
    enrich: bool = False
    report: dict | None = None
    summary: str | None = None
    error: str | None = None


@dataclass
class ShownTrace:
    """Lo que se mostró en una respuesta: la retroalimentación solo acepta activos de aquí (no se puede envenenar F24)."""

    user_id: str
    question: str
    asset_keys: set[str] = field(default_factory=set)
    domain: str | None = None  # dominio del candidato principal: a quién se escala (F24)
    asked_at: float = field(default_factory=time.time)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def open_api_stores(settings: ApiSettings) -> Stores:
    """Almacenes según la configuración: la BD `DiscoveryDataAgent` si `DISCOVERY_DATA_AGENT_DB` está definida; si no, archivos."""
    return open_stores(settings.db, data_root=settings.data_root, curation_dir=settings.curation_dir,
                       inventory_path=settings.inventory_path)


class AgentRuntime:
    def __init__(self, settings: ApiSettings, connector: Connector, vault: SessionVault, audit,
                 stores: Stores | None = None):
        # `audit`: FileAuditSink (desarrollo) o SqlServerAuditSink (BD DiscoveryDataAgent); misma interfaz.
        self.settings = settings
        self.connector = connector
        self.vault = vault
        self.audit = audit
        self._figure_slots = threading.BoundedSemaphore(FIGURE_CONCURRENCY)
        self._figure_counts: dict[tuple[str, str], int] = {}  # (usuario, día) → consultas de cifras hechas
        stores = stores or open_api_stores(settings)
        self.repository = stores.repository  # BD `DiscoveryDataAgent`; None = solo `data_root` (desarrollo)
        self.writer = stores.writer
        self.curation = stores.curation
        self.inventory_store = stores.inventory
        self.service: DiscoverService | None = None
        self.version = 0
        self.job = BuildJob()
        self.load_error: str | None = None
        self._lock = threading.RLock()
        self._deterministic: tuple[int, DiscoverService] | None = None
        self.usage_listeners: list = []  # (rol, tokens_in, tokens_out): tope diario (HU-19) y /health/metrics (HU-22)
        self._visibility: dict[str, tuple[int, float, frozenset[str]]] = {}  # sesión → (versión, leído_en, ids)
        self._traces: OrderedDict[str, ShownTrace] = OrderedDict()
        self.snapshot: CatalogSnapshot | None = None  # con BD: el catálogo vigente, en memoria
        self.db_version: int | None = None  # versión de la BD que refleja `snapshot`
        self._db_checked = 0.0
        self._fresh_golden: dict[str, GoldenDiscovery] = {}  # confirmaciones escritas que aún no entran al índice
        self._background: list[threading.Thread] = []
        # Se lee al arrancar: la API es de un solo proceso (OP-03) y es la única que lo cambia.
        self.inventory = Inventory(servers=self.inventory_store.inventory())
        self._pull()
        if settings.demo and settings.demo_preload_inventory and not self.inventory.servers:
            self.save_inventory(demo_inventory(settings.demo_fixtures), by="demo")
        self.reload()

    # --- inventario -------------------------------------------------------------------------------
    def save_inventory(self, servers: list[ServerConfig], *, by: str) -> None:
        with self._lock:
            self.inventory_store.save_inventory(servers, by=by)
            self.inventory = Inventory(servers=servers)

    # --- catálogo y DiscoverService ---------------------------------------------------------------
    @property
    def has_catalog(self) -> bool:
        if self.repository is not None:
            return self.snapshot is not None and bool(self.snapshot.objects)
        root = self.settings.data_root
        return (root / "config" / "databases.yaml").is_file() and any((root / "catalog").rglob("*.yaml"))

    @property
    def _settings_path(self) -> Path:
        return self.settings.data_root / "config" / "settings.yaml"  # ajustes del flujo; no es estado

    # --- BD `DiscoveryDataAgent` como fuente de verdad (HU-09) ---------------------------------------------
    def _pull(self, force: bool = False) -> bool:
        """Carga en memoria la versión vigente de la BD. Devuelve True si cambió lo cargado."""
        if self.repository is None:
            return False
        version = self.repository.version()
        if version is None or (version == self.db_version and not force):
            return False
        loaded = self.repository.load()
        if loaded is None:
            return False
        self.snapshot, self.db_version = loaded
        return True

    def _sync(self) -> None:
        """Con el candado tomado: si la BD va por otra versión, la carga y reconstruye el índice."""
        if self._pull():
            self.reload()

    def refresh(self, max_age_s: float = 15.0) -> None:
        """Si otro proceso publicó un catálogo nuevo (el refresco nocturno), lo carga sin reiniciar la API."""
        if self.repository is None or time.monotonic() - self._db_checked < max_age_s:
            return
        with self._lock:
            self._db_checked = time.monotonic()
            try:
                self._sync()
            except Exception as exc:  # la BD no responde: se sigue con lo cargado; la auditoría ya es fail-closed
                log.error("catalog.refresh_failed", extra={"error_type": type(exc).__name__})

    @contextlib.contextmanager
    def editing(self):
        """Una edición de curación de principio a fin bajo un solo candado y sobre el catálogo vigente: lo que se
        comprueba (que el activo existe, de qué dominio es) es lo mismo que se escribe. Devuelve el servicio al día.
        Si la BD no responde, lanza antes de tocar nada."""
        with self._lock:
            self._sync()
            yield self.service

    def _written(self, strict: bool = True) -> None:
        """Tras una escritura de curación: el índice refleja lo escrito antes de responder. Si no se puede (la BD no
        responde al releer, o el catálogo no carga), lo escrito ya es firme pero quien editó recibe el error: no se le
        dice que su cambio está en vigor cuando el índice aún no lo refleja."""
        with self._lock:
            try:
                self._pull(force=True)
            except Exception as exc:
                log.error("catalog.refresh_failed", extra={"error_type": type(exc).__name__})
                self._db_checked = 0.0  # se reintenta en la siguiente petición
                raise
            self.reload()
            if strict and self.load_error:
                raise RuntimeError("El cambio se guardó pero el catálogo no se pudo recargar")

    def write_descriptions(self, edits: list[DescriptionEdit], user_id: str, reason: str) -> int:
        """Escribe descripciones (edición del responsable o diccionario) y recarga. Devuelve las copias cambiadas."""
        with self._lock:
            changed = self.writer.write_descriptions(edits, by=user_id, reason=reason)
            if changed:
                self._written()
            return changed

    def curated_rules(self) -> list[BusinessRule]:
        """Reglas que gestionan los responsables desde la vista Curación (HU-28)."""
        return steward_rules(self.service.deps.knowledge.rules) if self.service else []

    def upsert_rule(self, rule: BusinessRule, user_id: str) -> None:
        with self._lock:
            self.writer.upsert_rule(rule, by=user_id)
            self._written()

    def delete_rule(self, rule_id: str, user_id: str) -> bool:
        with self._lock:
            deleted = self.writer.delete_rule(rule_id, by=user_id)
            if deleted:
                self._written()
            return deleted

    def deterministic_service(self) -> DiscoverService | None:
        """El mismo catálogo sin nodos de LLM (modo del tope diario agotado, HU-19)."""
        if self.service is None or not self.settings.models_path:
            return self.service  # sin LLM configurado el servicio ya es determinista
        with self._lock:
            if self._deterministic is None or self._deterministic[0] != self.version:
                self._deterministic = (self.version, self._build_service(None))
            return self._deterministic[1]

    def _on_usage(self, role: str, tokens_in: int, tokens_out: int) -> None:
        for listener in self.usage_listeners:
            listener(role, tokens_in, tokens_out)

    def _build_service(self, gateway) -> DiscoverService:
        if self.repository is not None:
            service = build_service_from_snapshot(self.snapshot, settings_path=self._settings_path, gateway=gateway,
                                                  audit=self.audit)
        else:
            service = build_service(self.settings.data_root, gateway=gateway, audit=self.audit)
        if self.settings.ask_flow:  # DISCOVERY_DATA_AGENT_ASK_FLOW=1 activa las cifras agregadas sin editar settings.yaml
            service.deps.settings.features.ask_flow = True
        if self.settings.ask_llm_sql:  # CONVERDATA_ASK_LLM_SQL=1: fase 1b, SQL de un LLM cuando la plantilla no basta
            service.deps.settings.features.ask_llm_sql = True
        return service

    def reload(self) -> None:
        """Carga (o recarga) el DiscoverFlow sobre el catálogo vigente; sin catálogo, la API queda en modo configuración."""
        with self._lock:
            if not self.has_catalog:
                self.service, self.load_error = None, None
                return
            try:
                gateway = None
                if self.settings.models_path:
                    from discovery_data_agent.llm.gateway import LLMGateway

                    gateway = LLMGateway.from_file(self.settings.models_path)
                    gateway.usage_hook = self._on_usage
                service = self._build_service(gateway)
            except Exception as exc:
                # Solo el tipo: el texto de la excepción puede llevar rutas o contenido del catálogo (D5).
                log.error("catalog.load_failed", extra={"error_type": type(exc).__name__})
                # Sin poder cargar lo vigente no se sigue respondiendo con lo anterior: podría incluir una regla o
                # una confirmación que un responsable acaba de retirar. La API queda sin catálogo hasta que cargue.
                self.service, self.load_error = None, type(exc).__name__
                self._visibility.clear()
                return
            self.service, self.load_error = service, None
            self.version += 1
            self._visibility.clear()
            self._fresh_golden.clear()

    def catalog_stats(self) -> dict:
        if self.service is None:
            return {"objects": 0, "columns": 0, "databases": 0}
        objects = self.service.deps.catalog.objects
        return {"objects": len(objects), "columns": sum(len(o.columns) for o in objects),
                "databases": len({(o.server, o.database) for o in objects})}

    # --- identidad --------------------------------------------------------------------------------
    def visible_ids(self, session: Session) -> frozenset[str]:
        """`visible_ids` con el login del propio usuario en cada servidor (F14), cacheado por versión del catálogo."""
        if self.service is None:
            return frozenset()
        cached = self._visibility.get(session.id)
        now = time.monotonic()
        # F14: caduca a los 15 min, así una revocación en SQL Server deja de verse sin esperar a que cierre sesión.
        if cached and cached[0] == self.version and now - cached[1] < self.settings.visibility_ttl_s:
            return cached[2]
        catalog = self.service.deps.catalog
        ids: set[str] = set()
        for server_id in session.servers:
            server = self.inventory.server(server_id)
            cred = self.vault.credential(session, server_id)
            databases = sorted({o.database for o in catalog.objects if o.server == server_id})
            if server is None or cred is None or not databases:
                continue
            lister = self.connector.object_lister({server_id: server}, cred)
            try:
                for obj in lister.visible_objects(server_id, databases):
                    ids.add(physical_id(server.environment, server.id, obj.database, obj.schema, obj.name))
            except Exception as exc:  # servidor caído: el usuario no ve nada de ese servidor (fail-closed)
                log.warning("visibilidad no disponible en %s: %s", server_id, type(exc).__name__)
        result = frozenset(ids)
        self._visibility[session.id] = (self.version, now, result)
        if len(self._visibility) > 4 * MAX_TRACES:  # sesiones que ya caducaron
            alive = {s.id for s in self.vault.sessions()}
            for key in [k for k in self._visibility if k not in alive]:
                del self._visibility[key]
        return result

    # --- modelos de IA elegibles en pantalla (F16) ------------------------------------------------
    _DEFAULT_KEY_ENV = {"nvidia_nim": "NVIDIA_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}

    def _profile_problem(self, base, name: str) -> str | None:
        """Por qué no se puede usar un perfil, en palabras para el administrador; None si se puede."""
        import os

        from discovery_data_agent.llm.factory import apply_profile
        from discovery_data_agent.llm.gateway import GatewayConfigError, LLMGateway, ResidencyError

        config = apply_profile(base, name)
        try:
            LLMGateway(config).validate()
        except (GatewayConfigError, ResidencyError) as exc:  # el motivo lo redacta el gateway: no lleva claves
            return str(exc)
        except Exception as exc:  # una configuración que no se puede validar no se ofrece
            return f"La configuración del perfil no es válida ({type(exc).__name__})"
        for role in config.roles.values():
            provider = config.provider(role.provider)
            env = provider.api_key_env or self._DEFAULT_KEY_ENV.get(role.provider)
            if env and provider.base_url is None and not os.environ.get(env):
                return f"Falta la clave del proveedor en el servidor (variable de entorno {env})"
        return None

    def llm_profiles(self) -> dict:
        """Qué perfiles de modelos hay, cuál está activo y cuáles se pueden usar. Nunca devuelve claves."""
        path = self.settings.models_path
        if path is None:
            return {"configured": False, "selectable": False, "active": None, "data_mode": None, "profiles": []}
        from discovery_data_agent.llm.factory import NO_MODEL, load_models

        base = load_models(path, apply_selection=False)
        current = load_models(path)
        profiles = []
        for name, profile in base.profiles.items():
            problem = self._profile_problem(base, name)
            profiles.append({
                "id": name, "label": profile.label, "description": profile.description,
                "roles": {role: {"provider": cfg.provider, "model": cfg.model} for role, cfg in profile.roles.items()},
                "usable": problem is None, "reason": problem,
            })
        return {
            "configured": True, "selectable": bool(base.profiles), "none_id": NO_MODEL, "data_mode": base.data_mode,
            "active": current.active_profile if base.profiles else None,
            "roles": {role: {"provider": cfg.provider, "model": cfg.model} for role, cfg in current.roles.items()},
            "profiles": profiles,
        }

    def set_llm_profile(self, name: str) -> None:
        """Cambia el perfil activo y recarga el flujo. `ValueError` con el motivo si no se puede usar."""
        path = self.settings.models_path
        if path is None:
            raise ValueError("No hay un archivo de modelos configurado (DISCOVERY_DATA_AGENT_MODELS)")
        from discovery_data_agent.llm.factory import NO_MODEL, load_models, write_selection

        base = load_models(path, apply_selection=False)
        if not base.profiles:
            raise ValueError("El archivo de modelos no define perfiles elegibles")
        if name != NO_MODEL:
            if name not in base.profiles:
                raise ValueError("Ese perfil no existe")
            problem = self._profile_problem(base, name)
            if problem:
                raise ValueError(problem)
        write_selection(path, name)
        self.reload()

    def figure_executor(self, session: Session):
        """Cómo ejecutar un agregado con la credencial de la sesión (`discovery.figures.FigureExecutor`), o None si
        las cifras no están activas o el conector no abre conexiones de datos (modo demo). La conexión es de solo
        lectura y con tiempo límite; SQL Server decide con el login del usuario si puede leer la tabla."""
        if not self.settings.ask_flow or not hasattr(self.connector, "connect"):
            return None

        def run(server_id: str, database: str, sql: str):
            from discovery_data_agent.discovery.figures import check_sql

            check_sql(sql)  # solo las consultas de la plantilla: el ejecutor no acepta SQL libre de ningún llamador
            server = self.inventory.server(server_id)
            cred = self.vault.credential(session, server_id)
            if server is None or cred is None:
                raise PermissionError("La sesión no tiene credencial para ese servidor")
            allowed = server.figures if server.figures is not None else server.environment != "produccion"
            if not allowed:  # el banco decide en el inventario qué servidores aceptan consultas de totales
                raise PermissionError("Ese servidor no está autorizado para calcular cifras")
            if not self._count_figure(session.user_id):
                raise PermissionError("Se alcanzó el tope diario de cifras de este usuario")
            if not self._figure_slots.acquire(blocking=False):
                raise TimeoutError("Hay demasiadas cifras calculándose a la vez")
            try:
                # Antes de tocar datos queda registrado quién consulta qué y dónde (sin valores). Si la auditoría no
                # se puede escribir, la consulta no se ejecuta (F11, fail-closed también para el acceso).
                self.audit.event("figure_query", session.user_id, server=server_id, database=database, sql=sql)
                # Si el inventario declara una réplica de lectura, el conector abre la conexión ahí.
                return self._run_figure(server, cred, database, sql)
            finally:
                self._figure_slots.release()

        return run

    def ask_executor(self, session: Session):
        """Fase 1b (`ask_llm_sql`): ejecutor de SQL generado por un LLM y ya validado (F7), o None si no está activo
        o el conector no abre conexiones de datos (modo demo). Pasa por los mismos controles que las cifras."""
        service = self.service
        enabled = self.settings.ask_llm_sql or (service is not None and service.deps.settings.features.ask_llm_sql)
        if not enabled or not hasattr(self.connector, "connect"):
            return None
        from converdata_api.executor import SessionQueryExecutor

        return SessionQueryExecutor(
            self.inventory,
            lambda server_id, database, sql, max_rows, probe: self._run_ask(session, server_id, database, sql,
                                                                             max_rows, probe))

    def _run_ask(self, session: Session, server_id: str, database: str, sql: str, max_rows: int, probe: bool):
        """Como `figure_executor`, pero para SQL ya validado por `converdata.ask.validator`. Los sondeos (valores de
        categorías y rangos de fechas para el planner) se auditan pero no cuentan para el tope diario."""
        server = self.inventory.server(server_id)
        cred = self.vault.credential(session, server_id)
        if server is None or cred is None:
            raise PermissionError("Tu sesión no tiene acceso a ese servidor.")
        allowed = server.figures if server.figures is not None else server.environment != "produccion"
        if not allowed:
            raise PermissionError("Ese servidor no está autorizado para calcular datos.")
        if not probe and not self._count_figure(session.user_id):
            raise PermissionError("Alcanzaste el tope diario de consultas de datos.")
        if not self._figure_slots.acquire(timeout=ASK_SLOT_WAIT_S):
            raise TimeoutError("Hay demasiadas consultas calculándose a la vez")
        try:
            # Antes de tocar datos queda registrado quién consulta qué y dónde (sin valores); sin auditoría no se ejecuta.
            self.audit.event("ask_probe" if probe else "ask_query", session.user_id, server=server_id,
                             database=database, sql=sql)
            conn = self.connector.connect(server, cred, database)
            try:
                conn.timeout = ASK_TIMEOUT_S
                conn.autocommit = False  # nada de lo que corra aquí se confirma: al terminar siempre se revierte
                cursor = conn.cursor()
                cursor.execute("SET LOCK_TIMEOUT 5000; SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
                cursor.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                return columns, [list(row) for row in cursor.fetchmany(max_rows)]
            finally:
                try:
                    conn.rollback()
                finally:
                    conn.close()
        finally:
            self._figure_slots.release()

    def _count_figure(self, user_id: str) -> bool:
        """Cuenta una consulta de cifras del usuario hoy; False si ya llegó al tope (`figures_daily_limit`). El límite
        de preguntas por minuto mide preguntas; este mide consultas a los servidores del banco."""
        limit = self.settings.figures_daily_limit
        if limit <= 0:
            return True
        today = _now()[:10]
        key = (user_id.lower(), today)
        with self._lock:
            for old in [k for k in self._figure_counts if k[1] != today]:
                del self._figure_counts[old]
            if self._figure_counts.get(key, 0) >= limit:
                return False
            self._figure_counts[key] = self._figure_counts.get(key, 0) + 1
            return True

    def _run_figure(self, server, cred, database: str, sql: str):
            conn = self.connector.connect(server, cred, database)
            try:
                conn.timeout = FIGURE_TIMEOUT_S
                conn.autocommit = False  # nada de lo que corra aquí se confirma: al terminar siempre se revierte
                cursor = conn.cursor()
                # No esperar por bloqueos de la operación del banco ni dejarlos: lectura sin bloqueos y con tope.
                cursor.execute("SET LOCK_TIMEOUT 5000; SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
                cursor.execute(sql)
                return [tuple(row) for row in cursor.fetchmany(FIGURE_MAX_ROWS)]
            finally:
                try:
                    conn.rollback()
                finally:
                    conn.close()

    def user_context(self, session: Session) -> UserContext:
        return UserContext(user_id=session.user_id, groups=session.groups, visible_ids=self.visible_ids(session),
                           roles=session.roles)

    def forget(self, session: Session) -> None:
        self._visibility.pop(session.id, None)

    # --- respuestas mostradas y retroalimentación (F24) -------------------------------------------
    def remember(self, trace_id: str, trace: ShownTrace) -> None:
        with self._lock:
            self._traces[trace_id] = trace
            while len(self._traces) > MAX_TRACES:
                self._traces.popitem(last=False)

    def shown(self, trace_id: str) -> ShownTrace | None:
        return self._traces.get(trace_id)

    def golden(self, gid: str) -> GoldenDiscovery | None:
        """La confirmación vigente de una pareja pregunta-activo, incluida una recién escrita."""
        if gid in self._fresh_golden:
            return self._fresh_golden[gid]
        known = self.service.deps.knowledge.golden if self.service else []
        return next((g for g in known if g.id == gid), None)

    def record_feedback(self, session: Session, trace_id: str, trace: ShownTrace, asset_key: str, verdict: str,
                        steward: bool = False) -> dict:
        """Guarda el voto y actualiza la confirmación de la pareja plantilla-activo (regla en `resolve_golden`).

        La plantilla es la pregunta sin literales. Si aun así parece llevar datos personales, el voto cuenta pero no se
        convierte en conocimiento reutilizable (F17)."""
        known = self._vocabulary()
        safe = strip_literals(trace.question, known)
        template = question_template(trace.question, known)
        gid = golden_id(template, asset_key)
        elapsed_ms = int((time.time() - trace.asked_at) * 1000)
        learnable = bool(template) and not find_pii(safe)
        # Se audita antes de aplicar: sin registro no hay cambio (F11).
        self.audit.event("feedback", session.user_id, trace_id=trace_id, asset_key=asset_key, verdict=verdict,
                         steward=steward, time_to_verdict_ms=elapsed_ms)
        try:
            with self._lock:  # el voto y la confirmación que resulta, juntos: dos votos a la vez no se pisan
                votes = self.curation.add_vote({
                    "golden_id": gid, "user_id": session.user_id, "trace_id": trace_id, "asset_key": asset_key,
                    "verdict": verdict, "steward": steward})
                if learnable:
                    golden = resolve_golden(template, asset_key, votes, steward=steward, verdict=verdict,
                                            current=self.golden(gid))
                    self._store_golden(golden, session.user_id, trace.question)
        except Exception as exc:
            with contextlib.suppress(Exception):  # lo anunciado en la auditoría no se aplicó
                self.audit.event("feedback_failed", session.user_id, trace_id=trace_id, asset_key=asset_key,
                                 error_type=type(exc).__name__)
            raise
        if learnable and steward:
            self._written()  # su "✔" o su "✖" ya rige en la siguiente búsqueda (F24 CA2)
        elif learnable:
            self._reindex_later()
        counted = tally(votes)
        return {"golden_id": gid, "confirmations": counted.confirms, "rejections": counted.rejects, "learned": learnable}

    def steward_golden(self, question: str, asset_key: str, user_id: str) -> GoldenDiscovery | None:
        """Respuesta de un responsable a una duda escalada: entra de inmediato al índice (F24 CA1). None si la pregunta
        parece llevar datos personales: la respuesta queda en la solicitud, pero no como conocimiento reutilizable."""
        known = self._vocabulary()
        template = question_template(question, known)
        if not template or find_pii(strip_literals(question, known)):
            return None
        golden = GoldenDiscovery(id=golden_id(template, asset_key), template=template, asset_keys=[asset_key],
                                 confirmed_by="steward")
        with self._lock:
            self._store_golden(golden, user_id, question)
            self._written()
        return golden

    def _vocabulary(self) -> frozenset[str]:
        """Palabras con dígitos que no son literales: nombres del catálogo y códigos del glosario y de las reglas."""
        if self.service is None:
            return frozenset()
        deps = self.service.deps
        return deps.catalog.names_with_digits() | deps.knowledge.codes()

    def _store_golden(self, golden: GoldenDiscovery, user_id: str, question: str) -> None:
        """Con el candado tomado: una sola fila. El texto original solo se guarda si no traía ningún literal (nada que
        la plantilla descartara) ni parece llevar datos personales; la pregunta completa ya está en la auditoría."""
        keep = not has_literals(question, self._vocabulary()) and not find_pii(question)
        self.writer.upsert_golden(golden, by=user_id, question=question if keep else None)
        self._fresh_golden[golden.id] = golden

    def _reindex_later(self) -> None:
        """Reindexa con la confirmación nueva sin hacer esperar a quien votó."""
        worker = threading.Thread(target=self._reindex_quietly, daemon=True)
        self._background = [t for t in self._background if t.is_alive()] + [worker]
        worker.start()

    def drain(self, timeout_s: float = 30.0) -> None:
        """Espera a que terminen las recargas en segundo plano (apagado ordenado y pruebas)."""
        for worker in list(self._background):
            worker.join(timeout_s)

    def _reindex_quietly(self) -> None:
        try:
            self._written()
        except Exception as exc:  # la confirmación ya está guardada; entra al índice en la siguiente recarga
            log.error("catalog.reload_failed", extra={"error_type": type(exc).__name__})

    # --- CatalogBuildFlow -------------------------------------------------------------------------
    def start_build(self, session: Session, enrich: bool | None) -> BuildJob:
        """`enrich=None`: con un modelo configurado, las tablas y columnas nuevas reciben descripción y sinónimos
        sugeridos por IA (marcados sin revisar); `False` lo desactiva para ese build."""
        with self._lock:
            if self.job.status == "running":
                return self.job
            self.job = BuildJob(status="running", started_at=_now(), triggered_by=session.user_id,
                                enrich=enrich is not False and self.settings.models_path is not None)
        threading.Thread(target=self._run_build, args=(session, self.job), daemon=True).start()
        return self.job

    def _run_build(self, session: Session, job: BuildJob) -> None:
        work = self.settings.data_root
        scratch: Path | None = None
        try:
            self.audit.event("catalog_build_started", session.user_id, enrich=job.enrich)
            # Copia: el flujo reemplaza `databases: ["*"]` por lo descubierto y el inventario guardado conserva "*".
            inventory = Inventory(servers=[s.model_copy(deep=True) for s in self.inventory.servers])
            if self.repository is not None:
                # Con BD el build corre en un directorio temporal, que se borra al terminar: solo se publica el
                # resultado completo y el servidor no conserva una copia del catálogo.
                scratch = work = Path(tempfile.mkdtemp(prefix="discovery-data-agent-build-"))

            def source_factory(server: ServerConfig):
                cred = self.vault.credential(session, server.id)
                if cred is None:
                    raise PermissionError("Tu sesión no tiene credencial para este servidor; vuelve a iniciar sesión")
                return self.connector.metadata_source(server, cred)

            enricher = None
            if job.enrich:
                from discovery_data_agent.llm.gateway import LLMGateway
                from discovery_data_agent.llm.nodes import build_enricher

                gateway = LLMGateway.from_file(self.settings.models_path)
                gateway.usage_hook = self._on_usage  # el enriquecimiento también cuenta en el consumo de tokens
                enricher = build_enricher(gateway)
            demo = self.settings.demo
            result = refresh_catalog(
                inventory, work, source_factory=source_factory, enricher=enricher, repository=self.repository,
                published_by=session.user_id, scope="all" if demo else "build",
                # La BD de trabajo no se cataloga a sí misma, se llame como se llame.
                own_databases={describe(self.settings.db).split("/")[-1]} if self.settings.db else frozenset(),
                after_build=(lambda root: apply_fixture_knowledge(self.settings.demo_fixtures, root)) if demo else None)
            report = result.report
            job.report, job.summary = asdict(report), report.render()
            # Antes de marcar "ok": quien espera el estado ya encuentra el catálogo cargado (y publicado en la BD).
            if report.servers_ok:
                self._written(strict=False)
            if not report.servers_ok:
                job.error = "Ningún servidor respondió: " + "; ".join(report.servers_failed.values())
            elif self.load_error:
                job.error = f"El catálogo se escribió pero no se pudo cargar: {self.load_error}"
            if not job.error and demo and self.settings.demo_history:
                seeded = seed_history(self.service, self.audit, self.curation, self.settings.demo_fixtures,
                                      marker=self.settings.curation_dir / HISTORY_MARKER)
                if seeded:  # antes de marcar "ok": el tablero ya tiene el historial cuando la web lo pide
                    self.audit.event("demo_history_seeded", session.user_id, client="demo-seed", simulated=True,
                                     **seeded)
        except Exception as exc:
            log.error("catalog.build_failed", extra={"error_type": type(exc).__name__})
            job.error = f"{type(exc).__name__}: {str(exc)[:300]}"  # solo lo ve el admin
        finally:
            if scratch is not None:
                shutil.rmtree(scratch, ignore_errors=True)
        # El estado final va al último: quien lo consulta ya no encuentra el directorio temporal.
        job.finished_at = _now()
        job.status = "error" if job.error else "ok"
        with contextlib.suppress(Exception):  # sin auditoría el trabajo igualmente termina (no queda "running")
            # Sin el texto del error: un mensaje de conexión puede traer host, instancia o login (solo lo ve el admin).
            self.audit.event("catalog_build_finished", session.user_id, status=job.status,
                             objects=(job.report or {}).get("objects"),
                             servers_failed=sorted((job.report or {}).get("servers_failed") or {}))
