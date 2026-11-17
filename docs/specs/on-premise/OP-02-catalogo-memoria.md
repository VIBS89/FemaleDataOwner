# OP-02 — Catálogo, descubrimiento y memoria de búsqueda · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Implementa en on-premise Microsoft: [F1](../comun/F01-catalog-builder.md), [F2](../comun/F02-semantic-memory.md), [F18](../comun/F18-discovery-mcp.md), [F19](../comun/F19-multi-db-discovery.md) y, en la fase 1b, [F21](../comun/F21-semantic-layer.md)

## BD de trabajo `ConverData` (SQL Server 2016 o posterior)
Una sola BD guarda todo lo que ConverData necesita persistir, con respaldo, seguridad y alta disponibilidad gestionados por el DBA.
Usa **solo tablas normales** (PRD §13, decisión 10): no hay columnas de vectores, índices de texto completo ni tablas de grafo, así que
basta una versión con tablas temporales (SQL Server 2016 o posterior).

| Esquema | Contenido | Característica de SQL Server usada |
|---|---|---|
| `catalog` | Servidores, BDs, objetos, columnas, FKs, SPs, descripciones, sinónimos, PII, `asset_key`, ambientes y la versión publicada (`catalog_version`) | **Temporal tables** (`SYSTEM_VERSIONING = ON`): historial de cada cambio de descripción y quién lo hizo (`modified_by`) |
| `knowledge` | Fragmentos **redactados** de documentos y diccionarios, reglas de negocio, aristas de linaje ETL, entidades de negocio entre BDs (F19) y `golden_discovery` (preguntas confirmadas) (F23, F24) | Tablas normales; temporal tables para fragmentos y reglas |
| `golden` | `golden_discovery_original`: reservada para el original de cada pregunta confirmada cuando la plantilla se anonimice (hoy sin uso) | Tablas normales |
| `curation` | Responsables de negocio y técnico por dominio (`owners`). Pendientes (migración `002`): responsables de curación por login, solicitudes escaladas, votos y directorio de usuarios (`user_directory`: login SQL → cuenta de AD, F14, HU-13) | Tablas normales; las solicitudes contienen la pregunta (D2), por eso solo on-prem |
| `audit` | Modelo de F11 | Ver OP-05 |
| `semantic` (fase 1b) | Métricas, dimensiones y consultas verificadas (F21) | Tablas normales con validación por `CHECK` y versionado temporal |

No existe el esquema `estate`: las entidades, las FKs y las aristas de linaje son filas de tablas normales, y el grafo del patrimonio
(F19) se **construye en memoria** al cargar.

**Estado (2026-11-16).** Construido y probado contra un SQL Server real (2022 Express; las pruebas se activan con `CONVERDATA_TEST_DB`):
- **Migraciones** (`db/converdata/001_esquemas.sql`, `converdata db migrate`, OP-07): esquemas `catalog`, `knowledge`, `golden`,
  `curation` y `audit`, y los roles `converdata_app`, `converdata_builder`, `converdata_auditor` y `converdata_maintenance`.
- **Catálogo y conocimiento en la BD** (`converdata.storage.catalog_repository`): servidores, objetos, columnas y FKs; fragmentos,
  reglas, linaje, entidades, confirmaciones (`golden_discovery`) y responsables por dominio (`curation.owners`). Publicar escribe solo
  lo que cambió, sube `catalog.catalog_version` y deja la versión anterior en el historial temporal con `modified_by`.
- **La API arranca desde la BD** cuando `CONVERDATA_DB` está definida (obligatoria en qa y prod): `CONVERDATA_DATA_ROOT` pasa a ser una
  copia de trabajo que se reconstruye desde la BD, cada edición de curación se publica antes de recargar y, si otro proceso publicó
  entre tanto, la edición se rechaza con 409 para repetirla sobre la versión vigente.
- **Auditoría** en el esquema `audit` (OP-05).

Sigue en archivos del servidor, pendiente de pasar a la BD: responsables por login (`curation/stewards.yaml`), solicitudes escaladas
(`curation/requests.json`), votos (`curation/feedback.jsonl`), el registro de diccionarios ya aplicados y el inventario de servidores
de la API (`inventory.yaml`); además, los ajustes del descubrimiento (`config/settings.yaml`) son un archivo de configuración. No se
usa todavía `golden.golden_discovery_original`, y `curation.user_directory` no existe (HU-13).

**Confirmaciones y datos personales.** `knowledge.golden_discovery.template` es hoy la pregunta normalizada (minúsculas, sin tildes
ni puntuación), **no** una plantilla anonimizada: es D2. Por eso el Builder no puede leerla (rol `converdata_builder`), no se exporta
con `catalog export` (salvo `--with-questions`) y la API no guarda como confirmación una pregunta que parezca llevar datos personales
(DUI, NIT, correo, teléfono, tarjeta). Anonimizarla con marcadores y guardar el original en `golden` sigue pendiente, y mientras
tanto el criterio 5 no se cumple para esa tabla.
Sin `CONVERDATA_DB` (desarrollo) todo vive en archivos: YAML bajo `CONVERDATA_DATA_ROOT` y JSONL con cadena de hashes en `data/audit/`.

