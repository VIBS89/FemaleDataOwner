# Manual de desarrollo de DiscoveryDataAgent

Actualizado el 2026-11-17. Este manual es para quien va a desarrollar o mantener DiscoveryDataAgent. Explica qué pieza hace
qué, cómo se conectan y qué falta por construir. En la aplicación solo lo ven los administradores de datos, porque
describe controles de seguridad y sus puntos débiles; cada lectura queda en la auditoría.

Los detalles viven en otros documentos del repositorio y este manual dice en cuál. Si algo de aquí contradice al código,
manda el código: corrige el manual en el mismo cambio.

## 1. Qué hace la solución
DiscoveryDataAgent responde en lenguaje natural dónde vive un dato, qué significa, con qué se relaciona y cuánta confianza
merece la respuesta. Lee solo metadatos de SQL Server (tablas, columnas, llaves, descripciones) y el conocimiento que
el banco le carga o le enseña. No lee valores de datos de clientes. Una excepción, apagada por defecto: con las cifras agregadas activas
(`features.ask_flow`), un total (cuántos, suma, promedio) se calcula con el login de la persona y se muestra sin guardarlo.

Cuatro reglas sostienen el diseño. Un cambio que rompa una de ellas no se acepta:

1. **Permisos heredados.** Cada persona entra con su propio login de SQL Server y descubre solo lo que ese login puede leer. Lo que no ve responde igual que lo que no existe.
2. **Auditoría antes de responder.** Si una pregunta o un cambio no se puede registrar, no se entrega ni se aplica.
3. **Sin valores de datos.** El catálogo guarda estructura y descripciones. Los literales de una pregunta (un documento, una cuenta) solo quedan en la auditoría y en las dudas escaladas. Las cifras agregadas, apagadas por defecto, solo calculan totales de plantilla fija, nunca filas ni columnas con datos personales, no muestran totales ni grupos de menos de 10 registros, y el número no pasa por el modelo ni se guarda.
4. **Medir antes de aceptar.** Un cambio en la lógica de descubrimiento entra solo si la compuerta de calidad no baja.

## 2. Componentes

### 2.1 Lo que se despliega

| Componente | Para qué sirve | Dónde está |
|---|---|---|
| **Web** | Chat con tarjetas de candidatos, Catálogo, Mis solicitudes, Curación, Métricas y Administración. Reenvía `/api/*` a la API, que no se publica directamente. No guarda credenciales | `web/` (Next.js) |
| **DiscoveryDataAgent-API** | Un solo proceso: rutas REST, servidor MCP en `/mcp` y el flujo de descubrimiento. Guarda el login de cada sesión cifrado en memoria y nada en disco | `api/discovery_data_agent_api/` (FastAPI) |
| **BD DiscoveryDataAgent** | Todo el estado: catálogo con historial, conocimiento, curación, inventario de servidores y auditoría | `db/discovery_data_agent/*.sql` (SQL Server 2016 o posterior) |
| **Builder** | Comando que lee los metadatos de los servidores, arma el catálogo y lo publica en la BD. Corre y termina; lo lanza una tarea programada o un administrador | `discovery-data-agent catalog build --db` |
| **Proveedor de LLM** | Un modelo para redactar la respuesta para una persona de negocio, reformular la búsqueda cuando cubre poco y orientar cuando no hay resultados (rol `fast`); entender la pregunta y ordenar los candidatos (rol `planner`) está desaconsejado por la medición. También describe las tablas nuevas al construir el catálogo. Sin él, el flujo funciona en modo determinista | `config/models.yaml` (Bedrock en el piloto) |
| **SQL Server de datos** | Las BDs de negocio. Son la fuente de verdad de los permisos; DiscoveryDataAgent solo les pregunta qué puede ver cada login y cuál es su estructura | Fuera del repositorio |

La arquitectura completa, del contexto a los componentes (modelo C4), está en `docs/architecture/README.md`, con sus
diagramas: `c4-contexto.html`, `onpremise-architecture.html`, `cloud-native-architecture.html`, `c4-componentes-api.html`,
`flujo-descubrimiento.html`, `modelo-datos-discovery-data-agent.html`, `permisos-heredados.html` y `controles-calidad-bancaria.html`.
El detalle interno de cada componente está en la wiki del repositorio, `docs/wiki/README.md`.

