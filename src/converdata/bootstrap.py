"""Ensambla el DiscoverFlow a partir de un directorio con `config/`, `catalog/` y `knowledge/`.

On-premise, `ConverData-API` lo hará leyendo los esquemas de la BD `ConverData` y con `SqlServerVectorStore` (OP-02);
la forma de ensamblar es la misma.
"""

from __future__ import annotations

from pathlib import Path

from converdata.catalog.store import load_catalog, load_knowledge
from converdata.config import load_inventory, load_owners, load_settings
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
    inventory = load_inventory(root / "config" / "databases.yaml")
    catalog = load_catalog(root / "catalog", inventory)
    knowledge = load_knowledge(root / "knowledge")
    owners = load_owners(root / "config" / "owners.yaml")
    settings = load_settings(root / "config" / "settings.yaml")

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
