# Plan de desarrollo — estado y cómo retomar

> Última actualización: 2026-11-17. Documento vivo: se actualiza al cerrar cada sesión de trabajo.
> Specs: [PRD](PRD.md) (decisiones vigentes en §13), [comun/](specs/comun/), [on-premise/](specs/on-premise/). Uso diario: [README](../README.md#desarrollo).
> Backlog con el estado de cada historia: [backlog/on-premise.md](backlog/on-premise.md). Controles y pendientes de seguridad: [calidad-bancaria.md](calidad-bancaria.md).

## 1. Dónde estamos
Fase 1a on-premise (descubrimiento). El agente, la API, la web y el MCP están construidos y medidos, y desde el 2026-11-16 el
catálogo, el conocimiento y la auditoría viven en la **BD `ConverData`** (SQL Server) cuando `CONVERDATA_DB` está definida. Desde el
2026-11-17 (bloque C2) también el inventario de servidores, los responsables, las dudas escaladas y los votos: con la BD, `ConverData-API` ya no guarda estado en el disco del servidor. Lo que falta para el piloto es el LLM real, la
instalación en Windows Server y el trabajo con el banco.
Arquitectura (modelo C4): [architecture/README.md](architecture/README.md). Wiki interna con la deuda técnica, las brechas funcionales y las hojas de ruta: [wiki/README.md](wiki/README.md).

El mismo 2026-11-17, en una segunda tanda ("deudas técnicas", detalle en §3), se resolvieron los dos fallos de orden del
descubrimiento, se versionó y midió el set de 25 preguntas de reporte, se fijó la cadena de suministro (bloqueos con hashes, imágenes
por digest, análisis en la CI) y se escribió la prueba de literales marcados de punta a punta.

Ese día se cerraron también DT-01 (el proxy de la web reenvía `Origin`), DT-03 (cabeceras de seguridad en la web), DT-08 (las conversaciones se borran al cerrar sesión), DT-57 (la visibilidad pregunta `HAS_DBACCESS` desde `master`) y DT-67 (el proxy solo reenvía las rutas que usa la web). DT-02 queda mitigada: falta activar `TRUST_FORWARDED_FOR` y `CONVERDATA_TRUST_PROXY` detrás de IIS (bloque F). Registro en [wiki/deuda-tecnica.md](wiki/deuda-tecnica.md).

El 2026-11-16 se alinearon PRD, specs, backlog y diagramas con la **arquitectura simplificada** (PRD §13, decisiones 9–16): búsqueda
léxica en memoria sin embeddings, BD `ConverData` en tablas normales (SQL Server 2016+), web Next.js en lugar de Chainlit, Builder como
comando programado, un solo modelo de Bedrock y AWS como despliegue mínimo posterior al piloto.

El 2026-11-22 se fusionó `origin/main` (trabajo S1-A de otros colaboradores). Se conservaron el arreglo del descubrimiento que nombra el
proceso de carga en las preguntas de linaje y elige un punto de partida que resuelva las preguntas compuestas (con sus pruebas), el
fixture `vbank` en la imagen de la API para el modo demo, las specs [OP-08](specs/on-premise/OP-08-interfaz-web.md) y
[OP-09](specs/on-premise/OP-09-situaciones-desarrollo.md), las marcas de situación de pytest (`llm_local`, `sqlserver`, `bedrock`,
`windows_server`), las skills, los hooks y la configuración de MCP de Claude Code. Se retiraron, por contradecir PRD §13, las migraciones
`002_estate.sql` (tablas de grafo), `003_semantic.sql` y `004_roles_y_version.sql` (duplicaba `dbo.schema_version` y los roles de
`001_esquemas.sql`), el puerto `CatalogStore` con `catalog/files.py` y la selección de adaptadores por `CONVERDATA_STORE`/`CONVERDATA_AUDIT`
de `bootstrap.py`: la persistencia sigue siendo `converdata.storage` con `open_stores` y la guarda de qa/prod la de
`api/converdata_api/security.py`.

| Pieza | Estado | Dónde |
|---|---|---|
| DiscoverFlow (F22) en LangGraph: `intent → retrieve ⇄ grade → rerank → expand ⇄ review → respond → finalize` | ✅ | `src/converdata/flows/discover.py` |
| Lógica determinista (recuperación léxica, confianza F22, guardas, respaldos sin LLM) y patrones medidos | ✅ | `src/converdata/discovery/` |
| Agente de esquemas: CatalogBuildFlow `extract → enrich → relate → write` (F1, F18, F19) | ✅ probado contra SQL Server real; escribe YAML | `flows/catalog_build.py`, `builder/`, `metadata/sqlserver.py` |
| Grafo del patrimonio (entidades, copias canónicas, caminos de unión con permisos) | ✅ en memoria (así se queda) | `src/converdata/graph/estate.py` |
| Gateway de LLM: Ollama (solo local), NVIDIA NIM, Bedrock; respaldo, circuit breaker, guarda de residencia | ✅ Ollama y NIM probados; **Bedrock sin probar** (HU-35) | `src/converdata/llm/` |
| Capa de herramientas compartida y `converdata-mcp` (stdio y `/mcp` con `Bearer`) | ✅ | `application/discovery.py`, `integration/mcp/` |
| `ConverData-API`: login SQL por servidor, SessionVault, visibilidad, descubrimiento, feedback, curación, administración, métricas | ✅ con la BD `ConverData`; sobre archivos solo en desarrollo y modo demo | `api/converdata_api/` |
| Endurecimiento bancario y compuerta `converdata eval gate` (7 suites, línea base, CI) | ✅ | `api/converdata_api/security.py`, `evaluation/gate.py`, `.github/workflows/calidad.yml` |
| Cadena de suministro: dependencias de Python con versión y hash, imágenes base por digest, acciones por commit, `pip-audit`, `npm audit` y SBOM en la CI | ✅ 2026-11-17; la imagen no se construyó ese día y no hay firma ni escaneo de la imagen (§3) | `requirements/`, `api/Dockerfile`, `web/Dockerfile`, `.github/workflows/calidad.yml`, `.github/dependabot.yml`, `tests/test_supply_chain.py` |
| Web Next.js: chat, ficha, Catálogo, Curación, Solicitudes, Métricas, Administración | ✅ compilada el 2026-11-17 (tipos, lint y build); Responsables e Historial probados en navegador | `web/` |
| BD `ConverData`: migraciones (`converdata db migrate`), roles de mínimo privilegio y pruebas contra SQL Server real | ✅ bloque A | `db/converdata/`, `storage/migrations.py`, `conftest.py` |
| Auditoría fail-closed en SQL Server (preguntas, pasos, candidatos, votos, eventos; purga con su propio rol) | ✅ bloque B | `audit/sqlserver.py`, `api/converdata_api/audit.py` |
| Catálogo y conocimiento en la BD con historial y autor; la API arranca desde ella y carga lo que publica el Builder | ✅ bloque C1 | `storage/catalog_repository.py`, `catalog/store.py`, `api/converdata_api/runtime.py` |
| Responsables, solicitudes escaladas, votos e inventario de la API en la BD; la curación escribe filas concretas; plantilla anónima y regla de votos | ✅ bloque C2 (2026-11-17) | `db/converdata/002_curacion.sql`, `src/converdata/curation.py`, `storage/curation_repository.py`, `api/converdata_api/curation.py` |
| Instalación en Windows Server (IIS, tareas programadas) | ⏳ bloque F: hoy `docker compose` | — |

## 2. Resultados medidos
`converdata eval discovery` — Hit@1 sobre preguntas con respuesta. Siempre 0 fugas de permisos y 0 objetos inventados.

| Catálogo | Hit@1 | Hit@3 | A directa | B vocabulario | C varios saltos (caminos) | D entidad | E exploración | G brechas | p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| **BancosSQL crudo, léxico (línea base vigente, 58 casos, 2026-11-17)** | **98,0 %** | **98,0 %** | 100 % | 95,7 % | 100 % (100 %) | 100 % | 100 % | 100 % | 19 / 27 ms |
| **Fixture VBank (propuesta), línea base vigente, 31 casos, 2026-11-17** | **96,2 %** | **96,2 %** | — | — | — | — | — | 100 % | 6 / 8 ms |
| *Histórico:* Fixture VBank, 25 casos (hasta el 2026-11-16) | 100 % | 100 % | — | — | — | — | — | 100 % | — |
| *Histórico (HU-34, 2026-10-29, 31 casos):* BancosSQL crudo, léxico | 93,1 % | 93,1 % | 100 % | 87,5 % | 80 % (100 %) | 100 % | 100 % | 100 % | 41 / 73 ms |
| *Histórico (HU-34):* BancosSQL crudo + embeddings `bge-m3` | 93,1 % | 93,1 % | 100 % | 87,5 % | 80 % (100 %) | 100 % | 100 % | 100 % | 524 / 4592 ms |
| *Histórico (HU-34):* BancosSQL enriquecido por Qwen, léxico | 82,8 % | 93,1 % | 100 % | 75 % | 60 % (100 %) | 100 % | 75 % | 100 % | 71 / 111 ms |
| *Histórico (HU-34):* BancosSQL enriquecido + embeddings | 82,8 % | 89,7 % | 87,5 % | 87,5 % | 60 % (100 %) | 100 % | 75 % | 100 % | 407 / 508 ms |

Las filas vigentes y las históricas **no se comparan entre sí**: los sets crecieron el 2026-11-17 (BancosSQL de 31 a 58 casos, VBank
de 25 a 31). Para separar el efecto del código del efecto del set: con los sets antiguos, el código anterior daba 93,1 % (BancosSQL) y
100 % (VBank), y el código nuevo da 100 % y 100 %; con los sets nuevos, el código nuevo da 98,0 % y 96,2 %, con un fallo en cada uno
(abajo). Las líneas base (`tests/fixtures/*/eval/baseline.yaml`) se regeneraron ese día.

Historia de la línea base en BancosSQL crudo: 44,8 % / 69 % sin patrones ni grafo → 72,4 % / 82,8 % con patrones y grafo → 93,1 % / 93,1 %
tras las mejoras de descubrimiento del commit `9c700ec` (medición HU-34 del 2026-10-29, 31 casos) → 98,0 % / 98,0 % con el set de
58 casos tras resolver los fallos de orden (2026-11-17).

Preguntas de reporte (2026-11-17): 25 preguntas sobre BancosSQL (`tests/fixtures/bancos/eval/reportes.yaml`: 9 normativas, 8 de
tablero, 8 de estudio), medidas con el mismo catálogo crudo y con un glosario y manual de indicadores de prueba de 20 entradas
(`tests/fixtures/bancos/eval/conocimiento/items/glosario.yaml`), que se añade con `eval discovery --knowledge` sin tocar el catálogo.

| Preguntas de reporte (25) | Hit@1 | Hit@3 | N normativas (9) | T tablero (8) | S estudio (8) |
|---|---|---|---|---|---|
| Solo catálogo | 16 % | 16 % | 0 % | 25 % | 25 % |
| Catálogo + glosario de prueba | 60 % | 64 % | 66,7 % | 75 % | 37,5 % |

Lo fija `tests/test_graph_rag.py::test_las_fuentes_de_conocimiento_mueven_las_preguntas_de_reporte`. Sustituye a la cifra
"4 % → 40 %" que citaba el diagrama on-premise, cuyo set nunca estuvo en el repo (el diagrama ya está corregido).

Compuerta `converdata eval gate` (2026-11-17, modo determinista): aprobada en `tests/fixtures/vbank` y `tests/fixtures/bancos`, con
0 fugas en 1 065 preguntas × usuario (328 + 737) y 4 862 llamadas a herramientas (553 + 4 309). Con el catálogo de BancosSQL cargado
desde la BD `ConverData` (`eval gate --db --root tests/fixtures/bancos`) también aprueba con el set ampliado: Hit@1 y Hit@3 98,0 %,
0 fugas en 737 preguntas × usuario y 4 309 llamadas.

Lo que estas cifras **no** dicen:
- Los 89 casos de descubrimiento (58 de BancosSQL y 31 de VBank) y las 25 preguntas de reporte los escribió el equipo de desarrollo
  (sesgo de ajuste). Los cambios del 2026-11-17 se ajustaron y midieron con esas mismas preguntas. Faltan 50–80 preguntas reales (HU-33).
- Todo se midió sin LLM. Falta repetir con Bedrock (HU-35), también las suites `inyeccion` y `guardas`.
- Los fallos de orden **B4** ("arrendamientos financieros de vehículos" devolvía una columna en vez de la tabla) y **C2**
  (transacciones TC ↔ DUI) quedaron resueltos el 2026-11-17. C2 acierta por la tabla `TransaccionesTC`; `Clientes.DUI` sigue sin
  entrar en el top 3: lo aporta el camino de unión.
- Fallos que quedan: **B14** ("¿Dónde están los dispositivos Android bloqueados?", BancosSQL) y **eng-06** ("¿Dónde están los
  dispositivos iOS de clientes premium?", VBank). Los dos responden sin candidatos: el calificativo sí lo conoce otra tabla, así que
  no se descuenta.
- En las preguntas de reporte, las preguntas y el glosario los escribió el equipo (primero las preguntas, después el glosario). El
  resultado muestra el sentido del efecto; no predice el acierto con los documentos y las preguntas reales del banco (HU-26, HU-33).
  Las de estudio apenas se mueven (25 % → 37,5 %).

Lecciones que guían lo que sigue:
- Una pregunta por una entidad con calificativos ("los arrendamientos financieros de vehículos") pide la tabla, y el catálogo no puede
  conocer calificativos que son valores de datos (F1): se descuentan al ordenar, pero la respuesta queda por debajo del umbral de
  brecha y se ofrece preguntar al responsable (F22).
- Un evaluador independiente encontró tres clases de pregunta que la primera versión de ese cambio empeoraba. Se corrigieron y
  quedaron en el set, junto con casos nuevos de entidad con calificativos desconocidos, de cruce, de plurales que piden una columna,
  de "cada uno de" y de brechas donde la entidad existe pero lo pedido no. Con el set anterior el cambio habría dado 100 %: ampliar
  el set antes de aceptar un cambio dice más que ese porcentaje.
- El grafo resolvió D (copias de Clientes en 4 BDs) y C (caminos de unión); la descomposición de preguntas compuestas fue clave para C.
- Las descripciones generadas por LLM empeoran la búsqueda léxica si pesan como las humanas: son evidencia débil (×0.5).
- Los embeddings no mejoran el acierto y multiplican la latencia: no se despliegan (PRD §13, decisión 9). El canal con el que se
  midieron se retiró del código el 2026-11-17: las filas "+ embeddings" de la tabla son la medición histórica de HU-34, que ya no se
  puede repetir con este código (solo desde el historial de git).
- Lo que más mueve las preguntas de reporte es el conocimiento ingerido (diccionarios, documentos, reglas), no el modelo: 16 % → 60 %
  de Hit@1 en el set de prueba de arriba, sin LLM en ninguno de los dos casos.

## 3. Próximos pasos (en orden)
Bloques del [backlog §3](backlog/on-premise.md#3-plan-de-entregas). D y los scripts de F no dependen de nadie externo.

| Bloque | Qué | Historias | Estado |
|---|---|---|---|
| **A** | BD `ConverData`: DDL en migraciones con `dbo.schema_version`, roles (API, Builder, auditor, mantenimiento), sin `VECTOR`, Full-Text ni grafo; `converdata db migrate`; pruebas contra SQL Server real, también con la cuenta de cada rol | HU-04, HU-05 | ✅ 2026-11-16 (probado en SQL Server 2022, no en 2016) |
| **B** | Auditoría fail-closed en SQL Server: preguntas, pasos, candidatos, votos y eventos de la API y de la CLI; lectura para Administración, historial y métricas; purga `audit.usp_purge` | HU-20 | ✅ 2026-11-16 (falta la alerta en el monitoreo, HU-37) |
| **C1** | Catálogo y conocimiento en la BD con historial; publicar, cargar y exportar; el Builder publica (`catalog build --db`); la API arranca desde la BD, edita bajo un solo candado y recarga cuando cambia la versión | HU-06, HU-08, HU-09 | ✅ 2026-11-16, con las salvedades de abajo |
| **C2** | Terminar HU-06 y HU-09. (1) Migración `002_curacion.sql`: `catalog.inventory_server`, `curation.steward`, `curation.request` y `curation.vote` (sin texto libre); la purga `audit.usp_purge` alcanza también las dudas escaladas y los originales de las confirmaciones. (2) La curación escribe filas concretas (`KnowledgeWriter`: `write_descriptions`, `upsert_rule`, `delete_rule`, `upsert_golden`) y el catálogo se carga de la BD en memoria, sin copia de trabajo en disco. (3) Plantilla anónima de las confirmaciones (`question_template`) y original en `golden.golden_discovery_original`. (4) Regla de votos (`resolve_golden`). (5) Historial de descripciones en Curación y en la ficha (`GET /curation/history`) y responsables administrables (`GET`/`PUT /admin/stewards`). (6) Caso de uso común del build (`application/catalog_refresh.py`), que usan la CLI y la API | HU-06, HU-09, HU-15, HU-25, HU-28 a HU-32 | ✅ 2026-11-17, con las salvedades de abajo |
| **D** | `converdata metrics report` y vistas SQL del scorecard; reporte de brechas por dominio | HU-23, HU-32 | ⏳ **siguiente** |
| **E** | Conocimiento del dominio piloto: diccionario en Excel, documentos con redacción de datos personales, linaje SSIS | HU-25, HU-26, HU-27 | ⏳ E necesita documentos y SSISDB (S6); el conector y la redacción se pueden hacer ya |
| **F** | `deploy/windows/`: IIS con HttpPlatformHandler para web y API, tareas programadas (refresco, purga, evaluación), firewall, verificación; respaldo y restauración | HU-37, HU-38, HU-39, HU-18, HU-24 | ⏳ los scripts se pueden escribir ya; validarlos necesita un Windows Server |
| **G** | Bedrock de punta a punta y set de preguntas reales | HU-35, HU-36, HU-33 | ⛔ cuenta AWS y steward |
| **H** | Línea base, piloto de 8 semanas e informe | HU-40, HU-41, HU-13 | ⛔ banco |

Salvedades de A, B, C1 y C2, para no darlas por cerradas de más (detalle en los bloques **Estado** del backlog):
- Las pruebas contra SQL Server no corren en la CI (no tiene SQL Server): hay que ejecutarlas a mano con `CONVERDATA_TEST_DB`.
- El DDL (migraciones `001` y `002`) se probó en SQL Server 2022, no en 2016.
- De la CLI tienen prueba automática contra la BD desechable `db migrate`, `catalog publish`, `catalog export`, `discover --db` y
  `catalog build --db` (`tests/test_catalog_refresh.py`). `eval gate --db` y `audit purge` siguen sin prueba automática del comando;
  sí la tienen las funciones que llaman.
- La plantilla anónima quita, desde la revisión de seguridad del 2026-11-17, **toda palabra con algún dígito o con arroba** (tras
  normalizar con NFKC; también los umbrales de negocio), salvo el vocabulario conocido del banco: nombres del catálogo con dígitos
  (`Ultimos4`) y códigos del conocimiento con letras y dígitos (`NCB-022`, `BR-ONB-004`). `T24` o `F14` salen si no son nombres del
  catálogo ni códigos del glosario. **No detecta nombres de personas, texto entre comillas ni los trozos solo de letras de un
  código partido por espacios** (un IBAN escrito con espacios deja sus grupos de letras). Si tras quitar los literales la pregunta aún coincide con el detector de datos personales, el voto cuenta pero no se
  aprende. El texto original solo va a `golden.golden_discovery_original` si la pregunta no traía ningún literal ni parece llevar
  datos personales.
- El voto no guarda texto libre (`curation.vote` no tiene comentario). Las dudas escaladas (`curation.request`) y los originales de
  las confirmaciones sí llevan la pregunta: la purga de 180 días (`audit.usp_purge`) los alcanza; los votos y las plantillas se
  conservan. La purga sigue sin estar programada (HU-37).
- Cada escritura de curación vuelve a cargar el catálogo de la BD y reconstruye el índice en memoria: de forma síncrona tras una
  edición o el voto de un responsable (rige en la siguiente búsqueda), en segundo plano tras el voto de un usuario. Si lo vigente no
  se puede cargar, la API queda sin catálogo (409) en vez de seguir sirviendo el anterior, y quien editó recibe el error.
- Los roles que se dan por nombre de login (`CONVERDATA_ADMINS` y responsables) solo cuentan si la sesión validó el login en un
  servidor con `environment: produccion`, cuando el inventario tiene alguno (`identity_trusted`). Es una política que el banco debe
  confirmar (PRD §13, pregunta abierta 9).
- Con `CONVERDATA_DB` la API no arranca si faltan migraciones (`require_current`), y `catalog build --db` con el inventario de la BD
  solo se conecta a los hosts de `CONVERDATA_BUILDER_HOSTS` (obligatoria en qa y prod).
- No hay registro de diccionarios aplicados: volver a cargar el mismo CSV no escribe nada porque no queda nada que cambiar
  (`unchanged`). Así el archivo de un responsable no bloquea al de otro dominio.
- La prueba de literales marcados de punta a punta ya existe (`api/tests/test_marked_literals.py`, abajo). No cubre el cliente
  MCP, `/discover/stream` ni lo que es del servidor del piloto: el Visor de eventos, `TEMP` de las gMSA, las carpetas de IIS y los
  volcados de memoria (HU-37).
- Sin `CONVERDATA_DB` (desarrollo y modo demo) todo sigue en archivos (`converdata.storage.files`), y `GET /curation/history`
  responde `available: false`.

Deudas técnicas resueltas el 2026-11-17 (segunda tanda), con lo que cada una deja abierto:
- **Fallos de orden del descubrimiento (antes B4 y C2).** (1) Las preguntas de cruce ("¿cómo relaciono / cruzo / uno A con B?")
  piden tablas (`_JOIN` en `discovery/deterministic.py`); "cada uno de" no cuenta como cruce y "¿con qué campo cruzo…?" pide la
  columna (`_ASKS_FIELD`). (2) `engine.entity_kind_hint`: un plural que nombra una tabla o vista visible para el usuario ("¿dónde
  están los arrendamientos financieros de vehículos?") pide esa tabla; no aplica si una columna se llama como las dos primeras
  palabras ("pagos mínimos" → `PagoMinimo`) ni en preguntas compuestas. Lo aplica el nodo `intent` del flujo solo cuando la intención
  no trajo ya un tipo. (3) Cuando se pide una tabla, los nombres de sus columnas cuentan como términos débiles; un calificativo que
  ningún activo recuperado conoce pesa 0,25 (`qualifier_weights`, `UNKNOWN_QUALIFIER_WEIGHT`); `shortlist` descarta las columnas si
  alguna tabla alcanza la relevancia mínima; y una respuesta que descontó calificativos queda siempre por debajo del umbral de brecha
  (`Draft.unknown_qualifiers`, `compute_confidence`): se muestra la tabla con confianza baja y se ofrece preguntar al responsable.
  (4) Los literales de la pregunta ya no cuentan como conceptos que un activo deba cubrir: `strip_literals(question, known)` vive
  en `converdata.memory.text` y lo usan `discovery/expansion.py` y `curation.py`. Tras la revisión de seguridad la regla ya no es
  una lista de formatos: toda palabra con algún dígito o con arroba es un literal (tras NFKC), salvo el vocabulario conocido. Para
  la cobertura, el vocabulario son los nombres con dígitos de lo que el usuario ve (`Catalog.names_with_digits(visible_ids)`); para
  la plantilla y el original, el catálogo entero más los códigos del conocimiento (`KnowledgeBase.codes`,
  `AgentRuntime._vocabulary`). La revisión había reproducido que `ACME090`, los dígitos en superíndice, el guion final o la raya
  llegaban a la plantilla y al texto original. (5) De la misma revisión: el nombre de una tabla referenciada por llave foránea
  solo cuenta como término de un activo si el usuario también la ve (`_asset_terms_split`, `_asset_terms`; antes se podía
  confirmar su nombre por la confianza; `test_el_nombre_de_una_tabla_que_no_se_ve_no_mueve_la_confianza`). Deudas: las estadísticas
  BM25 son globales (la confianza de un usuario varía hasta ~0,006 según existan objetos que no ve, sin nombres ocultos) y dos
  preguntas que solo difieren en un código que el glosario no tiene comparten plantilla y confirmación. Abierto: B14 y eng-06 (§2), y que todo se ajustó con preguntas del equipo (HU-33).
- **Set de preguntas de reporte.** `tests/fixtures/bancos/eval/reportes.yaml` y el glosario de prueba; opción
  `converdata eval discovery --knowledge <dir>` (`bootstrap.build_service_with_knowledge`), que no se combina con `--db`. Cifras y
  límites en §2.
- **Cadena de suministro.** `requirements/runtime.lock`, `dev.lock`, `build.lock` y `tools.lock` (`pip-audit` y `cyclonedx-bom`:
  el trabajo `cadena-de-suministro` ya no instala nada sin hash) fijan versión y hash de todas las dependencias de Python (bloqueos universales generados con `uv pip compile --generate-hashes`; cómo regenerarlos, en
  [`requirements/README.md`](../requirements/README.md)). La imagen (`api/Dockerfile`) y la CI instalan con
  `pip install --require-hashes --only-binary :all:` y el paquete con `--no-deps --no-build-isolation --no-index`. La clave con la
  que Microsoft firma su repositorio se acepta solo si su huella es la fijada (`MICROSOFT_KEY_FINGERPRINT`). El argumento de build `EXTRAS` pasó a
  `REQUIREMENTS` (`CONVERDATA_REQUIREMENTS` en `docker-compose.yml`; `runtime.lock` por defecto, `dev.lock` para NIM u Ollama). Las
  imágenes base van por digest y las acciones de GitHub por commit; `.github/dependabot.yml` las mantiene al día (imágenes, acciones
  y npm; los bloqueos de Python se regeneran a mano). La CI tiene tres trabajos: `backend`, `web` (tipos, lint y build; antes no
  existía) y `cadena-de-suministro` (`pip-audit` sobre `runtime.lock`, `npm audit --omit=dev --audit-level=high` y SBOM CycloneDX de
  la API y de la web como artefacto); corre en cada push y PR y cada lunes (`schedule`). `tests/test_supply_chain.py` falla si algo
  deja de estar fijado o si un `pip install` no lleva hashes y `--only-binary` (o `--no-index`). El análisis encontró
  vulnerabilidades reales en la web: Next.js 15.5.4 (entre otras, ejecución remota de código en servidores Windows), actualizado a
  15.5.29, y `postcss` transitivo, forzado a 8.5.33 con `overrides` en `web/package.json`; `npm audit --omit=dev` queda en 0 y
  `pip-audit` no encontró nada en Python. Abierto: **la imagen no se construyó ese día** (Docker no estaba en marcha; se simularon
  sus pasos de instalación en un entorno limpio); las versiones de los paquetes del sistema de la imagen (`msodbcsql18`,
  `unixodbc`) no van fijadas; no hay firma ni análisis de la imagen construida; el bloqueo de Python se actualiza a mano; las dependencias de desarrollo de la web siguen con
  avisos (no se despliegan).
- **Literales marcados de punta a punta.** `api/tests/test_marked_literals.py`: 100 preguntas con 100 literales distintos en 10 formas
  (códigos `ACME-TEST-nnn`, documentos, cuentas alfanuméricas, correos, números y, tras la revisión de seguridad, alfanumérico
  corto, superíndices, raya, guion bajo con guion final y ancho completo), preguntadas por la API con tres usuarios (el literal va
  también en `history`), votadas, 20
  escaladas con nota y varias respondidas por un responsable. Después busca el literal, también transformado (minúsculas,
  NFKC, recortado a los 6 caracteres del stemmer), en el índice en memoria, en todo el disco del servidor (logs incluidos) y en
  toda columna de toda tabla de la BD que no sea número, fecha, bit o `uniqueidentifier`, convertida a texto (historial incluido),
  y comprueba que las plantillas solo contienen palabras de las preguntas base. Solo aparece en
  `audit.audit_question.question`, `curation.request.question` y `curation.request.note` (en modo archivos, en `audit/*.jsonl` y
  `curation/requests.json`). Corre en archivos y, con `CONVERDATA_TEST_DB`, en SQL Server real. Cierra F17 CA1, OP-02 CA5 y OP-06 CA1
  y CA4 en lo que cubre: no incluye el cliente MCP, `/discover/stream`, el Visor de eventos de Windows (`event_log` va apagado en la
  prueba), `TEMP` de las gMSA, carpetas de IIS ni volcados de memoria, y los nombres de personas siguen sin detectarse.
- **Historial simulado del modo demo** (`api/converdata_api/demo_history.py`): ya no usa las preguntas `expect_gap` del set y simula
  votos también sobre respuestas de baja confianza. Solo afecta a la demo.

Limpieza del 2026-11-17: se retiraron del código el canal de embeddings (ya no existen `config/models.embed.yaml`, `--embeddings-only`,
`CONVERDATA_EMBEDDINGS_ONLY` ni el rol `embed`; un `models.yaml` que lo declare se carga ignorándolo con un aviso, y en qa y prod la
API se niega a arrancar), `VisibilityResolver` (duplicado sin uso: la visibilidad por sesión la calcula `AgentRuntime.visible_ids`) y
código muerto (`Catalog.physical_ids`, `engine.mentioned_assets`, `QueryVariants`, `EstateGraph.neighbors`,
`runtime.set_golden_state`, `GoldenAction`, el parámetro `llm_nodes` de `build_service*`). La API ya no responde 409 por catálogo
desactualizado ni emite `catalog_conflict`: cada edición escribe sus filas. `SqlServerCatalogRepository.publish` conserva la versión
esperada (`expected_version`).

Hallazgos del 2026-11-16 ya corregidos:
- El refresco borraba del catálogo los objetos de un servidor que no respondía.
- Con `databases: "*"` el Builder catalogaba la propia BD `ConverData`.
- El DDL anterior no tenía la columna `detail` que el escritor de auditoría insertaba.
- De la revisión de seguridad: la copia de trabajo no tenía un candado común entre editar, traer y publicar (una edición podía
  perderse con respuesta de éxito, o publicarse a nombre de otro); el voto se aplicaba antes de auditarse y publicaba el catálogo
  entero; el rol del Builder podía leer las preguntas confirmadas y borrar lo curado; las pruebas podían correr contra una BD real
  si `CONVERDATA_TEST_DB` nombraba una; `verify` no veía permisos concedidos tabla por tabla.

Pendientes que no son historias (de [calidad-bancaria §5](calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto)), a resolver junto al bloque que toque:
- Resueltos con C2 (2026-11-17): un solo "✖" de un consumidor ya no retira lo que confirmaron varios (cuentan las confirmaciones
  netas), y un voto escribe solo su fila en lugar de publicar el catálogo. El índice completo se sigue recargando tras cada escritura.
- Sigue abierto: decidir si el responsable ve en Curación activos que su login no puede leer (PRD §13, pregunta abierta 7). Quedó
  resuelto solo para el historial (`GET /curation/history` exige visibilidad); la cola de revisión y la edición de descripciones
  siguen sin filtrar por `visible_ids`.
- Sin bloque asignado: que la fecha de un registro de auditoría (`ts`) no la fije quien lo inserta; llevar la orquestación de votos
  (`record_feedback`, `steward_golden`) de la API a un caso de uso de `converdata.application`; que la CLI use `open_stores`; que
  `tests/test_architecture.py` analice también `api/converdata_api` (lista completa en [capas-backend](architecture/capas-backend.md)
  y [calidad-bancaria §5](calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto)).
- Con D: decidir qué lecturas se auditan además de las preguntas (pregunta abierta 8).
- Con F: construir la imagen con los bloqueos (no se pudo el 2026-11-17), fijar la versión de `msodbcsql18` y `unixodbc`, y firmar y
  analizar la imagen construida; decidir si el bloqueo de Python se sigue actualizando a mano; SQL Server en la CI para que las pruebas de la BD corran en cada PR; probar el DDL en la versión de
  SQL Server del piloto (se probó en 2022). Las dependencias fijadas con hashes, las imágenes por digest y el SBOM ya están (arriba).

Mejoras de calidad del agente, solo si la medición las pide (regla: se acepta lo que mejora el set sin bajar otros tipos ni crear fugas):
- Los casos B14 y eng-06 (hoy los únicos fallos de los dos sets): una entidad con un calificativo que conoce otra tabla. Los fallos
  de orden B4 y C2 (ese "C2" es un caso de tipo C, no el bloque) se resolvieron el 2026-11-17.
- Explorador acotado sobre el grafo si el tipo E baja de 85 % con el set real.

## 4. Cómo retomar (checklist)
```bash
cd converdata
# Dependencias con versión y hash fijados (requirements/README.md); sin esto api/tests no carga
.venv/Scripts/python -m pip install --require-hashes --only-binary :all: -r requirements/build.lock -r requirements/dev.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation --no-index -e .
.venv/Scripts/python -m pytest -q                                          # 375 passed, 83 skipped: sin CONVERDATA_TEST_DB las pruebas de SQL Server se omiten
export CONVERDATA_TEST_DB='SERVER=localhost\SQLEXPRESS;Trusted_Connection=yes;TrustServerCertificate=yes'
.venv/Scripts/python -m pytest -q                                          # 458 passed: incluye migraciones, roles, auditoría, catálogo, curación, la CLI y los literales marcados en una BD real y desechable
.venv/Scripts/python -m converdata.cli eval gate --out reports             # compuerta: debe aprobar en vbank y bancos
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos   # 58 casos · Hit@1 98.0 % · Hit@3 98.0 % (falla B14)
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/vbank    # 31 casos · Hit@1 96.2 % · Hit@3 96.2 % (falla eng-06)
# Preguntas de reporte, sin y con fuentes de conocimiento: Hit@1 16.0 % → 60.0 %
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos --cases tests/fixtures/bancos/eval/reportes.yaml
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos --cases tests/fixtures/bancos/eval/reportes.yaml --knowledge tests/fixtures/bancos/eval/conocimiento
sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "SELECT name FROM sys.databases WHERE database_id>4"   # 5 BDs Banca* y ConverData
export CONVERDATA_DB='SERVER=localhost\SQLEXPRESS;DATABASE=ConverData;Trusted_Connection=yes;TrustServerCertificate=yes'
.venv/Scripts/python -m converdata.cli db migrate --status                 # "ninguna (la BD está al día)"
.venv/Scripts/python -m converdata.cli eval gate --db --root tests/fixtures/bancos   # la compuerta con el catálogo de la BD
```
En local, la autenticación de Windows de la API viene apagada: añadir `CONVERDATA_ALLOW_WINDOWS_AUTH=1` a `.env`.
En un clon nuevo la web necesita `npm --prefix web ci` (`node_modules` no se versiona).
Si la BD `ConverData` local se creó antes del 2026-11-17, `db migrate --status` mostrará pendiente la `002_curacion.sql`: aplicarla
con `converdata db migrate`.
Luego seguir con el bloque D de §3.

## 5. Decisiones de arquitectura vigentes
El registro completo está en [PRD §13](PRD.md#13-decisiones-y-preguntas-abiertas). Las que más pesan al programar:
- **Workflow, no agente autónomo**: el grafo fija el orden; el LLM opina dentro de nodos (intención, orden, narrativa) y nunca decide
  los pasos. Ciclos acotados: reformular (máx. 1), corregir (máx. 1).
- **Búsqueda léxica + grafo, todo en memoria** de `ConverData-API`; la BD `ConverData` es la fuente de verdad y el índice se reconstruye
  al arrancar o cuando cambia `catalog.catalog_version`. Con la BD, la API no guarda copia del catálogo en disco: el build bajo
  demanda usa un directorio temporal que se borra al terminar.
- **Publicar es dejar la BD igual a la foto escribiendo solo lo que cambió**, bajo un bloqueo y con la versión esperada. El Builder
  (`scope="build"`) solo toca lo que deriva de los metadatos: nunca pisa lo humano ni lo curado (la descripción humana de la BD
  gana siempre, también frente a otra versión humana que el Builder arrastre). **La curación no publica**: escribe sus filas
  (`KnowledgeWriter`) y sube la versión.
- **`catalog.catalog_version` significa "algo cambió", no "publicación"**: la suben cada publicación, cada edición de curación y
  cada voto aprendido.
- **La API es un solo proceso**: sesiones, trazas de respuestas mostradas, inventario y confirmaciones recientes viven en su
  memoria; el inventario se lee al arrancar (y al guardarlo desde Administración).
- **El Builder programado entra con autenticación de Windows** (la cuenta del proceso) aunque el inventario diga login SQL, salvo
  que el servidor declare `metadata_user_env`; solo a los hosts de `CONVERDATA_BUILDER_HOSTS`.
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
| Ollama | `qwen3.6:35b-a3b` y `bge-m3` instalados (`bge-m3` ya no lo usa el código: el canal de embeddings se retiró el 2026-11-17) |
| `web/node_modules` | Instalado (Next.js 15.5.29 tras la actualización del 2026-11-17); en un clon nuevo, `npm --prefix web ci` |
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
