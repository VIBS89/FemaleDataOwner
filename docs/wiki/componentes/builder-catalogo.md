# Builder del catálogo

Actualizado el 2026-11-17.

## Para qué sirve
Construye y refresca el catálogo: recorre los servidores del inventario con un login de solo metadatos, convierte lo que encuentra en objetos del catálogo, deduce entidades entre BDs y el linaje de vistas, y publica el resultado en la BD `ConverData` sin pisar lo que editaron las personas. Es un comando que corre y termina; no es un servicio ni tiene API propia.

## Lo esencial
- Lee solo metadatos (`sys.*`). Nunca lee valores de las tablas ni ejecuta procedimientos.
- El flujo es `extract → enrich → relate → write` (LangGraph) en `src/converdata/flows/catalog_build.py`. `enrich` es opcional y usa el LLM.
- El caso de uso `refresh_catalog` (`src/converdata/application/catalog_refresh.py`) lo comparten la CLI y el endpoint de Administración.
- Un servidor caído no vacía su parte del catálogo: se conserva lo último conocido.
- Con la BD, publica con `scope="build"`: solo toca lo derivado de los metadatos. Una descripción `human` o `data_dictionary` ya guardada nunca se reemplaza.
- Un objeto con el mismo `schema_hash` se reutiliza tal cual y no se vuelve a enriquecer.
- Fuentes de conocimiento: están el diccionario CSV y las reglas, pero se cargan por Curación, no por el Builder. Faltan documentos y linaje de SSIS y SQL Agent.

## Responsabilidades
- Descubrir BDs de cada servidor (`databases: ["*"]` = todas las que el login ve) y extraer objetos, columnas, PK, FK, filas aproximadas, descripciones (`MS_Description`), clasificación de sensibilidad, dependencias y parámetros.
- Marcar columnas con datos personales por nombre o por clasificación de SQL Server.
- Generar sinónimos por reglas y, con LLM, descripciones marcadas `generated`.
- Detectar la misma entidad en varias BDs y el linaje tabla → vista.
- Publicar de forma incremental y dejar constancia en la auditoría.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| Flujo | `src/converdata/flows/catalog_build.py` | `build_catalog_graph` con los cuatro nodos; `BuildReport`; `OWN_DATABASES` (no se cataloga `converdata`). |
| Pasos deterministas | `src/converdata/builder/catalog_builder.py` | `to_catalog_object`, `merge_existing`, `schema_hash`, `is_pii`, `domain_of`, `rule_synonyms`, `unsafe_name`, `detect_entities`, `view_lineage`, `write_output`, `write_snapshot`. |
| Puerto de metadatos | `src/converdata/metadata/ports.py` | `MetadataSource` (`list_databases`, `extract_database`) y los DTO `RawObject`, `RawColumn`. |
| Extractor SQL Server | `src/converdata/metadata/sqlserver.py` | `SqlServerMetadata`: consultas fijas, solo lectura. |
| Caso de uso | `src/converdata/application/catalog_refresh.py` | Parte del catálogo vigente, corre el flujo y publica. |
| Ids | `src/converdata/catalog/ids.py` | `physical_id`, `asset_key_of`, `table_key`. |
| Inventario | `src/converdata/config.py` | `ServerConfig`, `Inventory`, `load_inventory`. |
| Repositorio | `src/converdata/storage/catalog_repository.py` | `publish(scope="build")` y `load(scope="build")`. Ver [BD ConverData](bd-converdata.md). |
| CLI | `src/converdata/cli.py` | `catalog build`, `catalog publish`, `catalog export`, `builder_hosts_refused`. |
| Enriquecedor | `src/converdata/llm/nodes.py` (`LlmEnricher`) | Rol `planner` del gateway. Ver la página del componente LLM. |

