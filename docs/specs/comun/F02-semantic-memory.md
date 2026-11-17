# F2 — Memoria semántica · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Implementación en la fase 1a, igual en ambos despliegues: **índice léxico en memoria (BM25)** dentro de `ConverData-API` ([OP-02](../on-premise/OP-02-catalogo-memoria.md)). El despliegue en AWS usa el mismo índice dentro del contenedor de la API ([CN-02](../cloud-native/CN-02-catalogo-memoria.md)).

## Historia de usuario
Como **agente**, necesito buscar rápidamente qué tablas, columnas y consultas previas son relevantes para una pregunta,
sin cargar las más de 300 tablas en el contexto del LLM.

## Colecciones lógicas
| Colección | Documento indexado | Metadatos |
|---|---|---|
| `tables` | `"{schema}.{name}: {description}. Sinónimos: … Columnas: c1, c2…"` | `id, server, database, schema, domain, kind, row_count` |
| `columns` | `"{table}.{column} ({type}): {description}"` | `table_id, database, pii, low_cardinality` |
| `glossary` | `"{término}: {definición}"` | `domain, maps_to (table/column/expresión)` |
| `golden_sql` (fase 1b) | **Plantilla** de la pregunta, con los literales sustituidos por placeholders tipados | `sql_template, procedure, database, tables_used, approved_by, created_at` |
| `documents` | Fragmento **redactado** de documentación o diccionario (F23) | `source, section, linked_assets[], redacted, allowed_groups, reviewed` |
| `business_rules` | `"{id}: {texto}"` (F23) | `domain, applies_to[], source, owner, reviewed` |
| `etl` | `"{paquete/job/SP}: {origen} → {destino}. {descripción}"` (F23) | `kind, from[], to[], schedule` |
| `annotations` | Respuesta o corrección de un responsable (F24) | `asset_key, domain, author_group, created_at` |
| `golden_discovery` | **Plantilla** de una pregunta de descubrimiento confirmada (F24) | `asset_keys[], confirmed_by{steward\|users}, confirmations, created_at` |

Las descripciones de `tables` y `columns` usan la mejor fuente disponible (`human` > `data_dictionary` > `ms_description` > `document` >
`generated`) y se indexan por `asset_key`, con los ambientes como metadato (`environments[]`), para no duplicar un objeto por cada ambiente.

- **No existe colección de valores**: los valores reales se resuelven siempre en vivo contra SQL Server (F5).
- **Filtrado por permisos**: toda búsqueda recibe el `visible_ids` de la sesión (F14) y lo aplica como pre-filtro, antes del ranking.

## Decisión: búsqueda léxica como único canal de la fase 1a (PRD §13, decisión 9)
- `ConverData-API` carga el catálogo y el conocimiento al arrancar en un índice **BM25 en memoria** (`InMemoryVectorStore`) y lo
  recarga tras cada build, confirmación o cambio de curación. No hay embeddings, ni columnas de vectores, ni índices de texto en SQL Server.
- **Medición que lo justifica** (HU-34, 2026-10-29): el canal léxico solo dio **Hit@1 93,1 % y Hit@3 93,1 %**; añadir
  embeddings `bge-m3` **no cambió ningún caso** y subió el **p95 de 73 ms a 4,6 s**.
- El **canal semántico queda como opción experimental de desarrollo**: `InMemoryVectorStore` acepta un `embedder` y entonces fusiona
  el top-k léxico con el top-k por coseno (*Reciprocal Rank Fusion*). Se activa solo si `config/models.yaml` declara el rol `embed`
  (p. ej. `config/models.embed.yaml`, opción `--embeddings-only` de la CLI). **No se despliega** en qa ni en piloto. Reabrir la decisión
  exige repetir la medición con `converdata eval discovery` por tipo de pregunta (A–G) y mejorar el acierto sin romper la latencia de F22.
- Las preguntas largas de reporte, donde el léxico solo acierta menos, se atacan con el paso `intent` del LLM y con las fuentes de
  conocimiento (F22, F23), no con embeddings.

## Interfaz `VectorStore` (puerto; idéntico en ambos despliegues)
El puerto conserva su nombre aunque la implementación desplegada sea léxica (`src/converdata/memory/base.py`).
```python
index_catalog(source: CatalogSource) -> IndexStats      # tablas `catalog` de la BD ConverData; hoy, archivos YAML
search_tables(query, k=30, visible_ids, databases=None) -> list[TableHit]
search_columns(query, k=50, visible_ids, table_ids=None) -> list[ColumnHit]
search_golden(query, k=5, visible_ids, database=None) -> list[GoldenHit]        # fase 1b
add_golden_template(template, sql_template|procedure, meta) -> None             # fase 1b
index_knowledge(items: list[KnowledgeItem]) -> IndexStats                       # F23, F24
search_knowledge(query, k=30, visible_ids, groups, kinds=None) -> list[KnowledgeHit]
search_golden_discovery(query, k=5, visible_ids) -> list[GoldenDiscoveryHit]    # F22, F24
```
`visible_ids` (y `groups` en el conocimiento) son **obligatorios** en toda búsqueda: no existe una llamada sin filtro de permisos (F14).
Un golden SQL o golden discovery solo se devuelve si **todos** sus objetos están en `visible_ids`.

Implementaciones:
- **`InMemoryVectorStore`**: la única que se despliega. Construida y cubierta por tests.
- **`SqlServerVectorStore`**: **retirada** (PRD §13, decisión 9). El archivo `src/converdata/memory/sqlserver_store.py` y su test se eliminaron el 2026-11-16.
- No hay implementación sobre un servicio de búsqueda gestionado en la nube.

## Glosario de negocio
`glossary.yaml` se mantiene a mano y el CatalogBuilder lo amplía con sugerencias (`reviewed: false`). Ejemplo:
```yaml
- term: venta neta
  definition: "Importe del pedido menos descuentos y devoluciones."
  maps_to: "SUM(p.Importe - p.Descuento) - SUM(d.Importe)"
  tables: [Ventas.dbo.Pedido, Ventas.dbo.Devolucion]
```

## Aprendizaje continuo
- Fase 1a: un "✔ Es este" genera un golden discovery (F24). El **original** de la pregunta queda en la auditoría (F11); en el índice solo entra su **plantilla anonimizada**.
- Fase 1b: una respuesta con 👍 y `confidence ≥ 0.8` genera un golden SQL, con la misma regla; si queda algún literal sin sustituir, no se publica.
- Una respuesta rechazada se guarda en auditoría para revisión; nunca entra automáticamente al índice.

## Criterios de aceptación
1. `index_catalog` es idempotente: al reindexar, el número de documentos no cambia.
2. Con un `visible_ids` que excluye el esquema `RRHH`, ninguna búsqueda devuelve objetos de `RRHH`.
3. Ninguna colección contiene valores de datos ni literales de preguntas (test con literales marcados).
4. `search_tables` con k=30 tarda menos de 300 ms en AdventureWorks.
5. Los tests de contrato de `VectorStore` cubren `search_knowledge` y `search_golden_discovery` sobre `InMemoryVectorStore`, con y sin `embedder`.
6. La búsqueda de `ClientCode` (nombre técnico exacto) devuelve esa columna en la primera posición.
7. Sin rol `embed` en `config/models.yaml`, ninguna búsqueda llama a un modelo de embeddings (test).
