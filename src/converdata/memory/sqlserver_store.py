"""`SqlServerVectorStore`: `VectorStore` sobre la BD `ConverData` en SQL Server 2025 (OP-02).

- Búsqueda híbrida en una sola consulta: top-k `CONTAINSTABLE` (Full-Text, español) + top-k `VECTOR_DISTANCE('cosine')`,
  fusionados con Reciprocal Rank Fusion en T-SQL (mismo algoritmo que `InMemoryVectorStore`).
- Filtro de permisos **antes** del ranking: `visible_ids` viaja como JSON (`OPENJSON`) y se cruza con
  `catalog.search_doc_access` / `knowledge.item_asset`.
- Los embeddings los genera la aplicación (rol `embed` de F16); SQL Server solo los guarda y busca.

Estado: escrito contra el DDL de `db/converdata/001_esquemas.sql`; pendiente de los tests de contrato contra una instancia
SQL Server 2025 real (OP-02-CA4). Los tests de este repositorio corren contra `InMemoryVectorStore`.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from converdata.catalog.ids import table_key
from converdata.catalog.store import Catalog
from converdata.memory.base import ColumnHit, Embedder, GoldenDiscoveryHit, IndexStats, KnowledgeHit, TableHit
from converdata.memory.memory_store import _merged_columns
from converdata.memory.text import tokenize
from converdata.models.knowledge import GoldenDiscovery, KnowledgeItem, LinkedAsset

RRF_K = 60
NO_MATCH = "\"zzqxnomatch\""  # CONTAINSTABLE no admite condición vacía; solo vectorial

_HYBRID_DOCS = """
DECLARE @vis TABLE (physical_id nvarchar(400) PRIMARY KEY);
INSERT @vis SELECT DISTINCT value FROM OPENJSON(?);
DECLARE @q VECTOR(1024) = CASE WHEN ? IS NULL THEN NULL ELSE CAST(? AS VECTOR(1024)) END;
DECLARE @k int = ?, @ft nvarchar(4000) = ?, @model varchar(100) = ?, @collection varchar(20) = ?,
        @filter nvarchar(max) = ?;
WITH allowed AS (
    SELECT DISTINCT d.doc_id
    FROM catalog.search_doc d
    JOIN catalog.search_doc_access a ON a.doc_id = d.doc_id
    JOIN @vis v ON v.physical_id = a.physical_id
    WHERE d.collection = @collection
      AND (@filter IS NULL OR d.database_name IN (SELECT value FROM OPENJSON(@filter))
           OR LEFT(d.asset_key, LEN(d.asset_key) - CHARINDEX('.', REVERSE(d.asset_key))) IN (SELECT value FROM OPENJSON(@filter)))
),
lex AS (
    SELECT TOP (@k) ft.[KEY] AS doc_id, ROW_NUMBER() OVER (ORDER BY ft.RANK DESC) AS rnk
    FROM CONTAINSTABLE(catalog.search_doc, content, @ft) ft
    JOIN allowed al ON al.doc_id = ft.[KEY]
    ORDER BY ft.RANK DESC
),
sem AS (
    SELECT TOP (@k) d.doc_id, ROW_NUMBER() OVER (ORDER BY VECTOR_DISTANCE('cosine', d.embedding, @q)) AS rnk
    FROM catalog.search_doc d
    JOIN allowed al ON al.doc_id = d.doc_id
    WHERE @q IS NOT NULL AND d.embedding IS NOT NULL AND d.embed_model = @model
    ORDER BY VECTOR_DISTANCE('cosine', d.embedding, @q)
)
SELECT TOP (@k) d.asset_key, SUM(1.0 / (60 + x.rnk)) AS score
FROM (SELECT doc_id, rnk FROM lex UNION ALL SELECT doc_id, rnk FROM sem) x
JOIN catalog.search_doc d ON d.doc_id = x.doc_id
GROUP BY d.asset_key
ORDER BY score DESC, d.asset_key;
"""

_HYBRID_KNOWLEDGE = """
DECLARE @vis TABLE (physical_id nvarchar(400) PRIMARY KEY);
INSERT @vis SELECT DISTINCT value FROM OPENJSON(?);
DECLARE @q VECTOR(1024) = CASE WHEN ? IS NULL THEN NULL ELSE CAST(? AS VECTOR(1024)) END;
DECLARE @k int = ?, @ft nvarchar(4000) = ?, @model varchar(100) = ?, @groups nvarchar(max) = ?, @kinds nvarchar(max) = ?;
WITH allowed AS (
    SELECT i.item_id
    FROM knowledge.item i
    WHERE (@kinds IS NULL OR i.kind IN (SELECT value FROM OPENJSON(@kinds)))
      AND (i.allowed_groups_json IS NULL OR EXISTS (
            SELECT 1 FROM OPENJSON(i.allowed_groups_json) g JOIN OPENJSON(@groups) ug ON ug.value = g.value))
      -- F14: todos los activos vinculados deben ser visibles
      AND NOT EXISTS (
            SELECT 1 FROM knowledge.item_asset ia
            WHERE ia.item_id = i.item_id
              AND NOT EXISTS (SELECT 1 FROM catalog.object o JOIN @vis v ON v.physical_id = o.physical_id
                              WHERE o.asset_key = ia.table_key AND o.deprecated = 0))
),
lex AS (
    SELECT TOP (@k) ft.[KEY] AS item_id, ROW_NUMBER() OVER (ORDER BY ft.RANK DESC) AS rnk
    FROM CONTAINSTABLE(knowledge.item, content, @ft) ft JOIN allowed al ON al.item_id = ft.[KEY]
    ORDER BY ft.RANK DESC
),
sem AS (
    SELECT TOP (@k) i.item_id, ROW_NUMBER() OVER (ORDER BY VECTOR_DISTANCE('cosine', i.embedding, @q)) AS rnk
    FROM knowledge.item i JOIN allowed al ON al.item_id = i.item_id
    WHERE @q IS NOT NULL AND i.embedding IS NOT NULL AND i.embed_model = @model
    ORDER BY VECTOR_DISTANCE('cosine', i.embedding, @q)
)
SELECT TOP (@k) i.item_id, i.kind, i.content, i.source, i.domain, i.linked_assets_json, i.allowed_groups_json,
       i.reviewed, i.redacted, s.score
