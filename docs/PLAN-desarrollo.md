# Plan de desarrollo — estado y cómo retomar

> Última actualización: 2026-11-16. Documento vivo: se actualiza al cerrar cada sesión de trabajo.
> Specs: [PRD](PRD.md) (decisiones vigentes en §13), [comun/](specs/comun/), [on-premise/](specs/on-premise/). Uso diario: [README](../README.md#desarrollo).
> Backlog con el estado de cada historia: [backlog/on-premise.md](backlog/on-premise.md). Controles y pendientes de seguridad: [calidad-bancaria.md](calidad-bancaria.md).

## 1. Dónde estamos
Fase 1a on-premise (descubrimiento). El agente, la API, la web y el MCP están construidos y medidos, y desde el 2026-11-16 el
catálogo, el conocimiento y la auditoría viven en la **BD `ConverData`** (SQL Server) cuando `CONVERDATA_DB` está definida. Lo que
falta para el piloto es terminar de llevar la curación a la BD, el LLM real, la instalación en Windows Server y el trabajo con el banco.

El 2026-11-16 se alinearon PRD, specs, backlog y diagramas con la **arquitectura simplificada** (PRD §13, decisiones 9–16): búsqueda
léxica en memoria sin embeddings, BD `ConverData` en tablas normales (SQL Server 2016+), web Next.js en lugar de Chainlit, Builder como
comando programado, un solo modelo de Bedrock y AWS como despliegue mínimo posterior al piloto.

| Pieza | Estado | Dónde |
|---|---|---|
| DiscoverFlow (F22) en LangGraph: `intent → retrieve ⇄ grade → rerank → expand ⇄ review → respond → finalize` | ✅ | `src/converdata/flows/discover.py` |
| Lógica determinista (recuperación léxica, confianza F22, guardas, respaldos sin LLM) y patrones medidos | ✅ | `src/converdata/discovery/` |
| Agente de esquemas: CatalogBuildFlow `extract → enrich → relate → write` (F1, F18, F19) | ✅ probado contra SQL Server real; escribe YAML | `flows/catalog_build.py`, `builder/`, `metadata/sqlserver.py` |
| Grafo del patrimonio (entidades, copias canónicas, caminos de unión con permisos) | ✅ en memoria (así se queda) | `src/converdata/graph/estate.py` |
| Gateway de LLM: Ollama (solo local), NVIDIA NIM, Bedrock; respaldo, circuit breaker, guarda de residencia | ✅ Ollama y NIM probados; **Bedrock sin probar** (HU-35) | `src/converdata/llm/` |
| Capa de herramientas compartida y `converdata-mcp` (stdio y `/mcp` con `Bearer`) | ✅ | `application/discovery.py`, `integration/mcp/` |
| `ConverData-API`: login SQL por servidor, SessionVault, visibilidad, descubrimiento, feedback, curación, administración, métricas | ✅ sobre archivos | `api/converdata_api/` |
| Endurecimiento bancario y compuerta `converdata eval gate` (7 suites, línea base, CI) | ✅ | `api/converdata_api/security.py`, `evaluation/gate.py`, `.github/workflows/calidad.yml` |
| Web Next.js: chat, ficha, Catálogo, Curación, Solicitudes, Métricas, Administración | ✅ falta recompilar tras el endurecimiento | `web/` |
| BD `ConverData`: migraciones (`converdata db migrate`), roles de mínimo privilegio y pruebas contra SQL Server real | ✅ bloque A | `db/converdata/`, `storage/migrations.py`, `conftest.py` |
| Auditoría fail-closed en SQL Server (preguntas, pasos, candidatos, votos, eventos; purga con su propio rol) | ✅ bloque B | `audit/sqlserver.py`, `api/converdata_api/audit.py` |
| Catálogo y conocimiento en la BD con historial y autor; la API arranca desde ella y carga lo que publica el Builder | ✅ bloque C1 | `storage/catalog_repository.py`, `catalog/store.py`, `api/converdata_api/runtime.py` |
| Responsables, solicitudes escaladas, votos e inventario de la API en la BD | ⏳ bloque C2: hoy archivos | `api/converdata_api/curation.py` |
| Instalación en Windows Server (IIS, tareas programadas) | ⏳ bloque F: hoy `docker compose` | — |

## 2. Resultados medidos
`converdata eval discovery` — Hit@1 sobre preguntas con respuesta. Siempre 0 fugas de permisos y 0 objetos inventados.

| Catálogo | Hit@1 | Hit@3 | A directa | B vocabulario | C varios saltos (caminos) | D entidad | E exploración | G brechas | p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| Fixture VBank (propuesta), 25 casos | 100 % | 100 % | — | — | — | — | — | 100 % | — |
| **BancosSQL crudo, léxico (línea base vigente, 31 casos)** | **93,1 %** | **93,1 %** | 100 % | 87,5 % | 80 % (100 %) | 100 % | 100 % | 100 % | 41 / 73 ms |
| BancosSQL crudo + embeddings `bge-m3` | 93,1 % | 93,1 % | 100 % | 87,5 % | 80 % (100 %) | 100 % | 100 % | 100 % | 524 / 4592 ms |
| BancosSQL enriquecido por Qwen, léxico | 82,8 % | 93,1 % | 100 % | 75 % | 60 % (100 %) | 100 % | 75 % | 100 % | 71 / 111 ms |
| BancosSQL enriquecido + embeddings | 82,8 % | 89,7 % | 87,5 % | 87,5 % | 60 % (100 %) | 100 % | 75 % | 100 % | 407 / 508 ms |

Historia de la línea base en BancosSQL crudo: 44,8 % / 69 % sin patrones ni grafo → 72,4 % / 82,8 % con patrones y grafo → 93,1 % / 93,1 %
tras las mejoras de descubrimiento del commit `9c700ec` (medición HU-34 del 2026-10-29).

Compuerta `converdata eval gate` (2026-11-15, modo determinista): aprobada en `tests/fixtures/vbank` y `tests/fixtures/bancos`, con
0 fugas en 714 preguntas × usuario y 4 862 llamadas a herramientas.

Lo que estas cifras **no** dicen:
- Los 56 casos los escribió el equipo de desarrollo (sesgo de ajuste). Faltan 50–80 preguntas reales (HU-33).
- Todo se midió sin LLM. Falta repetir con Bedrock (HU-35), también las suites `inyeccion` y `guardas`.
- Fallos que quedan en crudo: **B4** ("arrendamientos financieros de vehículos": devuelve `ContratosLeasing.MontoFinanciado` en vez de la
  tabla) y **C2** (transacciones TC ↔ DUI: `Clientes.DUI` no entra en el top 3). Son de orden, no de recuperación.
- El diagrama on-premise cita una prueba con 25 preguntas normativas, de tablero y de estudio (4 % de acierto solo con catálogo, 40 % con
  fuentes de conocimiento). **Ese set no está en el repo**: hay que versionarlo en `tests/fixtures/*/eval/` o repetir la prueba antes de
  usar la cifra.

Lecciones que guían lo que sigue:
- El grafo resolvió D (copias de Clientes en 4 BDs) y C (caminos de unión); la descomposición de preguntas compuestas fue clave para C.
- Las descripciones generadas por LLM empeoran la búsqueda léxica si pesan como las humanas: son evidencia débil (×0.5).
- Los embeddings no mejoran el acierto y multiplican la latencia: no se despliegan (PRD §13, decisión 9).
- Lo que más mueve las preguntas de reporte es el conocimiento ingerido (diccionarios, documentos, reglas), no el modelo.

## 3. Próximos pasos (en orden)
Bloques del [backlog §3](backlog/on-premise.md#3-plan-de-entregas). A, B, C, D y los scripts de F no dependen de nadie externo.

| Bloque | Qué | Historias | Estado |
|---|---|---|---|
| **A** | BD `ConverData`: DDL en migraciones con `dbo.schema_version`, roles (API, Builder, auditor, mantenimiento), sin `VECTOR`, Full-Text ni grafo; `converdata db migrate`; pruebas contra SQL Server real, también con la cuenta de cada rol | HU-04, HU-05 | ✅ 2026-11-16 (probado en SQL Server 2022, no en 2016) |
| **B** | Auditoría fail-closed en SQL Server: preguntas, pasos, candidatos, votos y eventos de la API y de la CLI; lectura para Administración, historial y métricas; purga `audit.usp_purge` | HU-20 | ✅ 2026-11-16 (falta la alerta en el monitoreo, HU-37) |
| **C1** | Catálogo y conocimiento en la BD con historial; publicar, cargar y exportar; el Builder publica (`catalog build --db`); la API arranca desde la BD, edita bajo un solo candado y recarga cuando cambia la versión | HU-06, HU-08, HU-09 | ✅ 2026-11-16, con las salvedades de abajo |
| **C2** | Terminar HU-06 y HU-09. (1) Migración `002` y `CurationStore` sobre la BD: responsables por login, solicitudes escaladas, votos, registro de diccionarios e inventario de la API, hoy en archivos. (2) Que la curación escriba filas concretas, para no necesitar la copia de trabajo en disco. (3) Anonimizar la plantilla de las confirmaciones y guardar el original en `golden`. (4) Regla de votos. (5) Historial de descripciones en la vista Curación. (6) Un caso de uso común para el build, hoy repetido en la CLI y en la API | HU-06, HU-09, HU-15, HU-25, HU-28 a HU-32 | ⏳ **siguiente** |
| **D** | `converdata metrics report` y vistas SQL del scorecard; reporte de brechas por dominio | HU-23, HU-32 | ⏳ |
| **E** | Conocimiento del dominio piloto: diccionario en Excel, documentos con redacción de datos personales, linaje SSIS | HU-25, HU-26, HU-27 | ⏳ E necesita documentos y SSISDB (S6); el conector y la redacción se pueden hacer ya |
| **F** | `deploy/windows/`: IIS con HttpPlatformHandler para web y API, tareas programadas (refresco, purga, evaluación), firewall, verificación; respaldo y restauración | HU-37, HU-38, HU-39, HU-18, HU-24 | ⏳ los scripts se pueden escribir ya; validarlos necesita un Windows Server |
| **G** | Bedrock de punta a punta y set de preguntas reales | HU-35, HU-36, HU-33 | ⛔ cuenta AWS y steward |
| **H** | Línea base, piloto de 8 semanas e informe | HU-40, HU-41, HU-13 | ⛔ banco |

Salvedades de A, B y C1, para no darlas por cerradas de más (detalle en los bloques **Estado** del backlog):
- Las pruebas contra SQL Server no corren en la CI (no tiene SQL Server): hay que ejecutarlas a mano con `CONVERDATA_TEST_DB`.
- Los comandos nuevos de la CLI (`db migrate`, `catalog publish|export|build --db`, `eval gate --db`, `audit purge`) se probaron a mano
  contra la BD local, pero no tienen pruebas automáticas; sí las tienen las funciones que llaman.
- La prueba de literales marcados de punta a punta (HU-06, OP-02 CA5) no existe, y `knowledge.golden_discovery` guarda la pregunta
  normalizada, no anonimizada (mitigado: el Builder no la lee, no se exporta y no se guarda si parece llevar datos personales).
- El servidor todavía guarda estado propio: la copia de trabajo del catálogo y los archivos de curación.

Hallazgos del 2026-11-16 ya corregidos:
- El refresco borraba del catálogo los objetos de un servidor que no respondía.
- Con `databases: "*"` el Builder catalogaba la propia BD `ConverData`.
- El DDL anterior no tenía la columna `detail` que el escritor de auditoría insertaba.
- De la revisión de seguridad: la copia de trabajo no tenía un candado común entre editar, traer y publicar (una edición podía
  perderse con respuesta de éxito, o publicarse a nombre de otro); el voto se aplicaba antes de auditarse y publicaba el catálogo
  entero; el rol del Builder podía leer las preguntas confirmadas y borrar lo curado; las pruebas podían correr contra una BD real
  si `CONVERDATA_TEST_DB` nombraba una; `verify` no veía permisos concedidos tabla por tabla.

Pendientes que no son historias (de [calidad-bancaria §5](calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto)), a resolver junto al bloque que toque:
- Con C2: que un solo "✖" de un consumidor no retire una confirmación de usuarios; no publicar ni recargar todo en cada voto.
- Con C2: decidir si el responsable ve en Curación activos que su login no puede leer (PRD §13, pregunta abierta 7).
- Con D: decidir qué lecturas se auditan además de las preguntas (pregunta abierta 8).
- Con F: dependencias fijadas con hashes, imagen por digest, SBOM; SQL Server en la CI para que las pruebas de la BD corran en cada PR;
  probar el DDL en la versión de SQL Server del piloto (se probó en 2022).

Mejoras de calidad del agente, solo si la medición las pide (regla: se acepta lo que mejora el set sin bajar otros tipos ni crear fugas):
- Orden de B4 y C2 (hoy los únicos fallos del set de BancosSQL).
- Explorador acotado sobre el grafo si el tipo E baja de 85 % con el set real.

## 4. Cómo retomar (checklist)
```bash
cd converdata
.venv/Scripts/python -m pip install -e ".[api,mcp,dev,ollama,sqlserver]"   # sin esto api/tests no carga
.venv/Scripts/python -m pytest -q                                          # 297 passed, 63 skipped (las de SQL Server)
export CONVERDATA_TEST_DB='SERVER=localhost\SQLEXPRESS;Trusted_Connection=yes;TrustServerCertificate=yes'
.venv/Scripts/python -m pytest -q                                          # 360 passed: incluye migraciones, roles, auditoría y catálogo en una BD real y desechable
.venv/Scripts/python -m converdata.cli eval gate --out reports             # compuerta: debe aprobar en vbank y bancos
sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "SELECT name FROM sys.databases WHERE database_id>4"   # 5 BDs Banca* y ConverData
export CONVERDATA_DB='SERVER=localhost\SQLEXPRESS;DATABASE=ConverData;Trusted_Connection=yes;TrustServerCertificate=yes'
.venv/Scripts/python -m converdata.cli db migrate --status                 # "ninguna (la BD está al día)"
.venv/Scripts/python -m converdata.cli eval gate --db --root tests/fixtures/bancos   # la compuerta con el catálogo de la BD
```
En local, la autenticación de Windows de la API viene apagada: añadir `CONVERDATA_ALLOW_WINDOWS_AUTH=1` a `.env`.
La web necesita `npm --prefix web ci` (no hay `node_modules`).
Luego seguir con el bloque C2 de §3.

## 5. Decisiones de arquitectura vigentes
El registro completo está en [PRD §13](PRD.md#13-decisiones-y-preguntas-abiertas). Las que más pesan al programar:
- **Workflow, no agente autónomo**: el grafo fija el orden; el LLM opina dentro de nodos (intención, orden, narrativa) y nunca decide
  los pasos. Ciclos acotados: reformular (máx. 1), corregir (máx. 1).
- **Búsqueda léxica + grafo, todo en memoria** de `ConverData-API`; la BD `ConverData` es la fuente de verdad y el índice se reconstruye
  al arrancar o cuando cambia `catalog.catalog_version`. El directorio de datos de la API es una copia de trabajo desechable.
- **Publicar es dejar la BD igual a la foto escribiendo solo lo que cambió**, bajo un bloqueo y con la versión esperada. El Builder
  (`scope="build"`) solo toca lo que deriva de los metadatos: nunca pisa lo humano ni lo curado.
- **La cuenta de la API no puede modificar ni borrar la auditoría**; en qa y prod la API lo comprueba al arrancar.
- **Texto generado por IA = evidencia débil** (cobertura ×0.5, confianza máx. 0.6 sin otra evidencia) hasta curación humana.
- **Una sola respuesta por dato replicado**: la copia canónica (más referenciada) con las demás en `copies`.
- **Ollama solo en local** (regla de código + `CONVERDATA_ENV`); NIM alojado solo con datos de prueba; Bedrock para datos reales.
- **Capas** ([capas-backend](architecture/capas-backend.md)): dominio y aplicación no importan `pyodbc`, LangChain ni FastAPI; los
  adaptadores de SQL Server van en infraestructura detrás de un puerto (`tests/test_architecture.py`).
- **Todo cambio de lógica se acepta solo si la compuerta no baja** de su línea base ni crea fugas.

## 6. Estado del entorno local (no está en git)
| Elemento | Detalle |
|---|---|
| `.venv/` | Python 3.12 con langgraph, langchain-core/aws/ollama/nvidia, fastapi, mcp, pyodbc, pytest |
| SQL Server local | `localhost\SQLEXPRESS`, **SQL Server 2022 Express**, con 5 BDs de prueba cargadas desde `BancosSQL.zip` (BancaTarjetasCredito, BancaCuentasDebito, BancaTokenizacion, BancaLeasing, BancaPrestamos) y la BD **`ConverData`** de desarrollo, creada el 2026-11-16 con las migraciones aplicadas y el catálogo de BancosSQL publicado. Se elimina con `DROP DATABASE ConverData` si hace falta. Solo está el ODBC Driver 17 (el código usa el 18 si existe) |
| `data/` (ignorado) | `bancos_sql/` (scripts extraídos), `catalog_bancos/` (catálogo crudo), `catalog_bancos_enriched/` (enriquecido por Qwen), `logs/` |
| `config/models.yaml` (ignorado) | Ollama `qwen3.6:35b-a3b` para planner y fast |
| Ollama | `qwen3.6:35b-a3b` y `bge-m3` instalados (`bge-m3` solo para repetir la medición de embeddings) |
| `web/node_modules` | Sin instalar |
| `BancosSQL.zip` (13 MB) | Versionado en git; conviene sacarlo del repo o usar Git LFS |

## 7. Qué necesita al banco o a terceros
| Necesidad | Para | Supuesto del backlog |
|---|---|---|
| Cuenta de AWS con Bedrock e IAM Roles Anywhere | HU-35, HU-38 | S4 |
| Steward funcional y técnico, y 50–80 preguntas reales | HU-33, HU-31 | S9 |
| Ubicación de diccionarios y documentos; acceso a SSISDB y msdb | HU-26, HU-27 | S6 |
| Windows Server del piloto, instancia para la BD `ConverData`, gMSA, certificado de la PKI | HU-37, HU-38 | S10 |
| LDAP de solo lectura | HU-13 | S10 |
| Gestor de requerimientos y canal de consultas para la línea base | HU-40 | S13 |
| Decisiones de Seguridad de la Información: Guardrails, lecturas auditadas, batería de inyección | HU-36 | S7 |