## Búsqueda léxica en memoria (implementa la interfaz `VectorStore` de F2)
Decisión (PRD §13, decisión 9): **BM25 en memoria como único canal de la fase 1a**.
- **Motivo**: en la medición HU-34 (2026-10-29) el canal léxico solo dio Hit@1 93,1 % y Hit@3 93,1 %; añadir embeddings `bge-m3` no
  cambió ningún caso y subió el p95 de 73 ms a 4,6 s.
- **Cómo funciona**: `ConverData-API` carga el catálogo y el conocimiento al arrancar en un índice léxico en memoria
  (`InMemoryVectorStore`, `src/converdata/memory/memory_store.py`) y lo recarga tras cada build, cada confirmación y cada cambio de curación.
- **Filtro de permisos**: `visible_ids` de la sesión (F14) se aplica **antes** del ranking; no hay búsqueda sin filtro.
- **Sin modelo de embeddings**: `config/models.yaml` no declara el rol `embed` en qa ni en piloto (F16).
- El puerto `VectorStore` de F2 se conserva. El canal de embeddings queda como **opción experimental de desarrollo**
  (`--embeddings-only`, `config/models.embed.yaml`) y no se despliega.
- **`SqlServerVectorStore` se retira**: la búsqueda no se hace en SQL Server.
- Cuando el catálogo viva en la BD, la API lo leerá con la cuenta gMSA del proceso, con permisos solo sobre la BD `ConverData`
  (no sobre las BDs de datos).

## Ingesta y descubrimiento
| Pieza | Implementación |
|---|---|
| Catalog Builder | **Comando `converdata catalog build`**: corre y termina, con su gMSA (rol `converdata_builder`). No es un servicio ni tiene API propia (PRD §13, decisión 12). Extrae, enriquece, escribe el catálogo y sirve también de refresco. Un refresco solo toca lo que deriva de los metadatos: no pisa descripciones `human` ni `data_dictionary`, no toca reglas, confirmaciones ni responsables, no cataloga la propia BD `ConverData` y, si un servidor no responde, conserva lo último conocido de ese servidor |
| Disparo | **Programador de tareas de Windows**, cada noche, con `converdata catalog build --db` (la tarea está pendiente, HU-37): parte del catálogo publicado, publica el resultado y la API lo carga sin reiniciar (comprueba la versión cada 15 s). Bajo demanda desde Administración: `POST /admin/catalog/build` (rol `data_admin`), que hoy ejecuta el mismo flujo en un hilo de `ConverData-API` con la credencial de la sesión del administrador |
| `converdata-discovery` (F18) | Biblioteca dentro del comando; usa el login de metadatos guardado con DPAPI (hoy se lee de variables de entorno; la carga desde DPAPI es parte de HU-37) |
| Fuentes adicionales (F23) | Construido: diccionario de datos en CSV (HU-25, también desde Curación con `POST /curation/dictionary`) y reglas. Pendiente: documentos de la carpeta compartida (SMB) o SharePoint con una cuenta técnica de solo lectura (HU-26), y **SSISDB** y **msdb** (paquetes SSIS y jobs de SQL Server) leídos con `converdata-discovery` (HU-27) |
| Redacción de PII (F23) | Construido: detector de cinco patrones (`api/converdata_api/pii.py`) sobre las ediciones de curación. Pendiente: **Presidio** con reconocedores en español y patrones locales (DUI, NIT, cuenta, tarjeta), en memoria dentro del Builder y antes de escribir en `knowledge`; los documentos originales no se copian (HU-26) |
| Ingesta de conocimiento | En la misma ejecución nocturna, procesando solo lo que cambió por hash |
| Grafo entre BDs (F19) | Entidades (`knowledge.business_entity`) y linaje (`knowledge.lineage_edge`) en tablas normales; el grafo se arma en memoria al cargar (`src/converdata/graph/estate.py`). Los sketches MinHash solo viven en memoria durante la ejecución |
| Revisión humana | Vista Curación de la web (descripciones, reglas, diccionario) y Administración; cada cambio queda auditado y, con la BD, en el historial temporal |
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

Estado de los criterios (2026-11-16): 2 se cumple (`tests/test_catalog_repository.py`, `api/tests/test_catalog_db.py`); 3 y 8, con la suite
`permisos` de `converdata eval gate`, también con el catálogo cargado de la BD (`eval gate --db`); 4 se cumple en la forma "el
descubrimiento responde igual desde la BD que desde YAML" sobre los dos catálogos de prueba; 5 está cubierto para `catalog` y
`knowledge` en cuanto a columnas de valores, pero no para `knowledge.golden_discovery` (ver arriba) y falta la prueba de literales
marcados de punta a punta; 1 usa BancosSQL en vez de
AdventureWorks; 6 depende de HU-37 y 7 de HU-26.
