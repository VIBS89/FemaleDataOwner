# BD DiscoveryDataAgent

Actualizado el 2026-11-17.

## Para qué sirve
SQL Server (2016 o posterior) donde DiscoveryDataAgent guarda todo lo que debe persistir: catálogo, conocimiento, curación, confirmaciones y auditoría. Es la fuente de verdad; el índice de búsqueda se reconstruye en la memoria de `DiscoveryDataAgent-API` a partir de ella. Solo tablas normales y temporales: sin vectores, texto completo ni grafos. Nunca guarda valores de datos de los servidores catalogados.

Diagrama del modelo: [modelo de datos de DiscoveryDataAgent](../../architecture/modelo-datos-discovery-data-agent.html) (lo mantiene otra persona; sin verificar que ya exista). Spec: [OP-02](../../specs/on-premise/OP-02-catalogo-memoria.md), [OP-05](../../specs/on-premise/OP-05-auditoria-observabilidad.md), [OP-07](../../specs/on-premise/OP-07-instalacion-operacion.md).

## Lo esencial
- Dos migraciones: `db/discovery_data_agent/001_esquemas.sql` y `db/discovery_data_agent/002_curacion.sql`. Se aplican con `discovery-data-agent db migrate`.
- Cinco esquemas (`catalog`, `knowledge`, `curation`, `golden`, `audit`) más `dbo.schema_version`.
- Seis tablas son temporales (historial y autor en `modified_by`): objetos, columnas, inventario, fragmentos, reglas y responsables.
- Cuatro roles de base de datos de mínimo privilegio. Los scripts no crean logins ni usuarios: el DBA añade la cuenta de cada proceso al rol.
- La cuenta de la API puede insertar y leer en `audit`, pero no modificar, borrar ni purgar.
- Sin `DISCOVERY_DATA_AGENT_DB` todo pasa a archivos (`discovery-data-agent/storage/files.py`), solo para desarrollo, pruebas y demo.

## Responsabilidades
- Guardar el catálogo con historial por fila y autor.
- Guardar lo que escriben las personas (descripciones, reglas, confirmaciones, responsables) separado de lo que deduce el Builder.
- Guardar la auditoría de forma que quien la escribe no pueda alterarla (fail-closed).
- Separar las preguntas de los usuarios (dato D2) en tablas que el Builder no lee y que la purga alcanza.
- Versionar el esquema con migraciones comprobadas por hash.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| DDL inicial | `db/discovery_data_agent/001_esquemas.sql` | Esquemas, tablas, procedimiento de purga y los cuatro roles. |
| DDL de curación | `db/discovery_data_agent/002_curacion.sql` | Inventario, responsables, dudas escaladas, votos; amplía la purga; añade DENY. |
| Migraciones | `src/discovery_data_agent/storage/migrations.py` | Descubre, valida y aplica scripts; `require_current` al arrancar la API. |
| Conexión | `src/discovery_data_agent/storage/connection.py` | Lee `DISCOVERY_DATA_AGENT_DB`, elige el driver ODBC 18 o 17, abre conexiones (`APP=DiscoveryDataAgent`). |
| Catálogo | `src/discovery_data_agent/storage/catalog_repository.py` | `SqlServerCatalogRepository`: publicar, cargar, escrituras de curación, inventario, historial. |
| Curación | `src/discovery_data_agent/storage/curation_repository.py` | `SqlServerCurationRepository`: responsables, dudas escaladas, votos. |
| Auditoría | `src/discovery_data_agent/audit/sqlserver.py` | `SqlServerAuditSink`: escribe y lee `audit`; `verify()` comprueba permisos. |
| Archivos | `src/discovery_data_agent/storage/files.py` | Los mismos puertos sobre YAML/JSON, sin BD. |
| Selección | `src/discovery_data_agent/bootstrap.py` (`open_stores`) | Con `DISCOVERY_DATA_AGENT_DB` usa SQL Server y exige migraciones al día; sin ella, archivos. |