En la aplicación, *Administración → Documentación* muestra este manual, la wiki, `docs/architecture/README.md` y los
diagramas, solo a los administradores de datos y con cada lectura auditada (`api/discovery_data_agent_api/documentation.py`,
`web/src/components/docs-viewer.tsx`). Los documentos de fuera de esa lista se ven como ruta, sin enlace. Si un
compañero no ve la pestaña, su login no tiene el rol `data_admin`: en desarrollo se añade a `DISCOVERY_DATA_AGENT_ADMINS`.

### 2.2 El núcleo (`src/discovery_data_agent/`)
El código se ordena en cuatro capas y las dependencias apuntan hacia adentro: integración → aplicación → dominio ←
infraestructura. Lo comprueba `tests/test_architecture.py` y lo explica `docs/architecture/capas-backend.md`.

| Paquete | Capa | Para qué sirve |
|---|---|---|
| `models/` | Dominio | Formas de los datos: objeto del catálogo, conocimiento, intención, respuesta (`AnswerEnvelope`), identidad del usuario |
| `catalog/` | Dominio | El catálogo y el conocimiento en memoria (`Catalog`, `KnowledgeBase`, `CatalogSnapshot`) y los puertos de su almacenamiento |
| `discovery/` | Dominio | La lógica determinista del descubrimiento: recuperar, medir cobertura, calcular confianza, agrupar, guardas. También el clasificador de intención por reglas y la expansión de la consulta |
| `graph/` | Dominio | Grafo del patrimonio en memoria: llaves foráneas, la misma entidad en varias BDs y caminos para unir tablas |
| `curation.py` | Dominio | Reglas de la curación: plantilla sin literales, regla de votos, ediciones de descripciones, plan de un diccionario |
| `builder/` | Dominio | Pasos del Builder: convertir metadatos, marcar datos personales por nombre, conservar lo humano, detectar entidades y linaje de vistas |
| `memory/` | Dominio e infraestructura | Texto (tokens, literales) y el índice léxico BM25 en memoria. Aplica el filtro de permisos antes de ordenar |
| `flows/` | Aplicación | Los dos grafos de LangGraph: `discover.py` (responder una pregunta) y `catalog_build.py` (construir el catálogo) |
| `ask/` | Dominio e infraestructura | Fase 1b del AskFlow (`features.ask_llm_sql`, apagada por defecto): responde lo que las cifras de plantilla (`discovery/figures.py`, decisión 17) no pueden, con SQL de un LLM. Corre después de `compute` y solo si no hubo cifra. `engine.py` arma el esquema, corrige hasta 3 veces y rellena la frase con el resultado (el LLM nunca lo ve); `validator.py` deja pasar solo un `SELECT` sobre tablas visibles e inyecta `TOP`; `planner.py` es el planner con LLM (rol `coder`). El ejecutor (`api/converdata_api/executor.py`) pasa por los mismos controles que las cifras (`runtime._run_ask`): servidor autorizado, tope diario, concurrencia y auditoría previa |
| `application/` | Aplicación | Casos de uso compartidos: herramientas de descubrimiento (las usan el MCP y la compuerta; las rutas REST llaman al flujo directamente) y refresco del catálogo (el mismo para la CLI y la API) |
| `storage/` | Infraestructura | Adaptadores de la BD `DiscoveryDataAgent`: conexión, migraciones, catálogo, curación. Y los mismos puertos sobre archivos, solo para desarrollo |
| `audit/` | Dominio e infraestructura | Registro de auditoría: en SQL Server (solo inserción) o en archivos con cadena de hashes |
| `metadata/` | Infraestructura | Lectura de metadatos de SQL Server con consultas fijas a `sys.*` |
| `identity/` | Dominio | La consulta que dice qué objetos puede leer un login |
| `llm/` | Infraestructura | Gateway de modelos: resuelve cada rol a un proveedor, aplica respaldo y corte por fallos, y rechaza proveedores no aptos para datos reales |
| `observability/` | Infraestructura | Logs JSON con lista blanca de campos y contadores para el monitoreo. Sin texto de preguntas |
| `evaluation/` | Integración | `eval discovery` (acierto por tipo de pregunta) y `eval gate` (la compuerta de siete suites) |
| `integration/mcp/` | Integración | Servidor MCP: por HTTP dentro de la API y por stdio para desarrollo |
| `bootstrap.py`, `cli.py` | Integración | Raíz de composición (ensambla el flujo y abre los almacenes) y la línea de comandos `discovery-data-agent` |

