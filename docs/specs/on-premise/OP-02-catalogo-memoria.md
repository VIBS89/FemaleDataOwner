# OP-02 — Catálogo, descubrimiento y memoria de búsqueda · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Estado actualizado el 2026-11-17 (curación e inventario en la BD).
>
> Implementa en on-premise Microsoft: [F1](../comun/F01-catalog-builder.md), [F2](../comun/F02-semantic-memory.md), [F18](../comun/F18-discovery-mcp.md), [F19](../comun/F19-multi-db-discovery.md) y, en la fase 1b, [F21](../comun/F21-semantic-layer.md)

## BD de trabajo `ConverData` (SQL Server 2016 o posterior)
Una sola BD guarda todo lo que ConverData necesita persistir, con respaldo, seguridad y alta disponibilidad gestionados por el DBA.
Usa **solo tablas normales** (PRD §13, decisión 10): no hay columnas de vectores, índices de texto completo ni tablas de grafo, así que
basta una versión con tablas temporales (SQL Server 2016 o posterior).

| Esquema | Contenido | Característica de SQL Server usada |
|---|---|---|
| `catalog` | Servidores, BDs, objetos, columnas, FKs, SPs, descripciones, sinónimos, PII, `asset_key`, ambientes y la versión publicada (`catalog_version`). `inventory_server`: el inventario de servidores que usa la API para conectarse, con `host` (`catalog.server` es la copia sin hosts que acompaña al catálogo); el rol del Builder solo lo lee | **Temporal tables** (`SYSTEM_VERSIONING = ON`): historial de cada cambio de descripción y quién lo hizo (`modified_by`); también `inventory_server` es temporal |
| `knowledge` | Fragmentos **redactados** de documentos y diccionarios, reglas de negocio, aristas de linaje ETL, entidades de negocio entre BDs (F19) y `golden_discovery` (preguntas confirmadas) (F23, F24) | Tablas normales; temporal tables para fragmentos y reglas |
| `golden` | `golden_discovery_original`: el texto original de cada pregunta confirmada (D2), solo si la pregunta no traía ningún literal ni parece llevar datos personales; se guarda la primera vez, nunca entra al índice, la API no puede cambiarlo ni borrarlo y la purga de retención lo alcanza | Tablas normales |
| `curation` | Responsables de negocio y técnico por dominio (`owners`); responsables de curación por login (`steward`), dudas escaladas (`request`) y votos (`vote`, sin texto libre; la API no puede cambiarlos ni borrarlos). Pendiente: directorio de usuarios (`user_directory`: login SQL → cuenta de AD, F14, HU-13) | Tablas normales; `steward` es temporal (da un rol). Las dudas escaladas contienen la pregunta (D2), por eso solo on-prem y con purga por retención (OP-05) |
| `audit` | Modelo de F11 | Ver OP-05 |
| `semantic` (fase 1b) | Métricas, dimensiones y consultas verificadas (F21) | Tablas normales con validación por `CHECK` y versionado temporal |

No existe el esquema `estate`: las entidades, las FKs y las aristas de linaje son filas de tablas normales, y el grafo del patrimonio
(F19) se **construye en memoria** al cargar.

**Estado (2026-11-17).** Construido y probado contra un SQL Server real (2022 Express; las pruebas se activan con `CONVERDATA_TEST_DB`):
- **Migraciones** (`converdata db migrate`, OP-07). `db/converdata/001_esquemas.sql`: esquemas `catalog`, `knowledge`, `golden`,
  `curation` y `audit`, y los roles `converdata_app`, `converdata_builder`, `converdata_auditor` y `converdata_maintenance`.
  `db/converdata/002_curacion.sql`: `catalog.inventory_server`, `curation.steward`, `curation.request` y `curation.vote`; amplía
  `audit.usp_purge` a las dudas escaladas y a los originales de las confirmaciones; niega a `converdata_app` alterar el esquema
  `curation` (no puede reescribir el historial de responsables) y cambiar o borrar votos y originales, y a `converdata_builder`
  escribir en el inventario. Con `CONVERDATA_DB`, la API no arranca si falta alguna migración (`require_current`).
- **Catálogo y conocimiento en la BD** (`converdata.storage.catalog_repository`): servidores, objetos, columnas y FKs; fragmentos,
  reglas, linaje, entidades, confirmaciones (`golden_discovery`) y responsables por dominio (`curation.owners`). Publicar escribe solo
  lo que cambió, sube `catalog.catalog_version` y deja la versión anterior en el historial temporal con `modified_by`.
