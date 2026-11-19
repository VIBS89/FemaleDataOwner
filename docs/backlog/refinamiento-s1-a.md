# Refinamiento del goal S1-A · Persistencia y adaptadores en SD-1

> 2026-10-27. Refina el primer goal de [sesiones-goals.md](sesiones-goals.md) (**S1-A**, situación SD-1: sin SQL Server, sin AWS, sin servidor).
> Historias: HU-04 completa; la parte de HU-06 y HU-09 que no necesita SQL Server (puerto `CatalogStore` y selección de adaptadores).
> Specs: [OP-09](../specs/on-premise/OP-09-situaciones-desarrollo.md), [OP-02](../specs/on-premise/OP-02-catalogo-memoria.md), [F19](../specs/comun/F19-multi-db-discovery.md), [F21](../specs/comun/F21-semantic-layer.md), [capas del backend](../architecture/capas-backend.md).
> Método: se contrastó el goal con el código del repo en `main` (`bc91d91`). Lo marcado **⚠️** es una decisión propuesta que hay que confirmar.

## 1. Qué cambia respecto al goal original
| # | Hallazgo en el repo | Ajuste |
|---|---|---|
| 1 | HU-04 exige también el rol `auditor` (solo `SELECT` en `audit`) y el rol de `ConverData-Builder` con escritura en `catalog`, `estate` y `knowledge`. El goal solo nombraba `converdata_builder` | Se añade `auditor` y se precisan los permisos de ambos roles |
| 2 | `DENY UPDATE, DELETE ON SCHEMA::audit TO converdata_app` **ya existe** en `001_esquemas.sql` | El CA pasa a ser "no se pierde" (test estático), no "se crea" |
| 3 | Sin servidor no se puede ejecutar T-SQL: "tiene los esquemas…" no es verificable tal cual | Se verifica con un test estático que lee los `.sql`; la validez real del T-SQL queda explícitamente para S1-B (SD-3) |
| 4 | Una marca de pytest **no omite nada por sí sola**. `tests/test_sqlserver_store.py` hoy usa fakes y no lleva marca | Hace falta un `conftest.py` que omita por entorno con motivo (`pytest.skip`), más un test centinela |
| 5 | Las variables `CONVERDATA_*` hoy se leen dispersas: `api/converdata_api/settings.py` (de S2), `llm/factory.py` (`CONVERDATA_ENV`). OP-09 dice que `bootstrap.py` es el único | S1 no toca `settings.py`: `bootstrap` expone una función pura que recibe un `Mapping` (testable sin tocar `os.environ`) y S2 la consume después |
| 6 | `CONVERDATA_ENV=qa` debe prohibir también `CONVERDATA_DEMO=1`, Ollama/NIM y `audit.fail_open: true` (OP-09 CA3). El goal solo probaba `STORE=files` | Se amplía; la cookie sin `Secure` queda fuera (vive en la API, de S2) |
| 7 | `catalog/store.py` mezcla el modelo `Catalog` con la carga YAML (deuda anotada en capas-backend.md). `catalog` es capa **dominio**: un adaptador de archivos no puede vivir ahí sin registrarse aparte | El adaptador va en `catalog/files.py`, registrado en `LAYERS` como infraestructura (mismo precedente que `converdata.audit.sqlserver`); el puerto en `catalog/ports.py` |
| 8 | "Tests de contrato parametrizados por adaptador" con un solo adaptador es una parametrización vacía | La fixture de adaptadores ya declara `sqlserver` y lo omite con motivo; en S1-B solo se des-omite |
| 9 | El historial (`history(asset_key)`) lo necesita HU-06, no S1-A | **No** entra al puerto ahora: se evita código muerto; llega en S1-B con el adaptador SQL |
| 10 | No hay `.venv` en el equipo y el Python del sistema (3.14) no tiene `pytest` | Paso 0 de preparación; sin línea base verde no se empieza |

## 2. Preparación (paso 0, antes del primer test)
1. Worktree fuera de OneDrive: `git worktree add ../FemaleDataOwner-s1 -b sesion/1-persistencia`.
2. `python -m venv .venv` (Python ≥ 3.12) y `.venv/Scripts/python -m pip install -e ".[dev,api,sqlserver]"`.
3. Registrar la **línea base**: salida de `.venv/Scripts/python -m pytest -q` (el README habla de 81 tests; el número real es el que cuenta) y `tests/test_architecture.py` en verde. Si la base no está en verde, la sesión se detiene y lo reporta.

