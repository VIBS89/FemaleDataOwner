"""Raíz de composición: ensambla el DiscoverFlow y abre los almacenes según la configuración.

- `build_service*`: el DiscoverFlow sobre un directorio (`config/`, `catalog/`, `knowledge/`), una foto ya cargada o la
  BD `ConverData`. El índice de búsqueda es léxico y vive en memoria (`InMemoryVectorStore`, PRD §13 decisión 9).
- `open_stores`: los adaptadores del catálogo y de la curación. Con la cadena de la BD `ConverData`, SQL Server (OP-02);
  sin ella, archivos (desarrollo, pruebas y modo demo).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from converdata.catalog.store import CatalogRepository, CatalogSnapshot, InventoryStore, load_snapshot
from converdata.config import load_settings
from converdata.curation import CurationRepository, KnowledgeWriter
from converdata.flows.discover import DiscoverDeps, DiscoverService
from converdata.memory.memory_store import InMemoryVectorStore
from converdata.models.identity import UserContext


@dataclass
class Stores:
    repository: CatalogRepository | None  # None: el catálogo es el directorio `data_root`
    writer: KnowledgeWriter
    curation: CurationRepository
    inventory: InventoryStore


def open_stores(db: str | None, *, data_root: str | Path, curation_dir: str | Path,
                inventory_path: str | Path) -> Stores:
    if db:
        from converdata.storage.catalog_repository import SqlServerCatalogRepository
        from converdata.storage.connection import connector
        from converdata.storage.curation_repository import SqlServerCurationRepository
        from converdata.storage.migrations import require_current

        connect = connector(db)
        require_current(connect)
        repository = SqlServerCatalogRepository(connect)
        return Stores(repository=repository, writer=repository, curation=SqlServerCurationRepository(connect),
                      inventory=repository)
    from converdata.storage.files import FileCurationRepository, FileInventoryStore, FileKnowledgeWriter

    return Stores(repository=None, writer=FileKnowledgeWriter(Path(data_root)),
                  curation=FileCurationRepository(Path(curation_dir)), inventory=FileInventoryStore(Path(inventory_path)))


def build_service(
    root: str | Path, *, models_path: str | Path | None = None, gateway=None, **overrides
) -> DiscoverService:
    """Sin `models_path` ni `gateway`, modo determinista. Con ellos, los nodos `intent`, `rerank` y `respond` pasan
    por el gateway de LLM (NVIDIA NIM o Bedrock según `config/models.yaml`). La búsqueda es siempre léxica."""
    root = Path(root)
    return build_service_from_snapshot(
        load_snapshot(root), settings_path=root / "config" / "settings.yaml", models_path=models_path,
        gateway=gateway, **overrides)


def build_service_with_knowledge(root: str | Path, knowledge_dir: str | Path, **kwargs) -> DiscoverService:
    """El catálogo de `root` más las fuentes de conocimiento de `knowledge_dir` (misma estructura que `knowledge/`).
    Sirve para medir qué aporta el conocimiento sobre un catálogo sin tocarlo (`eval discovery --knowledge`)."""
    from converdata.catalog.store import load_knowledge

    root = Path(root)
    snapshot, extra = load_snapshot(root), load_knowledge(knowledge_dir)
    kb = snapshot.knowledge
    for name in ("items", "rules", "golden", "lineage", "entities"):
        getattr(kb, name).extend(getattr(extra, name))
    return build_service_from_snapshot(snapshot, settings_path=root / "config" / "settings.yaml", **kwargs)


def build_service_from_db(connect, **kwargs) -> DiscoverService:
    """Lo mismo, con el catálogo publicado en la BD `ConverData` (OP-02, HU-09). `connect` abre una conexión."""
    from converdata.storage.catalog_repository import SqlServerCatalogRepository

    loaded = SqlServerCatalogRepository(connect).load()
    if loaded is None:
        raise LookupError("La BD ConverData no tiene ningún catálogo publicado (converdata catalog publish)")
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
        from converdata.llm.gateway import LLMGateway

        gateway = LLMGateway.from_file(models_path)
    if gateway is not None:
        from converdata.llm.nodes import LlmIntentClassifier, LlmNarrator, LlmReranker

        if gateway.has_role("planner"):
            llm_ports["intent_classifier"] = LlmIntentClassifier(gateway.chat("planner"))
            llm_ports["reranker"] = LlmReranker(gateway.chat("planner"))
        if gateway.has_role("fast"):
            llm_ports["narrator"] = LlmNarrator(gateway.chat("fast"))
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

    En producción `visible_ids` lo calcula ConverData-API con el login SQL de cada usuario (F14)."""
    ids = frozenset(
        o.id for o in service.deps.catalog.objects if databases is None or o.database in databases
    )
    return UserContext(user_id=user_id, groups=list(groups or []), visible_ids=ids)