### 2.3 La API (`api/discovery_data_agent_api/`)

| Módulo | Para qué sirve |
|---|---|
| `main.py` | Todas las rutas y sus comprobaciones de rol |
| `runtime.py` | Estado del proceso: catálogo cargado, visibilidad de cada sesión, escrituras de curación, votos y la construcción del catálogo |
| `security.py` | Cabeceras, control de origen, tope de tamaño, bloqueo por intentos fallidos y las condiciones para arrancar en qa y prod |
| `vault.py` | Sesiones en memoria con las credenciales SQL cifradas con una clave que se genera al arrancar |
| `connector.py` | Conexiones a SQL Server con la credencial del usuario. Incluye el conector simulado del modo demo |
| `curation.py` | Responsables, dudas escaladas y su aviso; cola de revisión y tablero de métricas |
| `pii.py` | Detector de datos personales en lo que escribe un responsable |
| `tokens.py` | Tope diario de tokens de LLM por usuario |
| `audit.py`, `mcp_mount.py`, `settings.py` | Auditoría en archivos (desarrollo), montaje de `/mcp` y ajustes por variables de entorno |
| `demo.py`, `demo_history.py` | Modo demo: servidores simulados y actividad de ejemplo. No se admite en qa ni en prod |

### 2.4 La BD `DiscoveryDataAgent`

| Esquema | Qué guarda | Quién lo escribe |
|---|---|---|
| `catalog` | Objetos, columnas y llaves con historial y autor; versión del catálogo; inventario de servidores | API y Builder (el inventario, solo la API) |
| `knowledge` | Fragmentos, reglas, linaje, entidades y confirmaciones como plantilla sin literales | API; el Builder solo entidades y linaje |
| `curation` | Responsables, dudas escaladas y votos | API |
| `golden` | Texto original de una confirmación, solo si no traía literales | API (insertar) |
| `audit` | Preguntas, pasos, candidatos, votos y eventos | API y CLI (insertar); la purga, con su propio rol |

Cuatro roles de mínimo privilegio: `discovery_data_agent_app`, `discovery_data_agent_builder`, `discovery_data_agent_auditor` y
`discovery_data_agent_maintenance`. Los cambios de esquema van siempre en un script nuevo de `db/discovery_data_agent/`; uno ya aplicado no
se edita. Detalle en `docs/specs/on-premise/OP-02-catalogo-memoria.md`.

### 2.5 Lo que rodea al código

| Pieza | Para qué sirve |
|---|---|
| `tests/`, `api/tests/` | Pruebas. Las marcadas `sqlserver` crean y eliminan su propia BD y necesitan `DISCOVERY_DATA_AGENT_TEST_DB` |
| `tests/fixtures/*/eval/` | Sets de evaluación y sus líneas base. `reportes.yaml` mide el aporte del conocimiento y `chat.yaml` el chat de negocio (se corre aparte de la compuerta con `--cases`) |
| `requirements/*.lock` | Dependencias de Python con versión y hash. `requirements/README.md` dice cómo regenerarlas |
| `.github/workflows/calidad.yml` | CI: pruebas y compuerta, web, y análisis de dependencias con SBOM |
| `.claude/agents/` | Revisores automáticos: seguridad de datos, arquitectura y specs, contrato web-API, evaluador del descubrimiento |
| `tools/archify/` | Generador de los diagramas a partir de `docs/architecture/*.archify.json` |

