# OP-02 — Catálogo e ingesta + memoria semántica · on-premise

> Implementa en local: [F1](../comun/F01-catalog-builder.md) y [F2](../comun/F02-semantic-memory.md)

## Ingesta
| Pieza | Implementación |
|---|---|
| Disparo | **Comando manual** `converdata catalog build/refresh` (opcional: cron o tarea programada del servidor) |
| Catalog Builder | El mismo código, ejecutado dentro del contenedor `converdata-app`; LLM vía Bedrock por HTTPS |
| sql-to-mcp | **Contenedor AnythingMCP** en el mismo `docker compose`, con el login de metadatos en `.env` (fuera del repositorio) |
| Catálogo fuente | **Carpeta `catalog/`** versionada en git (solo metadatos estructurales) |
| Indexación | Al terminar `build/refresh`, el indexador valida que no haya valores y escribe en Chroma |
| Red hacia SQL Server | Directa desde la red corporativa, puerto 1433 |

## Memoria semántica: `ChromaStore`
- **ChromaDB embebida** en el proceso de `converdata-app`, persistente en el volumen `./.chroma`.
- Una colección por colección lógica de F2 (`tables`, `columns`, `glossary`, `golden_sql`). El filtro de permisos se aplica con `where={"id": {"$in": visible_ids}}`; si la lista supera los 2 000 objetos, se filtra por base de datos en Chroma y después por permisos en Python.
- Embeddings con el rol `embed` de F16 (Bedrock Cohere). Alternativa sin nube: `paraphrase-multilingual-MiniLM-L12-v2` local (requiere reindexar).

## Criterios de aceptación
1. `converdata catalog build` contra AdventureWorks deja YAML en `catalog/` y colecciones en `./.chroma`.
2. Al borrar `./.chroma`, `converdata catalog reindex` lo reconstruye desde `catalog/` sin consultar SQL Server.
3. Los tests de contrato de `VectorStore` pasan contra `ChromaStore`.