FROM (SELECT item_id, SUM(1.0 / (60 + rnk)) AS score
      FROM (SELECT item_id, rnk FROM lex UNION ALL SELECT item_id, rnk FROM sem) x GROUP BY item_id) s
JOIN knowledge.item i ON i.item_id = s.item_id
ORDER BY s.score DESC, i.item_id;
"""

_GOLDEN = """
DECLARE @vis TABLE (physical_id nvarchar(400) PRIMARY KEY);
INSERT @vis SELECT DISTINCT value FROM OPENJSON(?);
DECLARE @k int = ?, @ft nvarchar(4000) = ?;
SELECT TOP (@k) g.golden_id, g.template, g.asset_keys_json, g.confirmed_by, g.confirmations, ft.RANK
FROM CONTAINSTABLE(knowledge.golden_discovery, template, @ft) ft
JOIN knowledge.golden_discovery g ON g.golden_id = ft.[KEY]
WHERE g.rejected = 0
  AND NOT EXISTS (   -- un golden solo se devuelve si todos sus activos son visibles (F2)
      SELECT 1 FROM OPENJSON(g.asset_keys_json) a
      WHERE NOT EXISTS (
          SELECT 1 FROM catalog.object o JOIN @vis v ON v.physical_id = o.physical_id
          WHERE o.asset_key = CASE WHEN LEN(a.value) - LEN(REPLACE(a.value, '.', '')) >= 3
                                   THEN LEFT(a.value, LEN(a.value) - CHARINDEX('.', REVERSE(a.value)))
                                   ELSE a.value END))
