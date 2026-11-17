"""Estado del proceso: inventario, DiscoverService del catálogo actual, visibilidad por sesión y la construcción del catálogo.

El primer arranque no tiene catálogo: un admin inicia sesión con su usuario de BD, lanza el CatalogBuildFlow con esa
credencial y, al terminar, el DiscoverService se carga con lo descubierto (F1, F18). Cada reconstrucción sube `version`
y las visibilidades se recalculan con la credencial de cada sesión (F14).

Con `CONVERDATA_DB` definida, la fuente de verdad del catálogo y del conocimiento es la BD `ConverData` (OP-02, HU-09):
`data_root` pasa a ser una copia de trabajo que se trae de la BD al arrancar y cuando otro proceso (el Builder
programado) publica una versión nueva, y cada edición de curación se publica en la BD (`commit`) antes de recargar.
Sin la variable (desarrollo), `data_root` es el catálogo.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import shutil
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from converdata.bootstrap import build_service
from converdata.builder.catalog_builder import write_snapshot
from converdata.catalog.ids import physical_id
from converdata.catalog.store import CatalogRepository, StaleCatalog, load_snapshot
from converdata.config import Inventory, ServerConfig
from converdata.flows.catalog_build import OWN_DATABASES, build_catalog
from converdata.flows.discover import DiscoverService
from converdata.models.identity import UserContext
from converdata.models.knowledge import GoldenDiscovery
from converdata.storage.connection import describe

from converdata_api.connector import Connector
from converdata_api.demo import apply_fixture_knowledge, demo_inventory
from converdata_api.demo_history import seed_history
from converdata_api.pii import find_pii
from converdata_api.settings import ApiSettings
from converdata_api.vault import Session, SessionVault

log = logging.getLogger(__name__)
GOLDEN_FILE = "confirmaciones_usuarios.yaml"
MAX_TRACES = 500


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


def normalize_question(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


def open_repository(settings: ApiSettings) -> CatalogRepository | None:
    """Repositorio del catálogo en la BD `ConverData` si `CONVERDATA_DB` está definida; None = solo archivos."""
    if not settings.db:
        return None
    from converdata.storage.catalog_repository import SqlServerCatalogRepository
    from converdata.storage.connection import connector

    return SqlServerCatalogRepository(connector(settings.db))


class AgentRuntime:
    def __init__(self, settings: ApiSettings, connector: Connector, vault: SessionVault, audit):
        # `audit`: FileAuditSink (desarrollo) o SqlServerAuditSink (BD ConverData); misma interfaz.
        self.settings = settings
        self.connector = connector
        self.vault = vault
        self.audit = audit
        self.inventory = self._load_inventory()
        self.service: DiscoverService | None = None
        self.version = 0
        self.job = BuildJob()
        self.load_error: str | None = None
        self._lock = threading.RLock()
        self._deterministic: tuple[int, DiscoverService] | None = None
        self.usage_listeners: list = []  # (rol, tokens_in, tokens_out): tope diario (HU-19) y /health/metrics (HU-22)
        self._visibility: dict[str, tuple[int, float, frozenset[str]]] = {}  # sesión → (versión, leído_en, ids)
        self._traces: OrderedDict[str, ShownTrace] = OrderedDict()
        self.curation = None  # CurationStore; lo asigna create_app (historial simulado del modo demo)
        self.repository: CatalogRepository | None = None  # BD `ConverData`; None = solo `data_root` (desarrollo)
        self.db_version: int | None = None  # versión de la BD que refleja `data_root`
        self._db_checked = 0.0
        self._dirty = False  # la copia de trabajo tiene algo que no se pudo publicar: se descarta antes de seguir
        self._background: list[threading.Thread] = []
        self.repository = open_repository(settings)
        self._pull()
        if settings.demo and settings.demo_preload_inventory and not self.inventory.servers:
            self.save_inventory(demo_inventory(settings.demo_fixtures))
        self.reload()

    # --- inventario -------------------------------------------------------------------------------
    def _load_inventory(self) -> Inventory:
        path = self.settings.inventory_path
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return Inventory.model_validate({"servers": data.get("servers") or []})
        return Inventory(servers=[])

    def save_inventory(self, servers: list[ServerConfig]) -> None:
        with self._lock:
            self.inventory = Inventory(servers=servers)
            path = self.settings.inventory_path
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {"servers": [s.model_dump(exclude_none=True) for s in servers]}
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # --- catálogo y DiscoverService ---------------------------------------------------------------
    @property
    def has_catalog(self) -> bool:
        root = self.settings.data_root
        return (root / "config" / "databases.yaml").is_file() and any((root / "catalog").rglob("*.yaml"))

    # --- BD `ConverData` como fuente de verdad (HU-09) ---------------------------------------------
    def _pull(self, force: bool = False) -> bool:
        """Trae a `data_root` la versión vigente de la BD. Devuelve True si la copia de trabajo cambió."""
        if self.repository is None:
            return False
        version = self.repository.version()
        if version is None or (version == self.db_version and not force):
            return False
        loaded = self.repository.load()
        if loaded is None:
            return False
        write_snapshot(self.settings.data_root, loaded[0])
        self.db_version = loaded[1]
        return True

    def _sync(self) -> None:
        """Con el candado tomado: deja la copia de trabajo igual a la BD si esta cambió o si quedó algo sin publicar."""
        if self.repository is None:
            return
        changed = self._pull(force=self._dirty)  # si la BD no responde, lanza y `_dirty` se conserva
        self._dirty = False
        if changed:
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
        """Una edición de la copia de trabajo, de principio a fin bajo un solo candado.

        Nadie más lee, trae ni publica la copia mientras dura: la edición parte de la versión vigente de la BD y lo que
        se publica es exactamente lo que cambió quien edita (y a su nombre). Devuelve el servicio ya al día. Si la BD
        no responde, lanza antes de tocar nada."""
        with self._lock:
            self._sync()
            yield self.service

    def commit(self, user_id: str, reason: str, scope: str = "all", source: Path | None = None) -> None:
        """Publica la copia de trabajo (o `source`, el directorio de un build) en la BD y recarga el índice. Sin BD
        configurada, solo recarga. Se llama dentro de `editing()`.

        Si la publicación falla, la copia de trabajo se descarta (vuelve a ser la de la BD): `StaleCatalog` cuando otro
        proceso publicó entre tanto, y quien editaba debe repetir el cambio."""
        with self._lock:
            if self.repository is not None:
                try:
                    result = self.repository.publish(
                        load_snapshot(source or self.settings.data_root), published_by=user_id, reason=reason,
                        scope=scope, expected_version=self.db_version if scope == "all" and source is None else None)
                except Exception as exc:
                    self._dirty = True  # lo editado no llegó a la BD: no puede quedar para que lo publique otro
                    if isinstance(exc, StaleCatalog):
                        with contextlib.suppress(Exception):  # la edición ya quedó auditada: se anota que no se aplicó
                            self.audit.event("catalog_conflict", user_id, reason=reason)
                    with contextlib.suppress(Exception):
                        self._sync()
                    raise
                self.db_version = result.version
                if scope == "build" or source is not None:  # la BD conserva lo humano y lo curado que el refresco no trae
                    self._pull(force=True)
            self.reload()

    def deterministic_service(self) -> DiscoverService | None:
        """El mismo catálogo sin nodos de LLM ni embeddings remotos (modo del tope diario agotado, HU-19)."""
        if self.service is None or not self.settings.models_path:
            return self.service  # sin LLM configurado el servicio ya es determinista
        with self._lock:
            if self._deterministic is None or self._deterministic[0] != self.version:
                self._deterministic = (self.version, build_service(self.settings.data_root, audit=self.audit))
            return self._deterministic[1]

    def _on_usage(self, role: str, tokens_in: int, tokens_out: int) -> None:
        for listener in self.usage_listeners:
            listener(role, tokens_in, tokens_out)

    def reload(self) -> None:
        """Carga (o recarga) el DiscoverFlow sobre el catálogo escrito; sin catálogo, la API queda en modo configuración."""
        with self._lock:
            if not self.has_catalog:
                self.service, self.load_error = None, None
                return
            try:
                gateway = None
                if self.settings.models_path:
                    from converdata.llm.gateway import LLMGateway

                    gateway = LLMGateway.from_file(self.settings.models_path)
                    gateway.usage_hook = self._on_usage
                service = build_service(
                    self.settings.data_root, gateway=gateway,
                    llm_nodes=not self.settings.embeddings_only, audit=self.audit,
                )
            except Exception as exc:
                # Solo el tipo: el texto de la excepción puede llevar rutas o contenido del catálogo (D5).
                log.error("catalog.load_failed", extra={"error_type": type(exc).__name__})
                self.load_error = type(exc).__name__
                return
            self.service, self.load_error = service, None
            self.version += 1
            self._visibility.clear()

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

    def record_feedback(self, session: Session, trace_id: str, trace: ShownTrace, asset_key: str, verdict: str,
                        comment: str | None, steward: bool = False) -> dict:
        """Guarda la opinión del usuario y la agrega a las confirmaciones (`golden`).

        De usuarios: desde 2 confirmaciones distintas sin rechazos pesa en la confianza (F22). De un responsable del
        dominio: entra de inmediato, y su "✖" retira el par (F24 CA2)."""
        template = normalize_question(trace.question)
        golden_id = "u-" + hashlib.sha1(f"{template}|{asset_key}".encode("utf-8")).hexdigest()[:12]
        row = {"ts": _now(), "trace_id": trace_id, "user_id": session.user_id, "asset_key": asset_key,
               "verdict": verdict, "golden_id": golden_id, "comment": (comment or "")[:500] or None,
               "steward": steward, "time_to_verdict_ms": int((time.time() - trace.asked_at) * 1000)}
        # Se audita antes de aplicar: sin registro no hay cambio (F11).
        self.audit.event("feedback", session.user_id, trace_id=trace_id, asset_key=asset_key, verdict=verdict,
                         steward=steward, time_to_verdict_ms=row["time_to_verdict_ms"])
        cdir = self.settings.curation_dir
        cdir.mkdir(parents=True, exist_ok=True)
        # La confirmación guarda el texto de la pregunta: si parece llevar datos personales, el voto cuenta pero no se
        # convierte en conocimiento reutilizable (F17).
        learnable = not find_pii(trace.question)
        with self._lock:
            path = cdir / "feedback.jsonl"
            previous = []
            if path.is_file():
                previous = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            votes: dict[str, str] = {}  # último voto de cada usuario para esta pareja pregunta-activo
            for r in [*previous, row]:
                if r.get("golden_id") == golden_id:
                    votes[r["user_id"]] = r["verdict"]
            confirms = sum(v == "confirm" for v in votes.values())
            rejects = sum(v == "reject" for v in votes.values())
            if steward:
                golden = GoldenDiscovery(id=golden_id, template=template, asset_keys=[asset_key], confirmed_by="steward",
                                         confirmations=max(confirms, 1), rejected=verdict == "reject")
            else:
                golden = GoldenDiscovery(id=golden_id, template=template, asset_keys=[asset_key], confirmed_by="users",
                                         confirmations=max(confirms, 1), rejected=rejects > 0)
                current = next((g for g in self.golden() if g.id == golden_id), None)
                if current is not None and current.confirmed_by == "steward":  # el responsable manda sobre los usuarios
                    golden = current.model_copy(update={"confirmations": max(confirms, 1)})
            if learnable:
                self._store_golden(golden, session.user_id)
        if learnable:  # reindexa con la nueva confirmación, sin hacer esperar al usuario
            worker = threading.Thread(target=self._reload_quietly, daemon=True)
            self._background = [t for t in self._background if t.is_alive()] + [worker]
            worker.start()
        return {"golden_id": golden_id, "confirmations": confirms, "rejections": rejects, "learned": learnable}

    def _store_golden(self, golden: GoldenDiscovery, user_id: str) -> None:
        """Con el candado tomado: una sola fila en la BD (no se publica todo el catálogo) y después la copia de trabajo."""
        if self.repository is not None:
            version = self.repository.upsert_golden(golden, published_by=user_id)
            if self.db_version is not None and version == self.db_version + 1:
                self.db_version = version  # nadie más publicó: la copia de trabajo sigue al día
        self._upsert_golden(golden, keep=True)

    def drain(self, timeout_s: float = 30.0) -> None:
        """Espera a que terminen las publicaciones en segundo plano (apagado ordenado y pruebas)."""
        for worker in list(self._background):
            worker.join(timeout_s)

    def _reload_quietly(self) -> None:
        try:
            self.reload()
        except Exception as exc:  # la confirmación ya está guardada; entra al índice en la siguiente recarga
            log.error("catalog.reload_failed", extra={"error_type": type(exc).__name__})

    def golden(self) -> list[GoldenDiscovery]:
        path = self.settings.data_root / "knowledge" / "golden" / GOLDEN_FILE
        if not path.is_file():
            return []
        return [GoldenDiscovery.model_validate(d) for d in (yaml.safe_load(path.read_text(encoding="utf-8")) or [])]

    def steward_golden(self, question: str, asset_key: str) -> GoldenDiscovery | None:
        """Respuesta de un responsable a una duda escalada: entra de inmediato al índice (F24 CA1). None si la pregunta
        parece llevar datos personales: la respuesta queda en la solicitud, pero no como conocimiento reutilizable."""
        if find_pii(question):
            return None
        template = normalize_question(question)
        golden_id = "u-" + hashlib.sha1(f"{template}|{asset_key}".encode("utf-8")).hexdigest()[:12]
        golden = GoldenDiscovery(id=golden_id, template=template, asset_keys=[asset_key], confirmed_by="steward")
        with self._lock:
            self._upsert_golden(golden, keep=True)
        return golden

    def set_golden_state(self, golden_id: str, action: str) -> GoldenDiscovery | None:
        with self._lock:
            current = next((g for g in self.golden() if g.id == golden_id), None)
            if current is None:
                return None
            update = {"confirmed_by": "steward", "rejected": False} if action == "approve" else {"rejected": True}
            golden = current.model_copy(update=update)
            self._upsert_golden(golden, keep=True)
            return golden

    def _upsert_golden(self, golden: GoldenDiscovery, keep: bool) -> None:
        path = self.settings.data_root / "knowledge" / "golden" / GOLDEN_FILE
        items = self.golden()
        items = [g for g in items if g.id != golden.id] + ([golden] if keep else [])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump([g.model_dump() for g in items], allow_unicode=True, sort_keys=False),
                        encoding="utf-8")

    # --- CatalogBuildFlow -------------------------------------------------------------------------
    def start_build(self, session: Session, enrich: bool) -> BuildJob:
        with self._lock:
            if self.job.status == "running":
                return self.job
            self.job = BuildJob(status="running", started_at=_now(), triggered_by=session.user_id,
                                enrich=enrich and self.settings.models_path is not None)
        threading.Thread(target=self._run_build, args=(session, self.job), daemon=True).start()
        return self.job

    def _run_build(self, session: Session, job: BuildJob) -> None:
        work = self.settings.data_root
        scratch: Path | None = None
        try:
            self.audit.event("catalog_build_started", session.user_id, enrich=job.enrich)
            # Copia: el flujo reemplaza `databases: ["*"]` por lo descubierto y el inventario guardado conserva "*".
            inventory = Inventory(servers=[s.model_copy(deep=True) for s in self.inventory.servers])
            scope = "all" if self.settings.demo else "build"
            if self.repository is not None:
                # Con BD, el build corre en un directorio aparte: la copia de trabajo no cambia a medias mientras otros
                # editan o votan, y solo se publica el resultado completo.
                self.settings.data_root.parent.mkdir(parents=True, exist_ok=True)
                scratch = work = Path(tempfile.mkdtemp(prefix=".build-", dir=self.settings.data_root.parent))
                loaded = self.repository.load(scope)  # el refresco parte de la versión vigente de la BD
                if loaded is not None:
                    write_snapshot(work, loaded[0])

            def source_factory(server: ServerConfig):
                cred = self.vault.credential(session, server.id)
                if cred is None:
                    raise PermissionError("Tu sesión no tiene credencial para este servidor; vuelve a iniciar sesión")
                return self.connector.metadata_source(server, cred)

            enricher = None
            if job.enrich:
                from converdata.llm.gateway import LLMGateway
                from converdata.llm.nodes import LlmEnricher

                enricher = LlmEnricher(LLMGateway.from_file(self.settings.models_path).chat("planner"))
            own = OWN_DATABASES
            if self.settings.db:  # la BD de trabajo no se cataloga a sí misma, se llame como se llame
                own = own | {describe(self.settings.db).split("/")[-1].lower()}
            report = build_catalog(inventory, work, source_factory=source_factory, enricher=enricher,
                                   exclude_databases=own)
            if self.settings.demo and report.servers_ok:
                apply_fixture_knowledge(self.settings.demo_fixtures, work)
            job.report, job.summary = asdict(report), report.render()
            # Antes de marcar "ok": quien espera el estado ya encuentra el catálogo cargado (y publicado en la BD).
            if report.servers_ok:
                self.commit(session.user_id, "build", scope=scope, source=scratch)
            else:
                self.reload()
            if not report.servers_ok:
                job.error = "Ningún servidor respondió: " + "; ".join(report.servers_failed.values())
            elif self.load_error:
                job.error = f"El catálogo se escribió pero no se pudo cargar: {self.load_error}"
            if not job.error and self.settings.demo and self.settings.demo_history and self.curation is not None:
                seeded = seed_history(self.service, self.audit, self.curation, self.settings.demo_fixtures)
                if seeded:  # antes de marcar "ok": el tablero ya tiene el historial cuando la web lo pide
                    self.audit.event("demo_history_seeded", session.user_id, client="demo-seed", simulated=True,
                                     **seeded)
            job.status = "error" if job.error else "ok"
        except Exception as exc:
            log.error("catalog.build_failed", extra={"error_type": type(exc).__name__})
            job.status, job.error = "error", f"{type(exc).__name__}: {str(exc)[:300]}"  # solo lo ve el admin
        finally:
            if scratch is not None:
                shutil.rmtree(scratch, ignore_errors=True)
        job.finished_at = _now()
        with contextlib.suppress(Exception):  # sin auditoría el trabajo igualmente termina (no queda "running")
            self.audit.event("catalog_build_finished", session.user_id, status=job.status, error=job.error,
                             objects=(job.report or {}).get("objects"))
