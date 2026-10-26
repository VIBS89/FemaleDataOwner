"""Interfaz `VectorStore` (F2), idéntica en on-premise (`SqlServerVectorStore`) y cloud native (`OpenSearchStore`).

`visible_ids` es obligatorio en toda búsqueda: no existe una llamada sin filtro de permisos (F14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from converdata.models.knowledge import GoldenDiscovery, KnowledgeItem, KnowledgeKind


class Embedder(Protocol):
    """Lo cumple `BedrockEmbeddings` de langchain-aws (rol `embed` de F16) sin importarlo aquí."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class TableHit:
    asset_key: str
    score: float


@dataclass(frozen=True)
class ColumnHit:
    asset_key: str
    table_key: str
    score: float


@dataclass(frozen=True)
class KnowledgeHit:
    item: KnowledgeItem
    score: float


@dataclass(frozen=True)
class GoldenDiscoveryHit:
    golden: GoldenDiscovery
    score: float
    similarity: float  # 0..1, comparable con el umbral 0.85 de F22


@dataclass
class IndexStats:
    documents: int = 0
    collections: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    def index_catalog(self, catalog) -> IndexStats: ...

    def index_knowledge(self, items: list[KnowledgeItem], golden: list[GoldenDiscovery] | None = None) -> IndexStats: ...

    def search_tables(
        self, query: str, *, k: int = 30, visible_ids: frozenset[str], databases: list[str] | None = None
    ) -> list[TableHit]: ...

    def search_columns(
        self, query: str, *, k: int = 50, visible_ids: frozenset[str], table_ids: list[str] | None = None
    ) -> list[ColumnHit]: ...

    def search_knowledge(
        self,
        query: str,
        *,
        k: int = 30,
        visible_ids: frozenset[str],
        groups: list[str],
        kinds: list[KnowledgeKind] | None = None,
    ) -> list[KnowledgeHit]: ...

    def search_golden_discovery(self, query: str, *, k: int = 5, visible_ids: frozenset[str]) -> list[GoldenDiscoveryHit]: ...