ORDER BY ft.RANK DESC, g.golden_id;
"""


def fulltext_condition(query: str) -> str | None:
    """Condición de `CONTAINSTABLE` con prefijos de los mismos stems que el BM25 en memoria: `"identi*" OR "client*"`."""
    terms = sorted({t for t in tokenize(query) if re.fullmatch(r"[a-z0-9]+", t)})
    return " OR ".join(f'"{t}*"' for t in terms) or None


class SqlServerVectorStore:
    def __init__(self, connect: Callable[[], object], embedder: Embedder | None = None, embed_model: str = "lexical-only"):
        self._connect = connect  # conexión pyodbc a la BD ConverData con la gMSA del servicio (OP-02)
        self.embedder = embedder
        self.embed_model = embed_model
        self._catalog: Catalog | None = None

    # --- indexación (la ejecuta ConverData-Builder) ------------------------------------------
    def index_catalog(self, catalog: Catalog) -> IndexStats:
        self._catalog = catalog
        rows = []
        for key in catalog.table_keys():
            copies = catalog.copies(key)
            ref = copies[0]
            text = (
                f"{ref.schema_}.{ref.name}: {ref.description or ''}. Sinónimos: {', '.join(ref.synonyms)}. "
                f"Columnas: {', '.join(c.name for c in ref.columns)}"
            )
            rows.append(("tables", key, ref.database, text, [o.id for o in copies]))
            for col in _merged_columns(copies):
                ctext = f"{ref.name}.{col.name} ({col.type}): {col.description or ''}. Sinónimos: {', '.join(col.synonyms)}"
                access = [o.id for o in copies if any(c.name == col.name for c in o.columns)]
                rows.append(("columns", ref.column_asset_key(col.name), ref.database, ctext, access))
        vectors = self.embedder.embed_documents([r[3] for r in rows]) if self.embedder else [None] * len(rows)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM catalog.search_doc")  # idempotente: reconstrucción completa en una transacción
            for (collection, key, db, text, access), vec in zip(rows, vectors):
                cur.execute(
                    "INSERT catalog.search_doc (collection, asset_key, database_name, content, access_ids, embedding, embed_model) "
                    "OUTPUT INSERTED.doc_id "
                    "VALUES (?, ?, ?, ?, ?, CASE WHEN ? IS NULL THEN NULL ELSE CAST(? AS VECTOR(1024)) END, ?)",
                    collection, key, db, text, json.dumps(access), _vec(vec), _vec(vec), self.embed_model,
                )
                doc_id = cur.fetchone()[0]
                cur.executemany(
                    "INSERT catalog.search_doc_access (doc_id, physical_id) VALUES (?, ?)", [(doc_id, a) for a in access]
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        tables = sum(1 for r in rows if r[0] == "tables")
        return IndexStats(documents=len(rows), collections={"tables": tables, "columns": len(rows) - tables})

    def index_knowledge(self, items: list[KnowledgeItem], golden: list[GoldenDiscovery] | None = None) -> IndexStats:
        golden = golden or []
        vectors = self.embedder.embed_documents([i.text for i in items]) if self.embedder and items else [None] * len(items)
        conn = self._connect()
        try:
            cur = conn.cursor()
            for item, vec in zip(items, vectors):
                cur.execute("DELETE FROM knowledge.item_asset WHERE item_id = ?", item.id)
                cur.execute(
                    "MERGE knowledge.item AS t USING (SELECT ? AS item_id) AS s ON t.item_id = s.item_id "
                    "WHEN MATCHED THEN UPDATE SET kind=?, content=?, source=?, domain=?, linked_assets_json=?, "
                    "  allowed_groups_json=?, reviewed=?, redacted=?, "
                    "  embedding=CASE WHEN ? IS NULL THEN NULL ELSE CAST(? AS VECTOR(1024)) END, embed_model=? "
                    "WHEN NOT MATCHED THEN INSERT (item_id, kind, content, source, domain, linked_assets_json, "
                    "  allowed_groups_json, reviewed, redacted, embedding, embed_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "  CASE WHEN ? IS NULL THEN NULL ELSE CAST(? AS VECTOR(1024)) END, ?);",
                    item.id,
                    *_item_values(item, vec, self.embed_model),
                    item.id,
                    *_item_values(item, vec, self.embed_model),
                )
                cur.executemany(
                    "INSERT knowledge.item_asset (item_id, asset_key, table_key, method, score) VALUES (?, ?, ?, ?, ?)",
                    [(item.id, la.asset_key, table_key(la.asset_key), la.method, la.score) for la in item.linked_assets],
                )
            for g in golden:
                cur.execute(
                    "MERGE knowledge.golden_discovery AS t USING (SELECT ? AS golden_id) AS s ON t.golden_id = s.golden_id "
                    "WHEN MATCHED THEN UPDATE SET template=?, asset_keys_json=?, confirmed_by=?, confirmations=?, rejected=? "
                    "WHEN NOT MATCHED THEN INSERT (golden_id, template, asset_keys_json, confirmed_by, confirmations, rejected) "
                    "VALUES (?, ?, ?, ?, ?, ?);",
                    g.id, g.template, json.dumps(g.asset_keys), g.confirmed_by, g.confirmations, int(g.rejected),
                    g.id, g.template, json.dumps(g.asset_keys), g.confirmed_by, g.confirmations, int(g.rejected),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return IndexStats(documents=len(items) + len(golden), collections={"knowledge": len(items), "golden_discovery": len(golden)})

    # --- búsqueda ----------------------------------------------------------------------------
    def search_tables(self, query, *, k=30, visible_ids, databases=None) -> list[TableHit]:
        rows = self._docs("tables", query, k, visible_ids, databases)
        return [TableHit(key, float(score)) for key, score in rows]

    def search_columns(self, query, *, k=50, visible_ids, table_ids=None) -> list[ColumnHit]:
        rows = self._docs("columns", query, k, visible_ids, table_ids)
        return [ColumnHit(key, table_key(key), float(score)) for key, score in rows]

    def search_knowledge(self, query, *, k=30, visible_ids, groups, kinds=None) -> list[KnowledgeHit]:
        _require(visible_ids)
        ft = fulltext_condition(query)
        qvec = _vec(self.embedder.embed_query(query)) if self.embedder else None
        if ft is None and qvec is None:
            return []
        rows = self._query(
            _HYBRID_KNOWLEDGE, json.dumps(sorted(visible_ids)), qvec, qvec, k, ft or NO_MATCH, self.embed_model,
            json.dumps(list(groups)), json.dumps(kinds) if kinds else None,
        )
        hits = []
        for item_id, kind, content, source, domain, linked, allowed, reviewed, redacted, score in rows:
            item = KnowledgeItem(
                id=item_id, kind=kind, text=content, source=source, domain=domain,
                linked_assets=[LinkedAsset.model_validate(x) for x in json.loads(linked)],
                allowed_groups=json.loads(allowed) if allowed else None, reviewed=bool(reviewed), redacted=bool(redacted),
            )
            hits.append(KnowledgeHit(item, float(score)))
        return hits

    def search_golden_discovery(self, query, *, k=5, visible_ids) -> list[GoldenDiscoveryHit]:
        _require(visible_ids)
        ft = fulltext_condition(query)
        if ft is None:
            return []
        q_tokens = set(tokenize(query))
        hits = []
        for rank, (gid, template, keys, confirmed_by, confirmations, _ft_rank) in enumerate(
            self._query(_GOLDEN, json.dumps(sorted(visible_ids)), k, ft), start=1
        ):
            g = GoldenDiscovery(id=gid, template=template, asset_keys=json.loads(keys),
                                confirmed_by=confirmed_by, confirmations=confirmations)
            d_tokens = set(tokenize(template))
            similarity = len(q_tokens & d_tokens) / len(d_tokens) if d_tokens else 0.0
            hits.append(GoldenDiscoveryHit(g, 1.0 / (RRF_K + rank), round(similarity, 4)))
        return hits

    def _docs(self, collection, query, k, visible_ids, filter_values):
        _require(visible_ids)
        ft = fulltext_condition(query)
        qvec = _vec(self.embedder.embed_query(query)) if self.embedder else None
        if ft is None and qvec is None:
            return []
        return self._query(
            _HYBRID_DOCS, json.dumps(sorted(visible_ids)), qvec, qvec, k, ft or NO_MATCH, self.embed_model, collection,
            json.dumps(list(filter_values)) if filter_values else None,
        )

    def _query(self, sql, *params):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, *params)
            while cur.description is None and cur.nextset():  # salta los recuentos de DECLARE/INSERT
                pass
            return cur.fetchall()
        finally:
            conn.close()


def _vec(vec) -> str | None:
    return json.dumps([float(x) for x in vec]) if vec is not None else None


def _item_values(item: KnowledgeItem, vec, model: str) -> tuple:
    return (
        item.kind, item.text, item.source, item.domain,
        json.dumps([la.model_dump() for la in item.linked_assets]),
        json.dumps(item.allowed_groups) if item.allowed_groups is not None else None,
        int(item.reviewed), int(item.redacted), _vec(vec), _vec(vec), model,
    )


def _require(visible_ids) -> None:
    if visible_ids is None:
        raise ValueError("visible_ids es obligatorio en toda búsqueda (F14)")
