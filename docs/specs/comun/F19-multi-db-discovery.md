# F19 — Descubrimiento entre múltiples BDs: mapa del patrimonio de datos · común

> Se apoya en [F18](F18-discovery-mcp.md) (metadatos) y alimenta [F2](F02-semantic-memory.md) (memoria) y [F4](F04-schema-linking.md) (schema linking).

## Problema
Con varias BDs y servidores, los conceptos de negocio se repiten (`Cliente` en Ventas, CRM y Facturación) y las relaciones
entre BDs casi nunca están declaradas como FKs. El agente necesita saber **dónde vive cada concepto, qué copia es la buena y
cómo se cruzan las BDs** antes de escribir SQL.

## Salida: grafo del patrimonio de datos (`catalog/_estate/`)
Un grafo versionado en YAML, revisable por humanos, cargado en memoria con `networkx`:

| Nodo | Atributos |
|---|---|
| `server`, `database`, `schema`, `table`, `column` | Metadatos de F1/F18 |
| `entity` (concepto de negocio: Cliente, Producto, Pedido) | Definición, sinónimos, **tabla canónica** por BD, propietario |
| `metric` | Enlace a la capa semántica (F21) |

| Arista | Evidencia | Confianza |
|---|---|---|
| `fk_declared` | `sys.foreign_keys` | 1.0 |
| `view_join` / `proc_join` | Joins extraídos con sqlglot de vistas y SPs (`get_object_definition`) | 0.9 |
| `cross_db_reference` | `sys.sql_expression_dependencies` con BD o servidor distinto | 0.9 |
| `query_store_join` | Joins frecuentes en Query Store (`get_query_store_joins`), ponderados por frecuencia | 0.6–0.9 |
| `inferred_inclusion` | Contención de valores estimada con MinHash (columna A ⊆ columna B ≥ 0.9) + tipos compatibles + nombres similares | 0.4–0.8 |
| `same_entity` | Dos tablas de BDs distintas representan la misma entidad (por ejemplo `Ventas.dbo.Cliente` y `CRM.dbo.Customer`) | Combinación de las anteriores + LLM |

Cada arista guarda `evidence[]` y `reviewed`. Las inferidas (`confidence < 0.8`) se usan para sugerir joins, pero el planner las marca como **supuesto** en la respuesta.

## Pipeline (ejecutado por el Catalog Builder tras F1)
1. **Inventario**: servidores → BDs → objetos (F18). Detección de duplicados por nombre normalizado y estructura (huella de columnas).
2. **Relaciones declaradas**: FKs, dependencias de vistas y SPs, referencias entre BDs, sinónimos y linked servers.
3. **Relaciones observadas**: joins de Query Store (lo que la gente realmente cruza), ponderados por frecuencia y recencia.
4. **Relaciones inferidas** (solo si 2 y 3 no conectan dos dominios relevantes):
   - candidatos por nombre y tipo (`ClienteID` ↔ `CustomerId`, embeddings de nombres + reglas);
   - verificación con **sketches MinHash** calculados en memoria por F18 (estimación de contención tipo LSH Ensemble). Los sketches viven solo durante el proceso; se guarda la arista resultante y su confianza, nunca el sketch.
5. **Tipos semánticos de columna**: reglas (RFC, CURP, email, teléfono, código postal, ISO de moneda o país) + LLM sobre nombre, descripción y estadísticas (sin valores de texto). Sirven para encontrar joins y para marcar PII.
6. **Entidades de negocio**: el LLM agrupa tablas equivalentes en `entity` y propone la **tabla canónica**, priorizando: declarada por un humano → con más FKs entrantes → más usada en Query Store → más fresca (`last_user_update`).
7. **Dominios y popularidad**: clustering por grafo (comunidades) para dominios; puntuación de popularidad (Query Store + `index_usage_stats`) para el ranking del schema linking.
8. **Revisión humana**: `converdata estate review` muestra entidades, tablas canónicas y aristas inferidas pendientes.

## Uso en tiempo de pregunta
- **Router (F3)**: decide BD(s) a partir de las entidades mencionadas, no solo por similitud de texto.
- **Schema linking (F4)**: añade rutas de join del grafo (declaradas > observadas > inferidas) y prefiere la tabla canónica de cada entidad.
- **Consultas entre BDs**:

| Caso | Estrategia |
|---|---|
| Mismo servidor, varias BDs | Una sola consulta con nombres de tres partes (`[BD].[esquema].[tabla]`); el usuario necesita permisos en ambas BDs (F14) |
| Servidores distintos | **Plan federado**: una consulta validada por servidor (F7), ejecutada con el login del usuario en cada uno; el join final se hace **en memoria con DuckDB** sobre los DataFrames. Límite de filas por rama y aviso si el join intermedio es grande |
| Linked server existente | Solo si está en la lista blanca de `config/databases.yaml`; por defecto se prefiere el plan federado (más fácil de validar y auditar) |

- **Desambiguación**: si un concepto vive en varias BDs sin canónica definida, F3 pregunta "¿Clientes de Ventas o de CRM?" en lugar de elegir en silencio.

## Herramientas nuevas en `converdata-mcp` (para agentes y clientes MCP)
| Herramienta | Qué hace |
|---|---|
| `where_is(concept)` | Devuelve las entidades, BDs y tablas donde vive un concepto, con la canónica marcada, filtrado por la visibilidad del usuario |
| `estate_overview(domain?)` | Mapa de dominios, BDs y entidades principales (para preguntas "¿qué datos tenemos de…?") |
| `find_join_path(tables[])` | Ahora atraviesa BDs y servidores, con el tipo y la confianza de cada arista |

## Criterios de aceptación
1. Con dos BDs de prueba (Ventas y CRM) sin FKs entre sí, el pipeline encuentra la relación `Ventas.Cliente.ClienteID ↔ CRM.Customer.CustomerId` y la marca como `same_entity` con evidencia.
2. Un join usado con frecuencia en Query Store aparece como arista `query_store_join` sin guardar el texto de las consultas.
3. Una pregunta que necesita dos servidores se responde con un plan federado: dos consultas validadas, ejecutadas con el login del usuario, y el join en memoria.
4. Las aristas inferidas aparecen como supuestos en el `AnswerEnvelope`.
5. Ningún sketch ni valor queda persistido (prueba de literales marcados de F17).
6. En el set de evaluación con preguntas entre BDs, el router acierta la(s) BD(s) en al menos el 90 % de los casos.