## Cómo funciona
1. **Inicio.** `refresh_catalog` pide al repositorio la foto vigente con `load("build")` y la escribe en un directorio de trabajo (`write_snapshot`). Así el flujo ve qué objetos ya existen. Sin repositorio (desarrollo), el directorio de trabajo es el catálogo.
2. **extract.** Por cada servidor: abre la fuente (`source_factory(server)`), lista BDs (descarta `converdata` y la BD de trabajo), y para cada BD extrae objetos. Los objetos con nombres no admitidos (`.`, `/`, `\`, `:`, caracteres de control o vacíos) se omiten y se cuentan en `skipped_unsafe`. Cada objeto se convierte (`to_catalog_object`) y se fusiona con el existente (`merge_existing`).
3. **Fallo de un servidor.** Se registra `servers_failed`, se descartan sus objetos nuevos y se restauran los últimos conocidos (`kept_from_failed`). Los demás servidores siguen.
4. **enrich.** Solo si hay enriquecedor y objetos pendientes (tablas y vistas nuevas o cambiadas). Lotes de 6 (`ENRICH_BATCH`). Solo rellena campos `generated` y vacíos; descripciones de 500 caracteres como máximo para objetos y 300 para columnas; hasta 8 sinónimos. Un error del LLM se anota en `enrich_errors` y no detiene el build.
5. **relate.** `detect_entities` y `view_lineage`. Si algún servidor falló, conserva el linaje de vistas de los objetos conservados.
6. **write.** `write_output`: elimina los YAML de objetos que ya no existen, no reescribe los idénticos, y escribe `knowledge/estate/entities.yaml`, `knowledge/lineage/views.yaml` y `config/databases.yaml` (sin `host` ni credenciales).
7. **Publicación.** Si respondió al menos un servidor, `repository.publish(load_snapshot(work_dir), published_by=..., reason="build", scope=...)`. Escribe solo lo que cambió y sube `catalog.catalog_version`. Si ningún servidor respondió, no publica.

## Qué lee y qué no (`metadata/sqlserver.py`)
Consultas fijas (constantes `Q_*`); ninguna función acepta SQL del llamador.

| Consulta | Fuente | Para qué |
|---|---|---|
| `Q_DATABASES` | `sys.databases` (`HAS_DBACCESS`, en línea, `database_id > 4`) | BDs visibles |
| `Q_OBJECTS` | `sys.objects`, `sys.schemas`, `sys.extended_properties` | Tablas, vistas y SPs de usuario y su `MS_Description` |
| `Q_COLUMNS` | `sys.columns`, `sys.types`, `sys.extended_properties` | Columnas y tipo |
| `Q_PRIMARY_KEYS`, `Q_FOREIGN_KEYS` | `sys.indexes`, `sys.index_columns`, `sys.foreign_keys` | Llaves |
| `Q_ROW_COUNTS` | `sys.partitions` | Filas aproximadas (un número, no datos) |
| `Q_SENSITIVITY` | `sys.sensitivity_classifications` | Etiqueta de sensibilidad (opcional) |
| `Q_DEPENDENCIES` | `sys.sql_expression_dependencies` | Qué lee cada vista o SP (solo del mismo servidor) |
| `Q_PARAMETERS` | `sys.parameters`, `sys.procedures` | Parámetros de SPs |

- Conexión de solo lectura (`readonly=True`), `SET LOCK_TIMEOUT 2000` y tiempo de espera de 30 s por defecto: no bloquea al servidor de datos.
- Autenticación: Windows (`Trusted_Connection=yes`) o login SQL tomado de las variables `metadata_user_env`/`metadata_password_env` del servidor; sin credenciales en logs. `Encrypt=yes`. Con `read_replica` usa `ApplicationIntent=ReadOnly`.
- Los textos de `MS_Description` los escribe el DBA: son metadatos, pero pueden contener cualquier cosa. Sin verificar que se pasen por el detector de datos personales antes de publicarse.

## Ids y entidades
- Id físico: `<ambiente>:<servidor>.<bd>.<esquema>.<objeto>` (`catalog/ids.py::physical_id`). `asset_key` lógico: `<bd>.<esquema>.<objeto>[.<columna>]`. El `asset_key` agrupa las copias entre ambientes.
- Dominio: nombre de la BD sin las palabras `banca`, `bd`, `db` (`domain_of`). Los responsables se asocian al dominio.
- Entidad entre BDs: tablas con el mismo nombre normalizado en 2 o más BDs y al menos 60 % de columnas en común (`min_overlap=0.6`). La canónica es la más referenciada por FK; luego la de más filas; luego el nombre.
- Linaje: aristas tabla → vista de un salto (`LineageVia(kind="view")`). No hay linaje de SPs, jobs ni SSIS.

## La regla de no pisar lo editado por personas
- Fusión local (`merge_existing`): si el `schema_hash` no cambió, se reutiliza el objeto anterior completo. Si cambió, se conservan descripción, fuente y `reviewed` anteriores cuando eran `human` o `data_dictionary`, o cuando eran texto no vacío frente a uno nuevo `generated`.
- Publicación (`SqlServerCatalogRepository._protect`): con `scope="build"`, si la BD ya tiene una descripción `human` o `data_dictionary`, la fila publicada conserva la de la BD aunque la foto traiga otra. Cubre la edición hecha mientras el build corría (`tests/test_catalog_repository.py::test_el_refresco_no_revierte_una_correccion_humana_hecha_durante_el_build`).
- El rol `converdata_builder` no puede leer ni escribir reglas, fragmentos, confirmaciones ni responsables.
- El texto del LLM entra como `generated` (evidencia débil) hasta que una persona lo revise.

## Publicación incremental
Escribir solo lo que cambió. Una segunda ejecución idéntica no toca filas ni sube la versión. El historial temporal guarda lo anterior con `modified_by` (`builder` o el usuario). Detalle en [BD ConverData](bd-converdata.md).

## Las dos formas de lanzarlo
| | CLI `converdata catalog build --db` | `POST /admin/catalog/build` |
|---|---|---|
| Quién | Tarea programada (pendiente, HU-37) | Un `data_admin` desde Administración |
| Credencial de metadatos | Cuenta del proceso (Windows), salvo que el servidor declare `metadata_user_env` | La credencial de la sesión del admin (`SessionVault`) |
| Inventario | El de la BD (`--config` lo sustituye por un YAML) | El de la API |
| Lista de hosts permitidos | `CONVERDATA_BUILDER_HOSTS`, solo con el inventario de la BD (obligatoria en qa y prod) | No se aplica |
| Publicado como | `builder` | El `user_id` del admin |
| Alcance | `scope="build"` | `scope="build"` (con la BD); `scope="all"` en modo demo |
| Auditoría | `catalog_build_started` y `catalog_build_finished` con usuario `builder` | Los mismos eventos con el usuario de la sesión |
| LLM | `--models config/models.yaml` | Opción `enrich`, solo si la API tiene `models_path` |
| Estado | La salida de la consola; código 0 si respondió algún servidor | `GET /admin/catalog/build` (un trabajo a la vez, en memoria del proceso) |

Comandos relacionados:
```bash
converdata catalog build --db                         # refresco programado
converdata catalog build --config config/databases.local.yaml --out data/catalog_local   # sin BD, a YAML
converdata catalog publish --root <dir> [--force]     # importación inicial
converdata catalog export --out <dir> [--with-questions]
```

## Contratos y datos
- Salida lógica: `catalog/<ambiente>/<servidor>/<bd>/<esquema>.<objeto>.yaml` más `knowledge/estate/entities.yaml`, `knowledge/lineage/views.yaml`, `config/databases.yaml`, `config/owners.yaml`. Spec: [F01](../../specs/comun/F01-catalog-builder.md), [F18](../../specs/comun/F18-discovery-mcp.md), [F19](../../specs/comun/F19-multi-db-discovery.md).
- `BuildReport`: servidores correctos y fallidos, BDs, objetos, columnas, reutilizados, enriquecidos, errores de enriquecimiento, entidades, aristas, archivos escritos, segundos, conservados y omitidos.
- Diagramas: [on-premise](../../architecture/onpremise-architecture.html) y [controles de calidad bancaria](../../architecture/controles-calidad-bancaria.html).

## Configuración
| Dónde | Qué |
|---|---|
| `config/databases.local.yaml` (por defecto de la CLI sin `--db`) | Inventario: `id`, `host`, `alias`, `environment`, `platform`, `is_reference`, `databases` (o `["*"]`), `read_replica`, `auth` (`windows` o `sql`), `metadata_user_env`, `metadata_password_env`, `trust_server_certificate`. |
| `CONVERDATA_DB` | Cadena de la BD (requerida con `--db`). |
| `CONVERDATA_BUILDER_HOSTS` | Hosts o sufijos (`.banco.local`) separados por coma. Sin puerto ni instancia al comparar. Vacía en qa o prod: el build se niega. |
| `CONVERDATA_ENV` | `qa` o `prod` activan lo anterior. |
| `config/models.yaml` | Modelo del rol `planner` para el enriquecimiento (opcional). |

## Fuentes de conocimiento ([F23](../../specs/comun/F23-knowledge-sources.md))
| Fuente | Estado | Cómo entra hoy |
|---|---|---|
| Diccionario de datos (CSV) | Hecho (HU-25) | `POST /curation/dictionary` desde Curación: `plan_dictionary` en `src/converdata/curation.py`. Columnas `asset_key` o `database,schema,table[,column]`, `description`, `synonyms` (con `;`). Entra como `data_dictionary`, no pisa `human`, respeta el dominio del responsable y rechaza datos personales. Repetir el archivo no escribe nada. |
| Reglas de negocio | Hecho (HU-28) | Curación (`PUT /curation/rules`, `source` con prefijo `steward:`) y archivos `knowledge/rules/*.yaml` por importación. |
| Fragmentos (`items`) | Solo por importación | `knowledge/items/*.yaml` con `catalog publish`. Sin pantalla ni conector. |
| Linaje de vistas | Hecho | Lo deduce el Builder. |
| Entidades entre BDs | Hecho | Lo deduce el Builder. |
| Documentos con redacción de datos personales | Falta (HU-26) | Hay un detector de seis formatos (`api/converdata_api/pii.py`) para ediciones de curación, no un conector de documentos. |
| Linaje de SSIS, SQL Agent y SPs | Falta (HU-27) | Necesita acceso a `SSISDB` y `msdb`. |
| Reglas sugeridas por el Builder | Falta | No existe. |
| Diccionario en Excel | Falta | Solo CSV. |

Medir lo que aportan: `converdata eval discovery --knowledge <dir>` (ver [evaluación y calidad](evaluacion-calidad.md)).

## Pruebas que lo cubren
- `tests/test_catalog_build.py`: de SQL Server sin catálogo al DiscoverFlow; servidor caído; fuente falsa sin valores.
- `tests/test_catalog_refresh.py`: caso de uso, CLI contra la BD y `test_el_builder_solo_va_a_los_hosts_permitidos`.
- `tests/test_catalog_repository.py`: `scope="build"`, protección de lo humano, rol `converdata_builder` (pruebas `sqlserver`).
- `tests/test_gate.py`: nombres que rompen el catálogo, no escribir fuera de `catalog/`, el build omite nombres no admitidos.
- `tests/test_curation.py`: diccionario CSV. `tests/test_graph_rag.py`: efecto de las fuentes de conocimiento.
- Extractor real: probado a mano contra SQL Server 2022 con las 5 BDs de BancosSQL (PLAN §1); no hay prueba automática de las consultas `Q_*`.

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md).
- La lista de hosts no rige para el build desde Administración: ese camino usa la credencial del admin y el host del inventario.
- El Builder programado entra con Windows, no con el login SQL del inventario, salvo `metadata_user_env`. Sin verificar contra un Windows Server real (bloque F).
- La tarea programada, la alerta de fallo y la evaluación semanal no existen todavía (HU-37, HU-18, HU-24).
- El enriquecimiento con LLM empeoró la búsqueda léxica en la medición HU-34 (82,8 % frente a 93,1 % de Hit@1) porque pesaba como texto humano; hoy cuenta como evidencia débil (×0.5). Bedrock sin probar.
- `refresh` incremental explícito, `--database`, `--no-llm` y `catalog review` no existen.
- Los objetos eliminados salen del catálogo (se borra la fila; queda en el historial). No se marcan `deprecated`.
- `low_cardinality`, `drift` y `domain` por LLM no se calculan en el Builder. La deriva entre ambientes se detecta al consultar, comparando `schema_hash` (`discovery/engine.py::drift_of`).
- Los objetos se procesan en serie, sin paralelismo.
- `detect_entities` agrupa por nombre normalizado y usa la primera copia como referencia; dos tablas del mismo nombre en una misma BD se pisan.
- Dependencias entre servidores (vinculados) no entran al linaje.

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Añadir una consulta de metadatos | `Q_*` y `extract_database` en `metadata/sqlserver.py`, el DTO en `metadata/ports.py` y la prueba con fuente falsa. |
| Soportar otra plataforma | Otro adaptador de `MetadataSource`; el flujo no cambia. |
| Cambiar qué es dato personal | `_PII_NAME` e `is_pii` en `builder/catalog_builder.py`. |
| Cambiar cómo se agrupan las entidades | `detect_entities` y `singular`. |
| Añadir linaje de otro origen | `relate` en `flows/catalog_build.py`, `LineageVia` en `models/knowledge.py` y `knowledge.lineage_edge`. |
| Cambiar qué publica el Builder | `scope="build"` en `catalog_repository.py`. |
| Limitar a qué servidores entra | `builder_hosts_refused` en `cli.py`; para el camino de la API, `AgentRuntime._run_build` en `api/converdata_api/runtime.py`. |
| Cambiar el prompt o el tamaño de lote del LLM | `ENRICH_BATCH` en `flows/catalog_build.py` y `llm/nodes.py`. |
| Cargar otro tipo de conocimiento | `knowledge/<tipo>/*.yaml` y `load_knowledge` en `catalog/store.py`; para un conector, el puerto aún no existe. |