## 3. Entregables en rebanadas (cada una: un ciclo de `tdd-ciclo` y un commit)
### A1 · Marcas y omisión explícita (SD-1 base)
- `pyproject.toml`: marcas `llm_local`, `sqlserver`, `bedrock`, `windows_server` (con `--strict-markers`).
- `tests/conftest.py`: `pytest_collection_modifyitems` omite según OP-09 (§Tests por situación): `sqlserver` sin `CONVERDATA_TEST_DB`, `llm_local` sin `OLLAMA_HOST` ni `NVIDIA_API_KEY`, `bedrock` sin credenciales AWS ni proveedor `bedrock` en `CONVERDATA_MODELS`, `windows_server` fuera de Windows Server con IIS. El motivo nombra la variable que falta.
- Verificación: `pytest -q -rs` muestra cada test omitido con su motivo; un test centinela marcado `sqlserver` lo demuestra.

### A2 · Puerto `CatalogStore` y adaptador de archivos
- `catalog/ports.py` (dominio): `CatalogStore` (`Protocol`) con `load_catalog(inventory) -> Catalog`, `load_knowledge() -> KnowledgeBase`, `load_existing() -> dict[id, CatalogObject]` (para fusionar un refresco sin pisar ediciones humanas, F24-CA3) y `save_catalog(...) -> int` con la misma firma de `builder.catalog_builder.write_output`. Sin historial (ver hallazgo 9).
- `catalog/files.py` (infraestructura): `FileCatalogStore(root)` mueve aquí la carga YAML de `store.py`; `Catalog` y `KnowledgeBase` se quedan en el dominio. Se actualizan todos los llamadores (sin alias de compatibilidad) y `LAYERS` + `capas-backend.md` (se retira el ítem de deuda).
- `tests/test_catalog_store_contract.py`: batería parametrizada por adaptador `[files, sqlserver(omitido)]`: round-trip `save → load`, una edición `human` sobrevive a un refresco, ids de objetos inexistentes responden vacío, YAML inválido falla con la ruta del archivo (conducta actual de `load_catalog`), y ningún valor de datos se escribe (literal marcado).
- Verificación: el round-trip sobre `tests/fixtures/bancos` devuelve un `Catalog` idéntico al de antes del cambio (test de caracterización escrito **antes** de mover el código).

### A3 · Selección de adaptadores y guarda de entorno
- `bootstrap.py`: `AdapterConfig.from_env(environ: Mapping[str, str])` (pura) con `CONVERDATA_STORE` (`files`|`sqlserver`, por defecto `files`), `CONVERDATA_AUDIT` (por defecto igual que STORE), `CONVERDATA_DB`, `CONVERDATA_MODELS`, `CONVERDATA_ENV` (`dev`|`qa`|`prod`, por defecto `dev`). `build_service(root, ...)` conserva su firma (los tests actuales no cambian) y acepta un `CatalogStore` opcional.
- Errores: una sola excepción `ConfiguracionInvalida(ValueError)` cuyo mensaje **nombra la variable** y el valor aceptado.
- Reglas (una prueba por regla):
  | Condición | Resultado |
  |---|---|
  | `STORE`/`AUDIT` con valor desconocido | falla, nombra la variable |
  | Algún adaptador `sqlserver` sin `CONVERDATA_DB` | falla, nombra `CONVERDATA_DB` |
  | `CONVERDATA_DB` con `PWD=` o `Password=` | falla; la contraseña solo puede venir de `CONVERDATA_DB_PASSWORD` |
  | `ENV` ∈ {qa, prod} con `STORE=files` o `AUDIT=files` | falla, nombra la variable |
  | `ENV` ∈ {qa, prod} con `CONVERDATA_DEMO=1` | falla |
  | `ENV` ∈ {qa, prod} con un `models.yaml` que declara proveedor `ollama` o `nvidia_nim` | falla |
  | `ENV` ∈ {qa, prod} con `audit.fail_open: true` en `settings.yaml` | falla |
  | `ENV=dev` con todo en archivos | arranca como hoy |
