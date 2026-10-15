# OP-02 — Catálogo, descubrimiento y memoria semántica en SQL Server · on-premise

> Implementa en on-premise Microsoft: [F1](../comun/F01-catalog-builder.md), [F2](../comun/F02-semantic-memory.md), [F18](../comun/F18-discovery-mcp.md), [F19](../comun/F19-multi-db-discovery.md) y [F21](../comun/F21-semantic-layer.md)

## BD de trabajo `ConverData` (SQL Server 2025)
Una sola BD guarda todo lo que ConverData necesita persistir, con respaldo, seguridad y alta disponibilidad gestionados por el DBA.
No hay ChromaDB, SQLite ni archivos de catálogo como almacén de trabajo.

| Esquema | Contenido | Característica de SQL Server usada |
|---|---|---|
| `catalog` | Servidores, BDs, objetos, columnas, FKs, SPs, descripciones, sinónimos, PII, `asset_key` y ambientes | **Temporal tables** (`SYSTEM_VERSIONING = ON`): historial de cada cambio de descripción y quién lo revisó |
| `catalog` (vectores) | `embedding VECTOR(1024)` por tabla, columna, entrada de glosario y plantilla golden | Tipo **`VECTOR`** (GA en SQL Server 2025) y `VECTOR_DISTANCE('cosine', …)` |
| `catalog` (texto) | Nombres, descripciones y sinónimos | **Full-Text Search** (índice de texto completo, idioma español) |
| `estate` | Entidades de negocio, tablas canónicas y relaciones entre BDs (F19) | **Tablas de grafo** (`AS NODE` / `AS EDGE`) y consultas `MATCH` / `SHORTEST_PATH` |
| `semantic` | Métricas, dimensiones y consultas verificadas (F21) | Tablas normales con validación por `CHECK` y versionado temporal |
| `golden` | Golden SQL original (con literales) y su plantilla anonimizada | Tablas normales |
| `knowledge` | Fragmentos **redactados** de documentos y diccionarios, reglas de negocio, aristas de linaje ETL, anotaciones de responsables y `golden_discovery` (plantillas), con sus vectores (F23, F24) | `VECTOR` + Full-Text; linaje como aristas `etl` en las tablas de grafo de `estate`; temporal tables para reglas y anotaciones |
| `curation` | Responsables por dominio (`owners`), solicitudes escaladas y cola de revisión (F24) | Tablas normales; las solicitudes contienen la pregunta (D2), por eso solo on-prem |
| `audit` | Modelo de F11 | Ver OP-05 |

El volumen esperado (300–3 000 tablas, decenas de miles de columnas) permite **búsqueda vectorial exacta**: no hace falta el índice
DiskANN, que sigue en preview.

## `SqlServerVectorStore` (implementa la interfaz `VectorStore` de F2)
- **Búsqueda híbrida en una sola consulta**: top-k por `VECTOR_DISTANCE` + top-k por `CONTAINSTABLE` (Full-Text), combinados con *Reciprocal Rank Fusion* en T-SQL.
- **Filtro de permisos**: `visible_ids` de la sesión (F14) se pasa como parámetro con valores de tabla (o JSON con `OPENJSON`) y se aplica en el `WHERE`, antes del ranking.
- **Embeddings**: los genera la aplicación con el rol `embed` de F16 (Cohere Embed Multilingual en Bedrock, 1024 dimensiones) y SQL Server solo los almacena y busca. No depende de `AI_GENERATE_EMBEDDINGS` (estado de GA no confirmado). Alternativa sin nube: modelo multilingüe ONNX local en el servidor de aplicación (requiere reindexar).
- La conexión de la aplicación a la BD `ConverData` usa la cuenta gMSA del servicio, con permisos solo sobre esa BD (no sobre las BDs de datos).

## Ingesta y descubrimiento
| Pieza | Implementación |
|---|---|
| Disparo | **Job de SQL Server Agent** nocturno con un paso PowerShell que llama a `POST /api/admin/catalog/refresh` (autenticado con un token de servicio) en el servidor de aplicación, donde corre el Catalog Builder; también bajo demanda desde la UI de administración. Alternativa: Programador de tareas de Windows en el servidor de aplicación |
| `converdata-discovery` (F18) | Servicio de Windows en el servidor de aplicación, escuchando solo en `localhost`; usa el login de metadatos guardado con DPAPI |
| Fuentes adicionales (F23) | Diccionarios y documentos (carpeta compartida o SharePoint), **SSISDB** y **msdb** (paquetes SSIS y jobs de SQL Agent) leídos por `converdata-discovery` |
| Redacción de PII (F23) | **Presidio** con reconocedores en español y patrones locales (DUI, NIT, cuenta, tarjeta), en el proceso de ingesta del servidor de aplicación, antes de escribir en `knowledge`; los documentos originales no se copian |
| Ingesta de conocimiento | Mismo job nocturno de SQL Server Agent (paso `POST /api/admin/knowledge/ingest`), procesando solo lo que cambió por hash |
| Grafo entre BDs (F19) | Se escribe en el esquema `estate`; los sketches MinHash solo viven en memoria durante el job |
| Revisión humana | UI de administración (descripciones, entidades, tablas canónicas, métricas); cada cambio queda en el historial temporal |
| Versionado en git | `converdata catalog export` genera YAML de `catalog`, `estate` y `semantic` para revisarlos en pull requests (opcional) |
| Consultas de perfil y sketches | Contra la **secundaria legible de Always On** si existe; si no, con `allow_primary_sampling` explícito (F18) |

## Criterios de aceptación
1. Tras `converdata catalog build` contra AdventureWorks, `catalog`, `estate` y los vectores tienen datos, y la búsqueda híbrida devuelve las tablas esperadas para 20 preguntas de prueba.
2. Al cambiar una descripción, el historial temporal permite ver la versión anterior y quién la cambió.
3. Un usuario sin acceso al esquema `RRHH` no recibe objetos de `RRHH` en la búsqueda (filtro `visible_ids`).
4. Los tests de contrato de `VectorStore` pasan contra `SqlServerVectorStore`.
5. Ninguna tabla de la BD `ConverData` fuera de `audit` y `golden` contiene valores de datos ni literales de preguntas (test de literales marcados).
6. El job de SQL Server Agent registra éxito o fallo en su historial y avisa por correo (Database Mail) si falla.
7. Un documento de prueba con un DUI y un número de cuenta queda en `knowledge` con ambos valores redactados (búsqueda del literal = 0).
8. `SqlServerVectorStore.search_knowledge` y `search_golden_discovery` pasan los tests de contrato de F2, con el filtro `visible_ids` aplicado.