## Tablas por esquema
"Escribe" es quien las escribe en el código actual. T = tabla temporal (su historial va en `<esquema>.<tabla>_history`).

### `catalog`
| Tabla | Para qué sirve | Escribe |
|---|---|---|
| `catalog.server` | Inventario sin hosts que acompaña al catálogo (alias, ambiente, plataforma, `config_json`). | Builder y API al publicar |
| `catalog.object` (T) | Una fila por copia física (`physical_id` = `<amb>:<srv>.<bd>.<esq>.<obj>`); `asset_key` lógico, tipo, descripción y su fuente, dominio, sinónimos, PK, parámetros, `schema_hash`. | Builder; la API solo las descripciones |
| `catalog.[column]` (T) | Columnas con tipo, nulabilidad, descripción, sinónimos, `low_cardinality`, `pii`. | Builder; la API solo las descripciones |
| `catalog.foreign_key` | FKs por objeto (`ref_asset` a nivel de `asset_key`). | Builder |
| `catalog.catalog_version` | Una fila por cambio: versión, quién, motivo (`build`, `curation`, `dictionary`, `feedback`, `import`). La API recarga su índice cuando sube. | Builder y API |
| `catalog.inventory_server` (T) | Inventario con `host`, que la API usa para conectarse. | Solo la API |

### `knowledge`
| Tabla | Para qué sirve | Escribe |
|---|---|---|
| `knowledge.item` (T) | Fragmentos redactados (glosario, regla, documento, anotación, etl, diccionario). | Solo importación (`catalog publish`, publicación `scope="all"`); ningún endpoint los edita. |
| `knowledge.business_rule` (T) | Reglas de negocio con dominio y activos a los que aplican. | API (curación) e importación |
| `knowledge.lineage_edge` | Aristas de linaje a nivel de tabla (hoy las de vistas). | Builder (se reemplazan completas si cambian) |
| `knowledge.business_entity` | Entidades entre BDs y sus tablas, con la canónica. | Builder |
| `knowledge.golden_discovery` | Confirmaciones: plantilla anónima de la pregunta, activos, recuento, quién confirmó. | API e importación |

### `curation`
| Tabla | Para qué sirve | Escribe |
|---|---|---|
| `curation.owners` | Responsables de negocio y técnico por dominio (patrones de `asset_key`). | Solo importación; sin endpoint de edición |
| `curation.steward` (T) | Responsables por login y los dominios que curan. Da un rol. | API (`PUT /admin/stewards`) |
| `curation.request` | Dudas escaladas al responsable, con la pregunta (D2), lo mostrado y la respuesta. Única por `(trace_id, user_id)`. | API |
| `curation.vote` | Votos de confirmar o rechazar, sin texto libre. De aquí sale el recuento. | API |

### `golden`
| Tabla | Para qué sirve | Escribe |
|---|---|---|
| `golden.golden_discovery_original` | Texto original de una confirmación (D2), solo la primera vez y solo si no traía literales. | API |

### `audit`
| Tabla | Para qué sirve | Escribe |
|---|---|---|
| `audit.audit_question` | Una fila por pregunta: usuario, cliente, flujo, texto, intención, estado, confianza, duración. | API |
| `audit.audit_step` | Pasos del flujo por pregunta (nodo, intento, duración, modelo, error). | API |
| `audit.audit_discovery` | Candidatos, alternativas y relaciones mostradas. | API |
| `audit.audit_discovery_feedback` | Veredictos sobre candidatos (`confirm`, `reject`, `correct_is`) y rol del actor. | API |
| `audit.audit_event` | Eventos que no son preguntas: sesiones, accesos denegados, cambios, lecturas de auditoría, builds. `data_json` sin contraseñas ni tokens. | API; CLI y Builder (solo inserción) |
| `audit.usp_purge` | Procedimiento de purga por retención (ver abajo). | Lo ejecuta `discovery_data_agent_maintenance` |

### `dbo`
`dbo.schema_version`: versión, nombre, SHA-256 del script, fecha y quién lo aplicó. La crea `discovery-data-agent db migrate` la primera vez.