- ⚠️ `STORE=sqlserver` para el **catálogo** aún no tiene adaptador (llega en S1-B): hasta entonces falla con "adaptador no disponible: CONVERDATA_STORE=sqlserver" en vez de degradar en silencio. `AUDIT=sqlserver` sí se resuelve con `SqlServerAuditSink` existente (probado con el fake de `tests/fakes.py`).
- Fuera de alcance: cookie sin `Secure` (S2) y mover `settings.py` a esta función (S2 la consumirá).

### A4 · DDL (HU-04) sin ejecutarlo
Se **añaden** scripts, no se reescribe `001_esquemas.sql` (ya puede estar aplicado en algún entorno):
| Script | Contenido |
|---|---|
| `002_estate.sql` | Esquema `estate`. Nodos `AS NODE`: `entity`, `table_ref` (una por copia canónica/no canónica de tabla), y **una** tabla de aristas `estate.relation AS EDGE` con el tipo en `kind` (`same_entity`, `fk_declared`, `view_join`, `proc_join`, `cross_db_reference`, `query_store_join`, `inferred_inclusion`, `etl`), para que `MATCH` filtre por tipo y `SHORTEST_PATH` los atraviese todos. Las tablas de grafo no admiten `SYSTEM_VERSIONING`: la revisión humana queda en `reviewed_by`/`updated_at`. Cada arista: `confidence` (`CHECK` 0–1), `evidence` (JSON), `reviewed`. **Sin columnas de sketch MinHash** (OP-02, HU-07) |
| `003_semantic.sql` | Esquema `semantic` (F21): `entity`, `dimension`, `measure`, `metric` (con `certified`, `owner`, `procedure`), `verified_query`; temporales (`SYSTEM_VERSIONING = ON`); `CHECK` en `type`/`grains`. Sin literales de datos |
| `004_roles_y_version.sql` | `dbo.schema_version(script, applied_at, checksum)`; rol `converdata_builder` (escritura en `catalog`, `estate`, `knowledge`; sin acceso a `audit`); rol `auditor` (`SELECT` en `audit`, nada más) |
- ⚠️ Los nombres de tablas y columnas de `estate` y `semantic` son una **propuesta** derivada de F19/F21 y de los modelos `BusinessEntity`/`LineageEdge`; las specs no fijan el DDL. Requieren revisión de la DBA antes de S1-B.
- `tests/test_ddl.py` (estático, lee los `.sql`): scripts con numeración contigua `NNN_nombre.sql`; separa lotes por `GO`; existen `AS NODE`/`AS EDGE`, `schema_version`, ambos roles; `converdata_app` mantiene el `DENY UPDATE, DELETE` sobre `audit`; `auditor` no tiene `INSERT`, `UPDATE`, `DELETE` ni `EXECUTE`; `converdata_builder` no tiene nada sobre `audit`; ninguna sentencia contiene `PASSWORD`/`PWD=`; `estate` no define columnas `minhash`/`sketch`.
- Límite honesto: estos tests prueban la **forma**, no que SQL Server acepte el T-SQL. Eso es el CA de S1-B.

### A5 · Cierre
- Suite completa sin fallos, `tests/test_architecture.py` en verde, `git diff --stat main...HEAD` solo con archivos de S1.
- Subagentes: `revisor-arquitectura-specs` (siempre) y `revisor-seguridad-datos` (roles, credenciales, guarda de entorno).
- Documentación viva: estado de HU-04/06/09 en `on-premise.md` ("parcial: SD-1"), `PLAN-desarrollo.md` (conteo de tests), `capas-backend.md` (deuda saldada, `LAYERS`).

## 4. Dueños y límites
Puede modificar: `db/`, `src/converdata/catalog/`, `src/converdata/memory/`, `src/converdata/graph/` (solo persistencia), `bootstrap.py`, `config.py`, `pyproject.toml` (marcas), `tests/conftest.py`, tests nuevos de estas áreas, `docs/architecture/capas-backend.md`, estado de sus HU.
No puede tocar: `api/converdata_api/`, `src/converdata/identity/`, `audit/`, `discovery/`, `flows/`, `llm/`, `web/`. Si un llamador de `load_catalog` vive allí (p. ej. `api/converdata_api/runtime.py` usa `build_service`), el cambio de firma debe ser **compatible** y se avisa a esa sesión.

