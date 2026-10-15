# F2 — Memoria semántica · común

> Implementación por entorno: **cloud native** → OpenSearch Serverless ([CN-02](../cloud-native/CN-02-catalogo-memoria.md)) · **on-premise** → ChromaDB embebida ([OP-02](../on-premise/OP-02-catalogo-memoria.md))

## Historia de usuario
Como **agente**, necesito buscar rápidamente qué tablas, columnas y consultas previas son relevantes para una pregunta,
sin cargar las más de 300 tablas en el contexto del LLM.

## Colecciones lógicas
| Colección | Documento embebido | Metadatos |
|---|---|---|
| `tables` | `"{schema}.{name}: {description}. Sinónimos: … Columnas: c1, c2…"` | `id, server, database, schema, domain, kind, row_count` |
| `columns` | `"{table}.{column} ({type}): {description}"` | `table_id, database, pii, low_cardinality` |
| `glossary` | `"{término}: {definición}"` | `domain, maps_to (table/column/expresión)` |
| `golden_sql` | **Plantilla** de la pregunta, con los literales sustituidos por placeholders tipados | `sql_template, procedure, database, tables_used, approved_by, created_at` |

- **No existe colección de valores**: los valores reales se resuelven siempre en vivo contra SQL Server (F5).
- **Embeddings**: rol `embed` de F16 (Cohere Embed Multilingual en Bedrock). El índice guarda `embed_model` y la búsqueda verifica que coincida.
- **Filtrado por permisos**: toda búsqueda recibe el `visible_ids` de la sesión (F14) y lo aplica como pre-filtro.

## Interfaz `VectorStore` (idéntica en ambos entornos)
```python
index_catalog(catalog_dir) -> IndexStats
search_tables(query, k=30, databases=None, visible_ids=None) -> list[TableHit]
search_columns(query, k=50, table_ids=None) -> list[ColumnHit]
search_golden(query, k=5, database=None) -> list[GoldenHit]
add_golden_template(template, sql_template|procedure, meta) -> None
```
Hay dos implementaciones, `OpenSearchStore` y `ChromaStore`. Los mismos tests de contrato corren contra ambas.

## Glosario de negocio
`glossary.yaml` se mantiene a mano y el CatalogBuilder lo amplía con sugerencias (`reviewed: false`). Ejemplo:
```yaml
- term: venta neta
  definition: "Importe del pedido menos descuentos y devoluciones."
  maps_to: "SUM(p.Importe - p.Descuento) - SUM(d.Importe)"
  tables: [Ventas.dbo.Pedido, Ventas.dbo.Devolucion]
```

## Aprendizaje continuo
- Una respuesta con 👍 y `confidence ≥ 0.8` genera un golden SQL. El **original** (pregunta y SQL con literales) se guarda en el almacén de auditoría del entorno (F11). En el índice solo entra su **plantilla anonimizada**; si queda algún literal sin sustituir, no se publica.
- Una respuesta con 👎 se guarda en auditoría para revisión; nunca entra automáticamente al índice.

## Criterios de aceptación
1. `index_catalog` es idempotente: al reindexar, el número de documentos no cambia.
2. Con un `visible_ids` que excluye el esquema `RRHH`, ninguna búsqueda devuelve objetos de `RRHH`.
3. Ninguna colección contiene valores de datos ni literales de preguntas (test con literales marcados).
4. `search_tables` con k=30 tarda menos de 300 ms en AdventureWorks.
