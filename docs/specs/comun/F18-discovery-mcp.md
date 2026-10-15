# F18 — `converdata-discovery`: MCP propio de descubrimiento (Apache-2.0) · común

> Sustituye a sql-to-mcp / AnythingMCP (AGPL-3.0). Es código propio bajo **Apache-2.0**, sin dependencias copyleft.
> Despliegue (igual en ambos entornos): **biblioteca dentro del Catalog Builder** → tarea ECS en **cloud native** ([CN-02](../cloud-native/CN-02-catalogo-memoria.md)) ·
> servicio de Windows `ConverData-Builder` en **on-premise** ([OP-02](../on-premise/OP-02-catalogo-memoria.md)). El transporte MCP es opcional (herramientas de administración en red privada).

## Por qué un MCP propio
| Motivo | Detalle |
|---|---|
| Licencia | AnythingMCP es AGPL-3.0: obliga a publicar el código si se ofrece como servicio en red. El MCP propio es Apache-2.0 (permisivo, con concesión de patentes) |
| Profundidad de metadatos | sql-to-mcp solo expone `list_tables`, `describe_table` y `find_columns`. El descubrimiento entre BDs (F19) necesita FKs, dependencias, Query Store, uso de índices, estadísticas, clasificación de sensibilidad, sinónimos y linked servers |
| Multi-servidor | Varias instancias SQL Server y varias BDs en un mismo inventario |
| Garantías de solo lectura | Todas las consultas son fijas y parametrizadas; la herramienta no acepta SQL libre |
| Residencia de datos | Devuelve metadatos (D3) y, opcionalmente, *sketches* calculados en memoria que nunca se persisten fuera de la red (F17, F19) |

## Diseño
- **Python + FastMCP + pyodbc** (ODBC Driver 18), en el mismo repositorio y con la misma licencia que el resto del proyecto.
- **Separación de privilegios**: corre con el **login de metadatos** (nunca con logins de usuarios) y solo lo consumen el Catalog Builder (F1, F23) y el pipeline de descubrimiento (F19). No responde preguntas de usuarios; eso es `converdata-mcp`, que usa el login de cada usuario (F14).
- **Sin SQL libre**: cada herramienta ejecuta consultas predefinidas sobre vistas de catálogo y DMVs, parametrizadas. No existe una herramienta tipo `query`.
- **Modo por defecto: biblioteca Python** que el Catalog Builder importa en su proceso, de modo que el login de metadatos solo existe ahí.
  Opcionalmente se publica por MCP *streamable HTTP* en una red privada (o `localhost`), con autenticación por token de servicio y sin
  `get_sample_rows`.
- Inventario declarativo en `config/databases.yaml`:
  ```yaml
  servers:
    - id: SRV01
      host: sql01.corp.local
      metadata_secret: converdata/metadata/SRV01   # Secrets Manager (CN) o DPAPI con ámbito de la cuenta de servicio (OP)
      databases: [Ventas, Inventario, RRHH]
      read_replica: sql01-ro.corp.local            # opcional, para muestras y sketches
      query_store: true
  ```