## 5. Goal refinado (para pegar con `/goal`)
```
/goal En la rama sesion/1-persistencia, partiendo de una línea base verde que muestras (`python -m pytest -q` y tests/test_architecture.py): (1) pyproject.toml registra las marcas llm_local, sqlserver, bedrock y windows_server con --strict-markers y tests/conftest.py las omite según OP-09 con el motivo; muestras `pytest -q -rs` con un test centinela sqlserver "skipped" que nombra CONVERDATA_TEST_DB; (2) existe catalog/ports.py con CatalogStore (load_catalog, load_knowledge, save_catalog; sin historial) y catalog/files.py con FileCatalogStore registrado en LAYERS como infraestructura; un test de caracterización escrito antes del cambio prueba que el catálogo cargado de tests/fixtures/bancos es idéntico, y la batería tests/test_catalog_store_contract.py (round-trip, edición human sobrevive al refresco, YAML inválido nombra el archivo, sin valores de datos) pasa con el adaptador files y marca el adaptador sqlserver como omitido con motivo; (3) bootstrap.AdapterConfig.from_env(mapping) aplica la tabla de reglas de docs/backlog/refinamiento-s1-a.md §A3 con una prueba por regla y ConfiguracionInvalida nombra la variable; build_service conserva su firma; (4) db/converdata/ añade 002_estate.sql (NODE/EDGE sin sketches), 003_semantic.sql (temporales) y 004_roles_y_version.sql (dbo.schema_version, converdata_builder, auditor), y tests/test_ddl.py pasa comprobando forma, permisos de los roles, el DENY de converdata_app sobre audit y que no hay contraseñas; (5) muestras `python -m pytest -q` sin fallos y con un total de tests mayor que la línea base, `git diff --stat main...HEAD` solo con archivos de S1, y la salida de los subagentes revisor-arquitectura-specs y revisor-seguridad-datos sin hallazgos altos abiertos; (6) capas-backend.md ya no lista catalog.store como deuda y el estado de HU-04/06/09 refleja "parcial: SD-1". O detente tras 45 turnos y explica qué falta.
```

## 6. Decisiones pendientes (⚠️)
1. **DDL de `estate` y `semantic`**: columnas propuestas; confirmar con la DBA (nombres, `NODE` por copia o por tabla lógica).
2. **`STORE=sqlserver` del catálogo** falla explícitamente hasta S1-B (propuesto) frente a caer en `files` con aviso.
3. **Historial en el puerto**: se difiere a S1-B (propuesto) frente a declararlo ya.
4. **Línea base de tests**: el número exacto sale del paso 0, no del README.

## 7. Resultado (2026-10-27)
Hecho en SD-1 en cuatro commits (marcas, puerto, selección de adaptadores, DDL) con 262 tests en verde y 7 omitidos con motivo.
Cambios sobre lo planeado, tras la revisión de los subagentes:
- `build_service(..., catalog_store=...)` (no `store`, que choca con el almacén vectorial de `DiscoverDeps`).
- `CONVERDATA_ENV=local` se acepta como alias de `dev` (F16 lo usa para Ollama); `from_env(..., require_env=True)` obliga a declarar el entorno en los puntos de entrada de servicio.
- En qa/prod `settings` es obligatorio (para comprobar `audit.fail_open`), solo se permite `bedrock` (lista de permitidos), se rechaza `CONVERDATA_DB_PASSWORD` y la contraseña entra a la cadena ODBC entre llaves.
- `estate.relation` es una sola tabla de aristas con `kind`.
Pendiente y de otras sesiones: conectar `AdapterConfig` al arranque de la API (S2), adaptador `sqlserver` del catálogo (S1-B), validar el T-SQL en SQL Server 2025 y la revisión de la DBA.
Observación fuera del alcance: `audit/sqlserver.py` inserta `audit_step.detail`, columna que `001_esquemas.sql` no define (tiene `prompt_tokens` y `completion_tokens`); fallaría contra SQL Server real. Para S3 antes de SD-3.