## Tablas temporales: historial y autor
- `catalog.object`, `catalog.[column]`, `catalog.inventory_server`, `knowledge.item`, `knowledge.business_rule` y `curation.steward` usan `SYSTEM_VERSIONING`. Cada una tiene `modified_by`, `valid_from` y `valid_to` (ocultas).
- `catalog.object_history`, `catalog.column_history`, `catalog.inventory_server_history`, `knowledge.item_history`, `knowledge.business_rule_history` y `curation.steward_history` guardan cada versión anterior.
- `SqlServerCatalogRepository.description_history` lee `FOR SYSTEM_TIME ALL`, funde las versiones que no cambian la descripción y devuelve quién la escribió. Lo usa `GET /curation/history`.
- Los roles de aplicación tienen `DENY ALTER` sobre `catalog`, `knowledge` y `curation`: sin `ALTER` no pueden apagar el versionado para reescribir el historial.
- No son temporales: `catalog.server`, `catalog.foreign_key`, `catalog.catalog_version`, `knowledge.lineage_edge`, `knowledge.business_entity`, `knowledge.golden_discovery`, `curation.owners`, `curation.request`, `curation.vote` y todo `golden` y `audit`.

## Roles y permisos reales
Los cuatro son roles de base de datos (`CREATE ROLE`). Permisos tal como están en los scripts.

| Rol | GRANT | DENY |
|---|---|---|
| `discovery_data_agent_app` (API) | `SELECT, INSERT, UPDATE, DELETE` sobre los esquemas `catalog`, `knowledge`, `golden`, `curation`; `SELECT, INSERT` sobre `audit`. | `UPDATE, DELETE, ALTER` sobre el esquema `audit`; `EXECUTE` sobre `audit.usp_purge`; `ALTER` sobre `catalog`, `knowledge` y `curation`; `UPDATE, DELETE` sobre `catalog.catalog_version`, `curation.vote` y `golden.golden_discovery_original`. |
| `discovery_data_agent_builder` (tarea programada) | `SELECT, INSERT, UPDATE, DELETE` sobre el esquema `catalog`, `knowledge.business_entity` y `knowledge.lineage_edge`; `INSERT` sobre `audit.audit_event`. | `SELECT, INSERT, UPDATE, DELETE` sobre `knowledge.golden_discovery`, `knowledge.item`, `knowledge.business_rule`, los esquemas `golden` y `curation`; `SELECT, UPDATE, DELETE` sobre `audit`; `ALTER` sobre `catalog` y `knowledge`; `UPDATE, DELETE` sobre `catalog.catalog_version`; `INSERT, UPDATE, DELETE` sobre `catalog.inventory_server` (lo lee, no lo cambia). |
| `discovery_data_agent_auditor` | `SELECT` sobre el esquema `audit`. | Ninguno. |
| `discovery_data_agent_maintenance` | `EXECUTE` sobre `audit.usp_purge`. | Ninguno. |

Notas:
- El builder no lee preguntas ni confirmaciones: `knowledge.golden_discovery`, `curation` y `golden` le están negados.
- `SqlServerAuditSink.verify()` (y `discovery-data-agent audit verify --db`) consulta `HAS_PERMS_BY_NAME` y falla si la cuenta del servicio puede `UPDATE`, `DELETE` o `ALTER` en `audit` (esquema o tabla), ejecutar `audit.usp_purge` o `ALTER` en `catalog`, `knowledge` o `curation`. No revisa `golden` ni `dbo`.
- La API lo comprueba al arrancar en qa y prod (`docs/PLAN-desarrollo.md` §5).

## Purga: `audit.usp_purge`
- `WITH EXECUTE AS OWNER`: quien la ejecuta no necesita `DELETE` en `audit`.
- Parámetro `@keep_days` (por defecto 180). Si es nulo o menor de 180, lanza el error 51000.
- Borra, en una transacción, lo anterior al corte: feedback, candidatos, pasos y preguntas de auditoría; eventos (salvo los `audit_purged`); y, desde 002, `curation.request` y `golden.golden_discovery_original`.
- Los votos y las plantillas (`knowledge.golden_discovery`) no se purgan: no llevan texto libre.
- Deja un `audit_event` de tipo `audit_purged` con los recuentos y el login original.
- La lanza `discovery-data-agent audit purge --keep-days N` (rol `discovery_data_agent_maintenance`). No está programada todavía (HU-37).