## 3. Cómo viaja una pregunta
1. La web envía la pregunta a `/discover`. La identidad sale del token de sesión, nunca de un parámetro.
2. La API comprueba el ritmo y el tope de tokens del usuario, y lee de SQL Server qué objetos ve su login (se recuerda 15 minutos).
3. **intent**: qué se pide y de qué tipo (columna, tabla, regla). Por reglas, o con LLM si se declara el rol `planner`. Aquí también se contestan sin buscar las preguntas sobre el propio asistente y la cortesía (textos fijos), se completan los seguimientos con el historial y se rechazan las órdenes de modificar datos (solo mirando la pregunta actual).
4. **retrieve**: búsqueda léxica en el catálogo y el conocimiento, solo entre lo visible. **grade** reformula una vez si lo encontrado es pobre, con el LLM (rol `fast`) cuando lo hay.
5. **rerank**: ordena los candidatos. El LLM solo interviene si el resultado determinista no es claro.
6. **expand**: añade ubicaciones por ambiente, reglas, responsables, linaje y caminos de unión. **review** corrige una vez si el principal no cumple lo pedido.
7. **compute** (solo con las cifras activas y una pregunta de totales): arma una consulta de plantilla fija con nombres del catálogo (desglose por una categoría de la tabla o de una tabla relacionada, con una sola unión) y la ejecuta con el login de la persona, tras auditarla. Si no puede calcular, lo dice.
8. **respond**: redacta la respuesta. Si el texto del modelo nombra algo que no está entre los candidatos, se sustituye por el texto determinista. El número de una cifra nunca lo redacta el modelo. Si no hubo candidatos, el LLM puede reconocer una pregunta sobre el asistente o proponer una aclaración en lenguaje de negocio.
9. **finalize**: escribe la auditoría. Solo entonces se entrega la respuesta.

Una edición de curación sigue el mismo patrón: comprobar el rol y el dominio, auditar, escribir las filas en la BD,
recargar el índice y responder. Un refresco del catálogo parte de lo publicado, lee los servidores y publica solo lo que
deriva de los metadatos, sin tocar lo que escribieron las personas.