- **La API no guarda estado en disco** cuando `CONVERDATA_DB` está definida (obligatoria en qa y prod): carga el catálogo y el
  conocimiento de la BD en memoria, sin copia de trabajo en `CONVERDATA_DATA_ROOT`, y los vuelve a cargar cuando otro proceso publica.
  El inventario, los responsables, las dudas escaladas y los votos se leen y se escriben en la BD
  (`converdata.storage.curation_repository`; el inventario, por el puerto `InventoryStore`). No hay registro de diccionarios
  aplicados: repetir un diccionario no escribe nada porque no queda nada que cambiar. El build bajo demanda corre en un directorio temporal que se borra al terminar.
- **La curación escribe filas concretas**, no publica el catálogo: una descripción, una regla o una confirmación son una escritura
  atómica que deja su autor y sube la versión (puerto `KnowledgeWriter` de `converdata.curation`: `write_descriptions`, `upsert_rule`,
  `delete_rule`, `upsert_golden`). Ya no hay rechazo 409 por catálogo desactualizado en la API; la versión esperada se conserva al
  publicar (`publish(..., expected_version=)`). Decisión (2026-11-17): `catalog.catalog_version` significa "algo cambió", no
  "publicación"; la suben cada edición de curación y cada voto aprendido.
- **Recarga fail-closed**: si el catálogo vigente no se puede cargar, la API queda sin catálogo (responde 409) en vez de seguir
  sirviendo el anterior, que podría incluir una regla o una confirmación recién retirada; tras una edición, quien editó recibe el
  error aunque lo escrito ya sea firme.
- **Historial de descripciones** a la vista: `GET /curation/history?asset_key=` lo lee del historial temporal (OP-04). Cada
  entrada es un cambio real de la descripción con quien lo hizo: las versiones de fila que no la cambian (un refresco que solo
  actualiza el número de filas) se funden con la anterior.
- **Auditoría** en el esquema `audit` (OP-05).

Siguen siendo archivos de configuración, no estado: los ajustes del descubrimiento (`config/settings.yaml`, que la API lee de
`CONVERDATA_DATA_ROOT/config/`) y `config/models.yaml`. `curation.user_directory` no existe (HU-13).

**Confirmaciones y datos personales.** `knowledge.golden_discovery.template` es una **plantilla anónima**
(`converdata.curation.question_template`): la pregunta normalizada (minúsculas, sin tildes ni puntuación) y sin literales.
Regla (`converdata.memory.text.strip_literals(question, known)`, endurecida tras la revisión de seguridad del 2026-11-17; ya no
hay lista de formatos): tras normalizar con NFKC (los dígitos en superíndice, de ancho completo o en círculo cuentan como dígitos),
**toda palabra con algún dígito o con arroba es un literal**, salvo que sea vocabulario conocido del banco: un nombre del catálogo
con dígitos (`Catalog.names_with_digits`, p. ej. `Ultimos4`) o un código del conocimiento con letras y dígitos
(`KnowledgeBase.codes`, p. ej. `NCB-022`, `BR-ONB-004`). El vocabulario de la plantilla es el del catálogo entero más los códigos
del conocimiento (`AgentRuntime._vocabulary`); el descubrimiento usa la misma función con el vocabulario de lo que el usuario ve
(F22). `T24` o `F14` salen de la plantilla si no son nombres del catálogo ni códigos del glosario (antes se conservaban), y
`NCB-022` se conserva solo si el glosario del banco lo nombra. Dos preguntas que solo difieren en el literal son la misma
confirmación; también las que solo difieren en un código que el banco no tiene en su glosario. Decisión (2026-11-17): se quitan
todos los números, también los umbrales de negocio; "mora mayor a 90 días" y
"mora mayor a 30 días" son la misma confirmación.
- Si tras quitar los literales la pregunta aún parece llevar datos personales (detector de cinco patrones), el voto cuenta y se audita,
  pero no se guarda como confirmación.
- El texto original va a `golden.golden_discovery_original` solo si la pregunta no traía ningún literal (`has_literals`) ni parece
  llevar datos personales; en otro caso queda únicamente en la auditoría. Los dos tienen la misma retención (OP-05).