## Migraciones
1. `discovery-data-agent db migrate` abre conexión con `DISCOVERY_DATA_AGENT_DB` (`db_connect` en `src/discovery_data_agent/cli.py`) y llama a `migrate`.
2. `discover` lista `db/discovery_data_agent/NNN_<descripcion>.sql` (regex `^(\d{3})_([a-z0-9_]+)\.sql$`). Exige numeración 001, 002, … sin huecos ni repetidos.
3. `pending` compara con `dbo.schema_version`. Si un script ya aplicado cambió (SHA-256 distinto, insensible al fin de línea), falla: los cambios van en un script nuevo. Si la BD tiene versiones que el código no conoce, también falla.
4. `migrate` parte cada script por líneas `GO`, lo ejecuta entero en una transacción junto con la fila de `dbo.schema_version`. Si algo falla, revierte y no queda nada de ese script.
5. `--status` solo muestra lo pendiente; `--dir` cambia la carpeta.
6. `REQUIRED_VERSION = 2` en `migrations.py`. `require_current` (llamada desde `open_stores`) impide arrancar la API si la BD va atrás. Una prueba mantiene esa constante al día.

## Adaptadores
- **`SqlServerCatalogRepository`**: `publish` deja las tablas iguales a la foto escribiendo solo lo que cambió, bajo `sp_getapplock 'discovery_data_agent_catalog'` (exclusivo al escribir, compartido al leer), con `expected_version` opcional (`StaleCatalog`). `scope="build"` toca solo lo derivado (servidores, objetos, columnas, FKs, entidades, linaje) y conserva descripciones `human` o `data_dictionary` ya presentes. `scope="all"` iguala todo. Las escrituras de curación (`write_descriptions`, `upsert_rule`, `delete_rule`, `upsert_golden`) son filas concretas, cada una en su transacción, y suben la versión.
- **`SqlServerCurationRepository`**: responsables, dudas escaladas (inserta una vez por `(trace_id, user_id)`) y votos (bloqueo por `golden_id`; el último voto de cada usuario gana).
- **`SqlServerAuditSink`**: una pregunta con sus pasos y candidatos se escribe en una sola transacción; si falla, relanza y el flujo no entrega la respuesta. Los eventos se escriben antes de aplicar el cambio.
- **`connection.py`**: `connector(conn_str, timeout_s=5)`; `with_driver`; `names_database` (las pruebas exigen una cadena de servidor, sin `DATABASE`); `describe` (servidor/BD sin credenciales).
- **Modo archivos** (`storage/files.py`): `FileKnowledgeWriter` edita `catalog/*.yaml` y `knowledge/rules/curadas.yaml`; `FileCurationRepository` usa `stewards.yaml`, `requests.json` y `feedback.jsonl`; `FileInventoryStore` usa `inventory.yaml`. En qa y prod la API exige `DISCOVERY_DATA_AGENT_DB`. Sin BD, `GET /curation/history` responde `available: false`.

## Cómo funciona un refresco o una edición
1. El proceso abre una conexión y toma el bloqueo de aplicación.
2. Lee la versión vigente; si declaró `expected_version` y no coincide, aborta.
3. Compara fila a fila (`_Table.sync`): borra lo que sobra, inserta lo nuevo, actualiza lo que difiere. Hijos antes que padres al borrar, y al revés al insertar (sin `ON DELETE CASCADE`).
4. Si cambió algo, inserta en `catalog.catalog_version` y confirma.
5. La API ve la versión nueva y recarga su índice en memoria.

