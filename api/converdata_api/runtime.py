"""Estado del proceso: inventario, DiscoverService del catálogo actual, visibilidad por sesión y la construcción del catálogo.

El primer arranque no tiene catálogo: un admin inicia sesión con su usuario de BD, lanza el CatalogBuildFlow con esa
credencial y, al terminar, el DiscoverService se carga con lo descubierto (F1, F18). Cada reconstrucción sube `version`
y las visibilidades se recalculan con la credencial de cada sesión (F14).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from converdata.bootstrap import build_service
from converdata.catalog.ids import physical_id
from converdata.config import Inventory, ServerConfig
from converdata.flows.catalog_build import build_catalog
from converdata.flows.discover import DiscoverService
from converdata.models.identity import UserContext
from converdata.models.knowledge import GoldenDiscovery

from converdata_api.audit import FileAuditSink
from converdata_api.connector import Connector
from converdata_api.demo import apply_fixture_knowledge, demo_inventory
from converdata_api.demo_history import seed_history
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


class AgentRuntime:
    def __init__(self, settings: ApiSettings, connector: Connector, vault: SessionVault, audit: FileAuditSink):
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
        self._visibility: dict[str, tuple[int, frozenset[str]]] = {}
        self._traces: OrderedDict[str, ShownTrace] = OrderedDict()
        self.curation = None  # CurationStore; lo asigna create_app (historial simulado del modo demo)
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

    def reload(self) -> None:
        """Carga (o recarga) el DiscoverFlow sobre el catálogo escrito; sin catálogo, la API queda en modo configuración."""
        with self._lock:
            if not self.has_catalog:
                self.service, self.load_error = None, None
                return
            try:
                service = build_service(
                    self.settings.data_root, models_path=self.settings.models_path,
                    llm_nodes=not self.settings.embeddings_only, audit=self.audit,
                )
            except Exception as exc:
                log.exception("no se pudo cargar el catálogo")
                self.load_error = f"{type(exc).__name__}: {str(exc)[:200]}"
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
        if cached and cached[0] == self.version:
            return cached[1]
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
        self._visibility[session.id] = (self.version, result)
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
        cdir = self.settings.curation_dir
        cdir.mkdir(parents=True, exist_ok=True)
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
            self._upsert_golden(golden, keep=True)
        self.audit.event("feedback", session.user_id, trace_id=trace_id, asset_key=asset_key, verdict=verdict,
                         steward=steward, time_to_verdict_ms=row["time_to_verdict_ms"])
        threading.Thread(target=self.reload, daemon=True).start()  # reindexa con la nueva confirmación
        return {"golden_id": golden_id, "confirmations": confirms, "rejections": rejects}

    def golden(self) -> list[GoldenDiscovery]:
        path = self.settings.data_root / "knowledge" / "golden" / GOLDEN_FILE
        if not path.is_file():
            return []
        return [GoldenDiscovery.model_validate(d) for d in (yaml.safe_load(path.read_text(encoding="utf-8")) or [])]

    def steward_golden(self, question: str, asset_key: str) -> GoldenDiscovery:
        """Respuesta de un responsable a una duda escalada: entra de inmediato al índice (F24 CA1)."""
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
        self.audit.event("catalog_build_started", session.user_id, enrich=job.enrich)
        try:
            # Copia: el flujo reemplaza `databases: ["*"]` por lo descubierto y el inventario guardado conserva "*".
            inventory = Inventory(servers=[s.model_copy(deep=True) for s in self.inventory.servers])

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
            report = build_catalog(inventory, self.settings.data_root, source_factory=source_factory, enricher=enricher)
            if self.settings.demo and report.servers_ok:
                apply_fixture_knowledge(self.settings.demo_fixtures, self.settings.data_root)
            job.report, job.summary = asdict(report), report.render()
            self.reload()  # antes de marcar "ok": quien espera el estado ya encuentra el catálogo cargado
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
            log.exception("falló la construcción del catálogo")
            job.status, job.error = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
        job.finished_at = _now()
        self.audit.event("catalog_build_finished", session.user_id, status=job.status, error=job.error,
                         objects=(job.report or {}).get("objects"))