- **Limitación**: la plantilla no detecta nombres de personas, texto entre comillas ni los trozos solo de letras de un código
  partido por espacios (un IBAN escrito con espacios deja sus grupos de letras). Por eso se mantienen las otras barreras: el
  Builder no puede leer la tabla (rol `converdata_builder`) y no se exporta con `catalog export` (salvo `--with-questions`).

Sin `CONVERDATA_DB` (desarrollo y modo demo) todo vive en archivos (`converdata.storage.files`): YAML bajo `CONVERDATA_DATA_ROOT`,
`inventory.yaml`, el directorio de curación (`stewards.yaml`, `requests.json`, `feedback.jsonl`) y JSONL con
cadena de hashes en `data/audit/`.

## Búsqueda léxica en memoria (implementa la interfaz `VectorStore` de F2)
Decisión (PRD §13, decisión 9): **BM25 en memoria como único canal de la fase 1a**.
- **Motivo**: en la medición HU-34 (2026-10-29, set de 31 casos) el canal léxico solo dio Hit@1 93,1 % y Hit@3 93,1 %; añadir embeddings `bge-m3` no
  cambió ningún caso y subió el p95 de 73 ms a 4,6 s.
- **Cómo funciona**: `ConverData-API` carga el catálogo y el conocimiento al arrancar en un índice léxico en memoria
  (`InMemoryVectorStore`, `src/converdata/memory/memory_store.py`) y lo recarga tras cada build, cada confirmación y cada cambio de curación.
- **Filtro de permisos**: `visible_ids` de la sesión (F14) se aplica **antes** del ranking; no hay búsqueda sin filtro.
- **Sin modelo de embeddings**: el rol `embed` ya no existe (F16). Un `config/models.yaml` que lo declare se carga ignorándolo con
  un aviso, y en qa y prod la API se niega a arrancar.
- El puerto `VectorStore` de F2 se conserva. El canal de embeddings con el que se hizo la medición se retiró del código el 2026-11-17
  (ya no existen `--embeddings-only` ni `config/models.embed.yaml`): la medición de HU-34 queda como historia.
- **`SqlServerVectorStore` se retira**: la búsqueda no se hace en SQL Server.
- La API lee el catálogo de la BD con la cuenta del proceso (la gMSA en el servidor), con permisos solo sobre la BD `ConverData`
  (no sobre las BDs de datos).

## Ingesta y descubrimiento
| Pieza | Implementación |
|---|---|
| Catalog Builder | **Comando `converdata catalog build`**: corre y termina, con su gMSA (rol `converdata_builder`). No es un servicio ni tiene API propia (PRD §13, decisión 12). Extrae, enriquece, escribe el catálogo y sirve también de refresco. Un refresco solo toca lo que deriva de los metadatos: no pisa descripciones `human` ni `data_dictionary` (la descripción humana de la BD gana siempre, también frente a otra versión humana que el Builder leyó al empezar), no toca reglas, confirmaciones ni responsables, no cataloga la propia BD `ConverData` y, si un servidor no responde, conserva lo último conocido de ese servidor |
| Disparo | **Programador de tareas de Windows**, cada noche, con `converdata catalog build --db` (la tarea está pendiente, HU-37): parte del catálogo publicado, publica el resultado y la API lo carga sin reiniciar (comprueba la versión cada 15 s). Sin `--config` toma el inventario de la BD (`catalog.inventory_server`, el que administra la API) y entra a cada servidor con la cuenta del proceso (`auth: windows`) aunque el inventario diga login SQL, salvo que el servidor declare `metadata_user_env` (decisión del 2026-11-17: el inventario guarda cómo entran los usuarios, no el Builder). Solo se conecta a los hosts de `CONVERDATA_BUILDER_HOSTS` (hosts o sufijos, separados por coma; obligatoria en qa y prod). Sin `--out` trabaja en un directorio temporal. Bajo demanda desde Administración: `POST /admin/catalog/build` (rol `data_admin`), en un hilo de `ConverData-API` con la credencial de la sesión del administrador. Los dos usan el mismo caso de uso (`converdata.application.catalog_refresh.refresh_catalog`) |
| `converdata-discovery` (F18) | Biblioteca dentro del comando; entra con la cuenta del proceso o, si el servidor declara `metadata_user_env`, con el login de metadatos guardado con DPAPI (hoy se lee de variables de entorno; la carga desde DPAPI es parte de HU-37) |
| Fuentes adicionales (F23) | Construido: diccionario de datos en CSV (HU-25, también desde Curación con `POST /curation/dictionary`) y reglas. Pendiente: documentos de la carpeta compartida (SMB) o SharePoint con una cuenta técnica de solo lectura (HU-26), y **SSISDB** y **msdb** (paquetes SSIS y jobs de SQL Server) leídos con `converdata-discovery` (HU-27) |
| Redacción de PII (F23) | Construido: detector de cinco patrones (`api/converdata_api/pii.py`) sobre las ediciones de curación. Pendiente: **Presidio** con reconocedores en español y patrones locales (DUI, NIT, cuenta, tarjeta), en memoria dentro del Builder y antes de escribir en `knowledge`; los documentos originales no se copian (HU-26) |
| Ingesta de conocimiento | En la misma ejecución nocturna, procesando solo lo que cambió por hash |
| Grafo entre BDs (F19) | Entidades (`knowledge.business_entity`) y linaje (`knowledge.lineage_edge`) en tablas normales; el grafo se arma en memoria al cargar (`src/converdata/graph/estate.py`). Los sketches MinHash solo viven en memoria durante la ejecución |
| Revisión humana | Vista Curación de la web (descripciones con su historial, reglas, diccionario) y Administración (inventario y responsables); cada cambio queda auditado y, con la BD, en el historial temporal |
| Versionado en git | Opcional: `converdata catalog export --out <dir>` genera el YAML del catálogo publicado para revisarlo en pull requests; `converdata catalog publish --root <dir>` lo importa |
| Consultas de perfil y sketches | Contra la **secundaria legible de Always On** si existe; si no, con `allow_primary_sampling` explícito (F18) |