## Contratos y datos
- Todo valor estructurado va como JSON en columnas `*_json` con `CHECK (ISJSON(...) = 1)`.
- `template` de `knowledge.golden_discovery` es una plantilla anónima desde 002. El comentario de 001 dice lo contrario (la pregunta normalizada); 001 no se edita porque ya está aplicada.
- El modelo `CatalogObject` rechaza campos de valores antes de llegar aquí (`tests/test_catalog_repository.py::test_el_catalogo_de_la_bd_no_contiene_valores_de_datos`).

## Configuración
| Variable | Efecto |
|---|---|
| `DISCOVERY_DATA_AGENT_DB` | Cadena ODBC de la BD. En el servidor, `Trusted_Connection=yes` con la cuenta del proceso. Sin ella, modo archivos. |
| `DISCOVERY_DATA_AGENT_ENV` | `qa` o `prod`: la API exige la BD y comprobaciones de seguridad (`api/discovery_data_agent_api/settings.py`). |
| `DISCOVERY_DATA_AGENT_TEST_DB` | Solo pruebas: cadena de servidor, sin `DATABASE`; crean y eliminan `DiscoveryDataAgent_test_<aleatorio>`. |

## Pruebas que lo cubren
Las marcadas `sqlserver` se omiten sin `DISCOVERY_DATA_AGENT_TEST_DB` y **no corren en la CI** (no tiene SQL Server).
- `tests/test_storage_migrations.py`: migraciones, hash, `require_current` (parte con una base falsa).
- `tests/test_catalog_repository.py`: publicar, cargar, historial, roles `discovery_data_agent_app` y `discovery_data_agent_builder`, purga, votos.
- `tests/test_audit_sqlserver.py` y `api/tests/test_audit_db.py`: auditoría y fail-closed.
- `tests/test_curation.py`, `tests/test_catalog_refresh.py`, `api/tests/test_catalog_db.py`: curación, CLI y API contra la BD.
- `api/tests/test_marked_literals.py`: ningún literal de pregunta fuera de `audit` y `curation.request`.
- Fixtures y BD desechable: `conftest.py` (raíz).

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md).
- El DDL se probó en SQL Server 2022, no en 2016.
- Ningún GRANT cubre `dbo.schema_version`. `require_current` la lee con la cuenta de la API. Ninguna prueba ejecuta `require_current` con un usuario que solo pertenezca a `discovery_data_agent_app` (`acting_as` en `tests/test_catalog_repository.py` no lo llama). Sin verificar si una cuenta real lo lee por otra vía.
- La purga no está programada; la alerta de fallo de auditoría tampoco (HU-37).
- `ts` de la auditoría puede venir del que inserta (`COALESCE(?, SYSUTCDATETIME())`); el plan lo anota como deuda.
- Nada escribe `knowledge.item` ni `curation.owners` salvo la importación; no hay pantalla ni comando para editarlos.
- `catalog.catalog_version.reason` no tiene `CHECK`: los valores del comentario son convención.
- `deprecated` y `drift_json` existen en `catalog.object` pero el Builder no los llena.
- Sin respaldo ni restauración probados (bloque F).

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Añadir una tabla o columna | Un script nuevo `db/discovery_data_agent/003_*.sql`, `REQUIRED_VERSION` en `migrations.py` y el repositorio que la use. Nunca edites 001 o 002. |
| Cambiar un permiso de un rol | Script nuevo con `GRANT`/`DENY`; actualiza `VERIFY_PERMISSIONS` en `audit/sqlserver.py` si afecta a `audit`. |
| Cambiar la retención | `audit.usp_purge` (script nuevo con `ALTER PROCEDURE`); el mínimo de 180 días viene de OP-05. |
| Qué publica el Builder | `scope="build"` en `SqlServerCatalogRepository.publish` y `_sync_catalog`/`_sync_derived`. |
| Qué es "humano" y no se pisa | `PROTECTED_SOURCES` en `catalog_repository.py` y `_PROTECTED_SOURCES` en `builder/catalog_builder.py`. |
| Qué se audita | `audit/sqlserver.py` y `audit/recorder.py`. |
| El modo desarrollo sin BD | `storage/files.py` y `open_stores` en `bootstrap.py`. |