## 4. Cómo trabajar

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes --only-binary :all: -r requirements/build.lock -r requirements/dev.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation --no-index -e .
.venv/Scripts/python -m pytest -q                      # sin DISCOVERY_DATA_AGENT_TEST_DB se omiten las pruebas de SQL Server
.venv/Scripts/python -m discovery_data_agent.cli eval gate       # la compuerta: debe aprobar en los dos catálogos
npm --prefix web ci && npm --prefix web run build
```

- **Antes de pedir revisión.** Si tocaste `storage/`, `audit/` o `db/`, corre las pruebas con `DISCOVERY_DATA_AGENT_TEST_DB`: la CI todavía no las ejecuta. Si tocaste `discovery/` o un set de evaluación, corre `eval discovery` en los dos catálogos y prueba además con preguntas que no estén en el set.
- **Revisores.** Tras tocar identidad, auditoría, almacenamiento, curación o la API, pasa `revisor-seguridad-datos` y `revisor-arquitectura-specs`. Tras cambiar una ruta o la web, `verificador-contrato-web-api`. Tras tocar el descubrimiento, `evaluador-descubrimiento`. Han encontrado fallos reales que las pruebas no veían.
- **Documentación viva.** El estado y el siguiente paso están en `docs/PLAN-desarrollo.md`; el de cada historia, en `docs/backlog/on-premise.md`. Se actualizan en el mismo cambio que el código.
- **Dependencias.** Una dependencia nueva exige regenerar el bloqueo y pasar el análisis de vulnerabilidades, en un cambio aparte.

## 5. Mejoras que faltan

### 5.1 Bloques del plan

| Bloque | Qué falta | Depende de |
|---|---|---|
| **D · Métricas** | Comando `discovery-data-agent metrics report`, vistas SQL del scorecard y reporte de brechas por dominio | Nadie |
| **E · Fuentes de conocimiento** | Diccionario en Excel, documentos con redacción de datos personales y linaje desde SSIS | Documentos del dominio y acceso a SSISDB |
| **F · Instalación** | Scripts de `deploy/windows/` para IIS, tareas programadas del refresco, la purga y la evaluación, respaldo y restauración | Un Windows Server para validarlos, gMSA |
| **G · LLM y calidad real** | Probar Bedrock de punta a punta, repetir la compuerta con el modelo real y reunir 50–80 preguntas de usuarios | Cuenta AWS y un responsable del dominio |
| **H · Piloto** | Línea base, ocho semanas con 10–15 usuarios e informe. Roles desde grupos de Active Directory | El banco |

### 5.2 Deudas técnicas
El registro completo está en `docs/wiki/deuda-tecnica.md`: 66 deudas abiertas comprobadas contra el código, con evidencia,
gravedad, esfuerzo y cómo se cierran. Estas son las 8 de gravedad alta:

| ID | Deuda | Por qué importa |
|---|---|---|
| DT-04 | La fecha de un registro de auditoría la fija quien lo inserta | Una cuenta comprometida podría antedatar filas para que caigan en la purga |
| DT-05 | El detector de datos personales reconoce seis formatos y no nombres ni direcciones | De él depende lo que escribe un responsable; la plantilla de las confirmaciones tampoco reconoce nombres |
| DT-29 | Los sets de evaluación los escribió el equipo | Los porcentajes no predicen el uso real |
| DT-30 | Nada se ha medido con el modelo real | Bedrock sin probar de punta a punta; las suites de inyección y guardas solo corrieron sin modelo |
| DT-33 | La purga de 180 días existe y `deploy/windows/registrar-tareas.ps1` la programa, pero el script no se ha probado en un servidor | Retención |
| DT-39 | Las pruebas de SQL Server (83 de 458) no corren en la CI | Una regresión en el esquema o en los adaptadores no se ve en un PR |
| DT-44 | No hay instalación para Windows Server | Sin IIS, tareas programadas ni respaldo no hay piloto |
| DT-45 | La CI no construye ni analiza la imagen | Cadena de suministro |

El 2026-11-17 se cerraron DT-01, DT-03, DT-08, DT-57 y DT-67, y DT-02 bajó a gravedad media: queda activar
`TRUST_FORWARDED_FOR` (web) y `DISCOVERY_DATA_AGENT_TRUST_PROXY` (API) detrás de IIS, en el bloque F.

Las brechas frente al PRD y las specs están en `docs/wiki/brechas-funcionales.md`, y el orden para cerrarlas en
`docs/wiki/hoja-de-ruta-on-premise.md` y `docs/wiki/hoja-de-ruta-cloud.md`.

### 5.3 Decisiones que debe tomar el banco
- Qué validación hace falta para dar un rol por el nombre del login. Hoy se exige haberlo validado en un servidor de producción.
- Si un responsable puede ver y editar, dentro de sus dominios, activos que su login no puede leer.
- Qué lecturas se auditan además de las preguntas: fichas, catálogo y herramientas MCP.
- Si se usa Guardrails de Bedrock y quién revisa la batería de inyección de prompt.

### 5.4 Límites de lo medido
- Los sets de evaluación los escribió el equipo: 89 preguntas de descubrimiento, 25 de reporte y 67 de chat. Los porcentajes no predicen el uso real.
- Todo se midió sin LLM. Falta repetirlo con Bedrock, incluidos los pasos nuevos del modelo (reformular, orientar y enriquecer el catálogo).
- Las cifras agregadas se verificaron contra un SQL Server local con datos ficticios. Su revisión de seguridad independiente terminó el 2026-11-23 sin encontrar inyección SQL ni fugas de permisos; sus dos bloqueantes se corrigieron (los totales y grupos de menos de 10 registros no se muestran y cada consulta se audita antes de ejecutarse), quedan abiertas DT-78 a DT-80 y no se han medido con usuarios reales.
- La prueba de literales marcados no cubre el cliente MCP, la respuesta por streaming ni el Visor de eventos de Windows.

## 6. Dónde está cada cosa

| Si buscas | Mira |
|---|---|
| Enfoque y arquitectura (C4) con sus diagramas | `docs/architecture/README.md` |
| Cada componente por dentro | `docs/wiki/README.md` |
| Deuda técnica revisada contra el código | `docs/wiki/deuda-tecnica.md` |
| Brechas frente al PRD y las specs | `docs/wiki/brechas-funcionales.md` |
| Hojas de ruta on-premise y cloud | `docs/wiki/hoja-de-ruta-on-premise.md`, `docs/wiki/hoja-de-ruta-cloud.md` |
| Qué se decidió y por qué | `docs/PRD.md` §13 |
| Estado, resultados medidos y siguiente paso | `docs/PLAN-desarrollo.md` |
| Historias de usuario y su estado | `docs/backlog/on-premise.md` |
| Reparto del trabajo pendiente | `docs/backlog/reparto-5-devs.md` |
| Controles de seguridad y lo que no está resuelto | `docs/calidad-bancaria.md` |
| Cómo debe comportarse cada pieza | `docs/specs/comun/` (F01–F25) y `docs/specs/on-premise/` (OP-01–OP-07) |
| Capas del backend | `docs/architecture/capas-backend.md` |
| Instalación y operación | `docs/specs/on-premise/OP-07-instalacion-operacion.md` |
| Dependencias fijadas | `requirements/README.md` |