## Criterios de aceptación
1. Tras `converdata catalog build` contra AdventureWorks, el catálogo y las relaciones entre BDs tienen datos, y la búsqueda léxica devuelve las tablas esperadas para 20 preguntas de prueba.
2. Al cambiar una descripción, el historial temporal permite ver la versión anterior y quién la cambió.
3. Un usuario sin acceso al esquema `RRHH` no recibe objetos de `RRHH` en la búsqueda (filtro `visible_ids`).
4. Los tests de contrato de `VectorStore` pasan contra `InMemoryVectorStore` con el catálogo cargado desde la BD `ConverData`.
5. Ninguna tabla de la BD `ConverData` fuera de `audit`, `golden` y `curation` (solicitudes escaladas) contiene valores de datos ni literales de preguntas (test de literales marcados).
6. La tarea programada del build registra éxito o fallo en su historial, y si falla deja un error en el Visor de eventos (origen `ConverData`) que el monitoreo existente convierte en alerta (OP-05).
7. Un documento de prueba con un DUI y un número de cuenta queda en `knowledge` con ambos valores redactados (búsqueda del literal = 0).
8. `search_knowledge` y `search_golden_discovery` de `InMemoryVectorStore` pasan los tests de contrato de F2, con el filtro `visible_ids` aplicado.

Estado de los criterios (2026-11-17): 2 se cumple y el historial se ve en la vista Curación (`tests/test_catalog_repository.py`,
`api/tests/test_catalog_db.py`); 3 y 8, con la suite `permisos` de `converdata eval gate`, también con el catálogo cargado de la BD
(`eval gate --db`, repetido el 2026-11-17 con el set de 58 casos de BancosSQL: 0 fugas en 737 preguntas × usuario y 4 309 llamadas); 4 se cumple en la forma "el descubrimiento responde igual desde la BD que desde YAML" sobre los dos catálogos de
prueba; 5 se cumple desde la segunda tanda del 2026-11-17 con `api/tests/test_marked_literals.py`: tras 100 preguntas con 100
literales distintos en 10 formas (también en `history`), votadas y en parte escaladas y respondidas, busca el literal, también
transformado (minúsculas, NFKC, recortado a los 6 caracteres del stemmer), en toda columna de toda tabla que no sea número, fecha,
bit o `uniqueidentifier`, convertida a texto (historial incluido), y solo lo encuentra en `audit.audit_question.question`, `curation.request.question` y `curation.request.note`
(necesita `CONVERDATA_TEST_DB`, así que no corre en la CI), con la limitación de los nombres de personas descrita arriba; 1 usa
BancosSQL en vez de AdventureWorks; 6 depende de HU-37 y 7 de HU-26.
