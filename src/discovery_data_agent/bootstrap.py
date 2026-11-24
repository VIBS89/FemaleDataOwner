"""Raíz de composición: ensambla el DiscoverFlow y abre los almacenes según la configuración.

- `build_service*`: el DiscoverFlow sobre un directorio (`config/`, `catalog/`, `knowledge/`), una foto ya cargada o la
  BD `DiscoveryDataAgent`. El índice de búsqueda es léxico y vive en memoria (`InMemoryVectorStore`, PRD §13 decisión 9).
- `open_stores`: los adaptadores del catálogo y de la curación. Con la cadena de la BD `DiscoveryDataAgent`, SQL Server (OP-02);
  sin ella, archivos (desarrollo, pruebas y modo demo).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from discovery_data_agent.catalog.store import CatalogRepository, CatalogSnapshot, InventoryStore, load_snapshot
from discovery_data_agent.config import load_settings
from discovery_data_agent.curation import CurationRepository, KnowledgeWriter
from discovery_data_agent.flows.discover import DiscoverDeps, DiscoverService
from discovery_data_agent.memory.memory_store import InMemoryVectorStore
from discovery_data_agent.models.identity import UserContext


@dataclass
class Stores:
    repository: CatalogRepository | None  # None: el catálogo es el directorio `data_root`
    writer: KnowledgeWriter
    curation: CurationRepository
    inventory: InventoryStore


def open_stores(db: str | None, *, data_root: str | Path, curation_dir: str | Path,
                inventory_path: str | Path) -> Stores:
    if db:
        from discovery_data_agent.storage.catalog_repository import SqlServerCatalogRepository
        from discovery_data_agent.storage.connection import connector
        from discovery_data_agent.storage.curation_repository import SqlServerCurationRepository
        from discovery_data_agent.storage.migrations import require_current

        connect = connector(db)
        require_current(connect)
        repository = SqlServerCatalogRepository(connect)
        return Stores(repository=repository, writer=repository, curation=SqlServerCurationRepository(connect),
                      inventory=repository)
    from discovery_data_agent.storage.files import FileCurationRepository, FileInventoryStore, FileKnowledgeWriter

    return Stores(repository=None, writer=FileKnowledgeWriter(Path(data_root)),
                  curation=FileCurationRepository(Path(curation_dir)), inventory=FileInventoryStore(Path(inventory_path)))


def build_service(
    root: str | Path, *, models_path: str | Path | None = None, gateway=None, **overrides
) -> DiscoverService:
    """Sin `models_path` ni `gateway`, modo determinista. Con ellos, los nodos `intent`, `rerank` y `respond` pasan
    por el gateway de LLM (el proveedor de cada rol en `config/models.yaml`). La búsqueda es siempre léxica."""
    root = Path(root)
    return build_service_from_snapshot(
        load_snapshot(root), settings_path=root / "config" / "settings.yaml", models_path=models_path,
        gateway=gateway, **overrides)


def build_service_with_knowledge(root: str | Path, knowledge_dir: str | Path, **kwargs) -> DiscoverService:
    """El catálogo de `root` más las fuentes de conocimiento de `knowledge_dir` (misma estructura que `knowledge/`).
    Sirve para medir qué aporta el conocimiento sobre un catálogo sin tocarlo (`eval discovery --knowledge`)."""
    from discovery_data_agent.catalog.store import load_knowledge

    root = Path(root)
    snapshot, extra = load_snapshot(root), load_knowledge(knowledge_dir)
    kb = snapshot.knowledge
    for name in ("items", "rules", "golden", "lineage", "entities"):
        getattr(kb, name).extend(getattr(extra, name))
    return build_service_from_snapshot(snapshot, settings_path=root / "config" / "settings.yaml", **kwargs)


def build_service_from_db(connect, **kwargs) -> DiscoverService:
    """Lo mismo, con el catálogo publicado en la BD `DiscoveryDataAgent` (OP-02, HU-09). `connect` abre una conexión."""
    from discovery_data_agent.storage.catalog_repository import SqlServerCatalogRepository

    loaded = SqlServerCatalogRepository(connect).load()
    if loaded is None:
        raise LookupError("La BD DiscoveryDataAgent no tiene ningún catálogo publicado (discovery-data-agent catalog publish)")
    return build_service_from_snapshot(loaded[0], **kwargs)


def build_service_from_snapshot(
    snapshot: CatalogSnapshot, *, settings_path: str | Path | None = None, models_path: str | Path | None = None,
    gateway=None, **overrides
) -> DiscoverService:
    catalog, knowledge, owners = snapshot.catalog(), snapshot.knowledge, snapshot.owners
    settings = load_settings(settings_path)

    llm_ports: dict = {}
    model_names = {}
    if models_path and gateway is None:
        from discovery_data_agent.llm.gateway import LLMGateway

        gateway = LLMGateway.from_file(models_path)
    if gateway is not None:
        from discovery_data_agent.llm.nodes import LlmIntentClassifier, LlmNarrator, LlmReranker

        if gateway.has_role("planner"):
            llm_ports["intent_classifier"] = LlmIntentClassifier(gateway.chat("planner"))
            llm_ports["reranker"] = LlmReranker(gateway.chat("planner"))
        if gateway.has_role("fast"):
            from discovery_data_agent.llm.nodes import LlmGuide, LlmQueryExpander

            # El modelo ayuda donde el camino determinista se queda corto: redacta la respuesta para una persona de
            # negocio, reformula la búsqueda cuando cubre poco la pregunta y orienta cuando no se encontró nada.
            llm_ports["narrator"] = LlmNarrator(gateway.chat("fast"))
            llm_ports["expander"] = LlmQueryExpander(gateway.chat("fast"))
            llm_ports["guide"] = LlmGuide(gateway.chat("fast"))
        if gateway.has_role("coder"):
            from converdata.ask.engine import AskEngine
            from converdata.ask.planner import LlmInterpreter, LlmSqlPlanner

            # Fase 1b (`features.ask_llm_sql`, apagado por defecto): el rol `coder` escribe el T-SQL cuando las
            # plantillas de cifras (`features.ask_flow`, decisión 17) no pueden responder. El intérprete (rol
            # `interpret`, o `coder`) entiende la pregunta sin listas de palabras clave. Se construye siempre que
            # haya rol: la API decide por pregunta si lo usa, según la bandera.
            interpret_role = "interpret" if gateway.has_role("interpret") else "coder"
            llm_ports["ask"] = AskEngine(LlmSqlPlanner(gateway.chat("coder")), catalog,
                                         max_rows=settings.features.ask_max_rows,
                                         interpreter=LlmInterpreter(gateway.chat(interpret_role)))
        model_names = gateway.labels  # vista viva: proveedor:modelo que atendió cada rol (audit_step.model)

    store = InMemoryVectorStore()
    store.index_catalog(catalog)
    store.index_knowledge(knowledge.all_items(), knowledge.golden)
    deps = DiscoverDeps(
        catalog=catalog, knowledge=knowledge, store=store, owners=owners, settings=settings,
        model_names=model_names, **{**llm_ports, **overrides},
    )
    return DiscoverService(deps)


def user_with_databases(service: DiscoverService, user_id: str, databases: list[str] | None, groups=None) -> UserContext:
    """Identidad de desarrollo: visibilidad sobre las BDs indicadas (todas si `None`).

    En producción `visible_ids` lo calcula DiscoveryDataAgent-API con el login SQL de cada usuario (F14)."""
    ids = frozenset(
        o.id for o in service.deps.catalog.objects if databases is None or o.database in databases
    )
    return UserContext(user_id=user_id, groups=list(groups or []), visible_ids=ids)
