"""`InMemoryVectorStore`: el índice de búsqueda de DiscoveryDataAgent-API (OP-02; PRD §13, decisión 9).

Índice léxico BM25 en memoria, con el filtro de permisos aplicado **antes** del ranking. Se reconstruye al arrancar y
cuando cambia el catálogo. No hay canal vectorial ni embeddings: el nombre `VectorStore` es histórico. El ranking
fusiona con Reciprocal Rank Fusion la lista de BM25 y la de coincidencia exacta del nombre técnico.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from discovery_data_agent.catalog.ids import short_name, table_key
from discovery_data_agent.catalog.store import Catalog
from discovery_data_agent.memory.base import (
    ColumnHit,
    GoldenDiscoveryHit,
    IndexStats,
    KnowledgeHit,
    TableHit,
)
from discovery_data_agent.memory.text import normalized_name, tokenize
from discovery_data_agent.models.knowledge import GoldenDiscovery, KnowledgeItem, KnowledgeKind

RRF_K = 60
_SOURCE_RANK = {"human": 0, "data_dictionary": 1, "ms_description": 2, "document": 3, "generated": 4}


@dataclass
class _Doc:
    key: str
    text: str
    tokens: list[str]
    access_ids: frozenset[str]  # ids físicos que dan acceso; vacío = sin restricción por catálogo
    payload: object = None
    database: str | None = None


@dataclass
class _Collection:
    docs: list[_Doc] = field(default_factory=list)
    df: Counter = field(default_factory=Counter)
    avgdl: float = 0.0

    def finalize(self) -> None:
        self.df = Counter()
        for doc in self.docs:
            self.df.update(set(doc.tokens))
        self.avgdl = sum(len(d.tokens) for d in self.docs) / max(len(self.docs), 1)

    def bm25(self, query_tokens: list[str], doc: _Doc, k1: float = 1.2, b: float = 0.75) -> float:
        tf = Counter(doc.tokens)
        n = len(self.docs)
        score = 0.0
        for tok in set(query_tokens):
            if tok not in tf:
                continue
            idf = math.log(1 + (n - self.df[tok] + 0.5) / (self.df[tok] + 0.5))
            freq = tf[tok]
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(doc.tokens) / (self.avgdl or 1)))
        return score


class InMemoryVectorStore:
    def __init__(self):
        self._tables = _Collection()
        self._columns = _Collection()
        self._knowledge = _Collection()
        self._golden = _Collection()
        self._catalog: Catalog | None = None

    # --- indexación ------------------------------------------------------------------------
    def index_catalog(self, catalog: Catalog) -> IndexStats:
        """Un documento por `asset_key` (no por ambiente); idempotente: reconstruye las colecciones."""
        self._catalog = catalog
        self._tables, self._columns = _Collection(), _Collection()
        for key in catalog.table_keys():
            copies = catalog.copies(key)
            ref = copies[0]
            access = frozenset(o.id for o in copies)
            col_names = ", ".join(c.name for c in ref.columns)
            text = f"{ref.schema_}.{ref.name}: {ref.description or ''}. Sinónimos: {', '.join(ref.synonyms)}. Columnas: {col_names}"
            self._tables.docs.append(_Doc(key, text, tokenize(text), access, ref, ref.database))
            for col in _merged_columns(copies):
                ckey = ref.column_asset_key(col.name)
                ctext = (
                    f"{ref.name}.{col.name} ({col.type}): {col.description or ''}. "
                    f"Sinónimos: {', '.join(col.synonyms)}"
                )
                col_access = frozenset(o.id for o in copies if any(c.name == col.name for c in o.columns))
                # El texto de la columna no lleva la descripción de la tabla, para que no se reparta como ruido
                # entre todas sus columnas.
                self._columns.docs.append(_Doc(ckey, ctext, tokenize(ctext), col_access, col, ref.database))
        for coll in (self._tables, self._columns):
            coll.finalize()
        return IndexStats(
            documents=len(self._tables.docs) + len(self._columns.docs),
            collections={"tables": len(self._tables.docs), "columns": len(self._columns.docs)},
        )

    def index_knowledge(self, items: list[KnowledgeItem], golden: list[GoldenDiscovery] | None = None) -> IndexStats:
        if self._catalog is None:
            raise RuntimeError("index_catalog debe ejecutarse antes que index_knowledge")
        self._knowledge, self._golden = _Collection(), _Collection()
        for item in items:
            self._knowledge.docs.append(_Doc(item.id, item.text, tokenize(item.text), frozenset(), item))
        for g in golden or []:
            if g.rejected:
                continue
            self._golden.docs.append(_Doc(g.id, g.template, tokenize(g.template), frozenset(), g))
        for coll in (self._knowledge, self._golden):
            coll.finalize()
        return IndexStats(
            documents=len(self._knowledge.docs) + len(self._golden.docs),
            collections={"knowledge": len(self._knowledge.docs), "golden_discovery": len(self._golden.docs)},
        )

    # --- búsqueda --------------------------------------------------------------------------
    def search_tables(self, query, *, k=30, visible_ids, databases=None) -> list[TableHit]:
        _require(visible_ids)
        docs = [
            d
            for d in self._tables.docs
            if d.access_ids & visible_ids and (not databases or d.database in databases)
        ]
        return [TableHit(d.key, s) for d, s in self._hybrid(self._tables, docs, query, k)]

    def search_columns(self, query, *, k=50, visible_ids, table_ids=None) -> list[ColumnHit]:
        _require(visible_ids)
        docs = [
            d
            for d in self._columns.docs
            if d.access_ids & visible_ids and (not table_ids or table_key(d.key) in table_ids)
        ]
        return [ColumnHit(d.key, table_key(d.key), s) for d, s in self._hybrid(self._columns, docs, query, k)]

    def search_knowledge(self, query, *, k=30, visible_ids, groups, kinds=None) -> list[KnowledgeHit]:
        _require(visible_ids)
        group_set = set(groups)
        docs = [
            d
            for d in self._knowledge.docs
            if (kinds is None or d.payload.kind in kinds)
            and self._knowledge_visible(d.payload, visible_ids, group_set)
        ]
        return [KnowledgeHit(d.payload, s) for d, s in self._hybrid(self._knowledge, docs, query, k)]

    def search_golden_discovery(self, query, *, k=5, visible_ids) -> list[GoldenDiscoveryHit]:
        _require(visible_ids)
        docs = [d for d in self._golden.docs if all(self._catalog.is_visible(a, visible_ids) for a in d.payload.asset_keys)]
        q_tokens = set(tokenize(query))
        hits = []
        for doc, score in self._hybrid(self._golden, docs, query, k):
            d_tokens = set(doc.tokens)
            lexical = len(q_tokens & d_tokens) / len(d_tokens) if d_tokens else 0.0
            hits.append(GoldenDiscoveryHit(doc.payload, score, round(lexical, 4)))
        return hits

    def _knowledge_visible(self, item: KnowledgeItem, visible_ids: frozenset[str], groups: set[str]) -> bool:
        # F14: todos los activos vinculados visibles y, si hay ACL de origen, pertenencia a sus grupos.
        if item.allowed_groups is not None and not groups.intersection(item.allowed_groups):
            return False
        return all(self._catalog.is_visible(a, visible_ids) for a in item.asset_keys)

    def _hybrid(self, coll: _Collection, docs: list[_Doc], query: str, k: int) -> list[tuple[_Doc, float]]:
        if not docs:
            return []
        q_tokens = tokenize(query)
        lexical = sorted(
            ((d, coll.bm25(q_tokens, d)) for d in docs), key=lambda x: (-x[1], x[0].key)
        )
        rankings = [[d for d, s in lexical if s > 0][:k]]
        # Nombre técnico exacto (`LegalClientId`): lista propia en la fusión para que gane al ruido de BM25.
        exact = [d for d in docs if normalized_name(short_name(d.key)) in {normalized_name(w) for w in query.split()}]
        if exact:
            rankings.append(exact)
        fused: dict[str, float] = {}
        by_key = {d.key: d for d in docs}
        for ranking in rankings:
            for rank, doc in enumerate(ranking, start=1):
                fused[doc.key] = fused.get(doc.key, 0.0) + 1.0 / (RRF_K + rank)
        ordered = sorted(fused.items(), key=lambda x: (-x[1], x[0]))[:k]
        return [(by_key[key], score) for key, score in ordered]


def _merged_columns(copies):
    """Unión de columnas entre ambientes; la descripción de mejor fuente gana (F2)."""
    best = {}
    for obj in copies:
        for col in obj.columns:
            cur = best.get(col.name)
            if cur is None or _SOURCE_RANK[col.description_source] < _SOURCE_RANK[cur.description_source]:
                best[col.name] = col
    return list(best.values())


def _require(visible_ids) -> None:
    if visible_ids is None:
        raise ValueError("visible_ids es obligatorio en toda búsqueda (F14)")