## Herramientas MCP
| Herramienta | Firma | Fuente en SQL Server | Devuelve |
|---|---|---|---|
| `list_servers` | `()` | configuración | Servidores, BDs, versión y edición (`SERVERPROPERTY`) |
| `list_databases` | `(server)` | `sys.databases` | BDs, estado, compatibilidad, Query Store activo, CDC/temporal |
| `list_objects` | `(server, db, kinds=[table,view,proc,synonym])` | `sys.objects`, `sys.schemas`, `sys.synonyms` | Objetos con esquema, tipo, fechas de creación y modificación |
| `describe_table` | `(server, db, schema, table)` | `sys.columns`, `sys.types`, `sys.indexes`, `sys.index_columns`, `sys.extended_properties` | Columnas, tipos, nulabilidad, PK/UK, índices, `MS_Description` |
| `get_foreign_keys` | `(server, db)` | `sys.foreign_keys`, `sys.foreign_key_columns` | FKs declaradas |
| `get_dependencies` | `(server, db, object?)` | `sys.sql_expression_dependencies` (incluye referencias **entre BDs y servidores**), `sys.dm_sql_referenced_entities` | Qué tablas usan vistas y SPs, incluidas referencias `[OtraBD].[dbo].[T]` |
| `get_object_definition` | `(server, db, schema, name)` | `OBJECT_DEFINITION` / `sys.sql_modules` | Texto de vistas y SPs (para extraer joins con sqlglot en F19) |
| `get_procedure_signature` | `(server, db, schema, proc)` | `sys.parameters` | Parámetros, tipos y valores por defecto |
| `get_table_stats` | `(server, db)` | `sys.dm_db_partition_stats`, `sys.dm_db_index_usage_stats` | Filas aproximadas, tamaño, lecturas, última escritura (frescura) |
| `get_query_store_joins` | `(server, db, days=30, top=500)` | `sys.query_store_query_text` + `sys.query_store_runtime_stats` | **Joins y filtros más usados**, extraídos del texto de las consultas con sqlglot, devueltos como pares de columnas y frecuencia. **El texto y los literales no salen de la herramienta** |
| `get_column_profile` | `(server, db, schema, table, column)` | `sys.stats`, `sys.dm_db_stats_properties`; `COUNT`/`COUNT DISTINCT` aproximado (`APPROX_COUNT_DISTINCT`) | Cardinalidad estimada, % nulos, min/max **solo para tipos numéricos y fechas**. Sin valores de texto |
| `get_column_sketch` | `(server, db, schema, table, column, k=128)` | `SELECT TOP (N) DISTINCT` sobre la réplica, procesado en memoria | **MinHash** (k firmas) de los valores, con hashes salados con una clave local. Solo para inferir relaciones (F19); nunca se persiste fuera de la red |
| `get_sensitivity` | `(server, db)` | `sys.sensitivity_classifications` | Clasificación de sensibilidad declarada (PII, confidencial) |
| `get_linked_servers` | `(server)` | `sys.servers` | Linked servers disponibles (solo informativo) |
| `get_sample_rows` | `(server, db, schema, table, top=5)` | `SELECT TOP (n)` sobre la réplica | Filas de muestra **solo en modo biblioteca** (no se publica por MCP/HTTP), sin columnas `pii` ni sensibles. Las usa el Catalog Builder para generar descripciones (F1) y se descartan |
| `list_ssis_packages` | `(server)` | `SSISDB.catalog.folders`, `projects`, `packages` | Carpetas, proyectos y paquetes SSIS (F23) |
| `get_ssis_package` | `(server, folder, project, package)` | `SSISDB.catalog.get_project` (XML `.dtsx`) | Orígenes, destinos y SQL embebido **sin literales** (F23) |
| `list_agent_jobs` | `(server)` | `msdb.dbo.sysjobs`, `sysjobsteps`, `sysschedules` | Jobs, pasos (paquete o SP que ejecutan) y frecuencia (F23) |

Todas las herramientas devuelven JSON con un `schema_version`, y paginan con `cursor` cuando hay más de 500 elementos.

## Seguridad
- Login de metadatos con `VIEW DEFINITION`, `VIEW DATABASE STATE` (para DMVs y Query Store), `SELECT` solo sobre la réplica para muestras
  y sketches, `READ` sobre las carpetas y proyectos de SSISDB y `SQLAgentReaderRole` en msdb. **Sin escritura.**
- Timeouts por consulta (30 s), concurrencia limitada por servidor (2) y `SET LOCK_TIMEOUT 2000` para no bloquear.
- Las consultas de perfil y sketch van **solo contra la réplica** si está configurada; si no, solo con permiso explícito (`allow_primary_sampling: true`).
- Columnas con `pii: true` (F1) o con clasificación de sensibilidad: sin perfil de valores ni sketch.
- Sal de los hashes MinHash: clave local rotada por entorno, guardada en Secrets Manager (CN) o con DPAPI (OP). Sin la sal, los sketches no permiten ataques de diccionario.

## Criterios de aceptación
1. `pip-licenses` del paquete no lista ninguna dependencia GPL/AGPL.
2. Contra AdventureWorks, las herramientas devuelven las mismas tablas, columnas y FKs que `sys.*` (test de paridad).
3. `get_dependencies` detecta una vista que referencia una tabla de otra BD (`[OtraBD].[dbo].[T]`).
4. `get_query_store_joins` devuelve pares de columnas sin ningún literal del texto de las consultas (test con literales marcados).
5. Ninguna herramienta acepta SQL libre (test: no existe herramienta con parámetro `sql`).
6. El login de metadatos no puede ejecutar `INSERT`/`UPDATE`/`DELETE` (test de permisos).
7. `get_sample_rows` no aparece en la lista de herramientas del transporte MCP/HTTP (solo se importa como biblioteca).
