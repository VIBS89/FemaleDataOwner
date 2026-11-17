"""Ensambla el DiscoverFlow a partir de un directorio con `config/`, `catalog/` y `knowledge/`.

El índice de búsqueda es léxico y vive en memoria (`InMemoryVectorStore`, PRD §13 decisión 9). La carga desde la BD
`ConverData` (OP-02, HU-09) usará la misma forma de ensamblar.
"""

from __future__ import annotations

from pathlib import Path

from converdata.catalog.store import CatalogSnapshot, load_snapshot
from converdata.config import load_settings
from converdata.flows.discover import DiscoverDeps, DiscoverService
from converdata.memory.memory_store import InMemoryVectorStore
from converdata.models.identity import UserContext


def build_service(
    root: str | Path, *, models_path: str | Path | None = None, gateway=None, llm_nodes: bool = True,
    embedder_override=None, **overrides
) -> DiscoverService:
    """Sin `models_path` ni `gateway`, modo determinista. Con ellos, los nodos `intent`, `rerank` y `respond` y los
    embeddings pasan por el gateway de LLM (NVIDIA NIM o Bedrock según `config/models.yaml`)."""
    root = Path(root)
    return build_service_from_snapshot(
        load_snapshot(root), settings_path=root / "config" / "settings.yaml", models_path=models_path,
        gateway=gateway, llm_nodes=llm_nodes, embedder_override=embedder_override, **overrides)


def build_service_from_db(connect, **kwargs) -> DiscoverService:
    """Lo mismo, con el catálogo publicado en la BD `ConverData` (OP-02, HU-09). `connect` abre una conexión."""
    from converdata.storage.catalog_repository import SqlServerCatalogRepository

    loaded = SqlServerCatalogRepository(connect).load()
    if loaded is None:
        raise LookupError("La BD ConverData no tiene ningún catálogo publicado (converdata catalog publish)")
    return build_service_from_snapshot(loaded[0], **kwargs)


def build_service_from_snapshot(
    snapshot: CatalogSnapshot, *, settings_path: str | Path | None = None, models_path: str | Path | None = None,
    gateway=None, llm_nodes: bool = True, embedder_override=None, **overrides
) -> DiscoverService:
    catalog, knowledge, owners = snapshot.catalog(), snapshot.knowledge, snapshot.owners
    settings = load_settings(settings_path)

    embedder, embed_model = None, None
    llm_ports: dict = {}
    model_names = {}
    if models_path and gateway is None:
        from converdata.llm.gateway import LLMGateway

        gateway = LLMGateway.from_file(models_path)
    if gateway is not None:
        from converdata.llm.nodes import LlmIntentClassifier, LlmNarrator, LlmReranker

        if llm_nodes and gateway.has_role("planner"):
            llm_ports["intent_classifier"] = LlmIntentClassifier(gateway.chat("planner"))
            llm_ports["reranker"] = LlmReranker(gateway.chat("planner"))
        if llm_nodes and gateway.has_role("fast"):
            llm_ports["narrator"] = LlmNarrator(gateway.chat("fast"))
        embedder, embed_model = gateway.embeddings(), gateway.embed_model
        model_names = gateway.labels  # vista viva: proveedor:modelo que atendió cada rol (audit_step.model)

    if embedder_override is not None:  # tests y evaluaciones con un embedder propio
        embedder, embed_model = embedder_override, type(embedder_override).__name__
    store = InMemoryVectorStore(embedder=embedder, embed_model=embed_model)
    store.index_catalog(catalog)
    store.index_knowledge(knowledge.all_items(), knowledge.golden)
    deps = DiscoverDeps(
        catalog=catalog, knowledge=knowledge, store=store, owners=owners, settings=settings,
        model_names=model_names, **{**llm_ports, **overrides},
    )
    return DiscoverService(deps)


def user_with_databases(service: DiscoverService, user_id: str, databases: list[str] | None, groups=None) -> UserContext:
    """Identidad de desarrollo: visibilidad sobre las BDs indicadas (todas si `None`).

    En producción `visible_ids` lo calcula `VisibilityResolver` con el login SQL del usuario (F14)."""
    ids = frozenset(
        o.id for o in service.deps.catalog.objects if databases is None or o.database in databases
    )
    return UserContext(user_id=user_id, groups=list(groups or []), visible_ids=ids)
