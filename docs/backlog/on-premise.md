# Backlog — versión on-premise (fase 0 + fase 1a)

> Creado: 2026-10-27. Documento vivo: se actualiza al cerrar cada sprint.
> Base: [PRD](../PRD.md) §6, §10 y §11 · [OP-01](../specs/on-premise/OP-01-despliegue-local.md) a [OP-06](../specs/on-premise/OP-06-residencia-datos.md) · [F25](../specs/comun/F25-success-metrics.md) · [plan de desarrollo](../PLAN-desarrollo.md).
>
> Las marcas **⚠️ SUPUESTO** son plazos, capacidades o métricas que no se deducen del repo. Hay que confirmarlas antes de
> comprometer fechas; la lista completa está en la [§5](#5-supuestos-a-confirmar).

## 1. Alcance de esta versión
"Versión on-premise terminada" significa: **el piloto de descubrimiento (fase 1a de OP-01) corre en el Windows Server del banco,
sobre la BD `ConverData` en SQL Server 2025, con 10–15 usuarios reales, y se evalúa contra D1–D7**. ⚠️ SUPUESTO S1.

| Dentro | Fuera (otra versión) |
|---|---|
| Fase 0 (preparación y línea base) y fase 1a (descubrimiento) de PRD §10 | Fase 1b: AskFlow, F4–F10, F20, F21 (RF-40 a RF-42) |
| Requisitos P0 de PRD §6.1–6.3 y 6.5, y los P1 que exigen las specs OP para el piloto (MCP, linaje SSIS) | Alta disponibilidad del servidor de aplicación, SSO con Kerberos (OP-03 §Evolución) |
| Cierre de los huecos de specs OP frente a CN | Migración a cloud native (CN-01 a CN-06) |

### Punto de partida (2026-10-27)
Ya hecho y probado (81 tests): DiscoverFlow (F22), agente de esquemas (F1, F18, F19), grafo del patrimonio en memoria, gateway de LLM
(Ollama probado; NIM y Bedrock sin probar), evaluación offline, `VisibilityResolver` y auditoría en memoria.
Escritos pero sin validar: DDL de la BD `ConverData` y `SqlServerVectorStore`.
Hecho el 2026-10-27, pendiente de revisión: épica E0 (HU-01 a HU-03), es decir, [OP-07](../specs/on-premise/OP-07-instalacion-operacion.md)
y los parches a OP-01, OP-03, OP-04, OP-05 y OP-06.
Pendiente: el resto de este backlog.

## 2. Objetivos SMART
| ID | Objetivo (específico) | Medida de cumplimiento | Alcanzable porque… | Relevante para | Plazo | Specs |
|---|---|---|---|---|---|---|
| **O1** | Specs on-premise completas y coherentes con CN: crear OP-07 (instalación y operación) y cerrar los huecos de OP-01 a OP-06 | Las 9 brechas de la revisión del 2026-10-27 (§6) cerradas o con decisión registrada; 0 contradicciones abiertas entre OP-01 y OP-04 | Es trabajo de documentación sobre specs ya maduras | Desbloquea instalación, seguridad y criterios de aceptación de todo lo demás | 2026-11-13 ⚠️ S2 | OP-01…OP-07, F17 |
| **O2** | La BD `ConverData` en SQL Server 2025 es el almacén de trabajo: catálogo con historial, grafo, conocimiento y vectores | CA 1–5 y 8 de OP-02 en verde contra una instancia SQL Server 2025; búsqueda híbrida con Hit@3 en BD ≥ Hit@3 en memoria (±1 punto) en el set de BancosSQL | El DDL y `SqlServerVectorStore` ya existen; falta validarlos y completar `estate` y `semantic` | Sin persistencia no hay piloto multiusuario ni historial (RF-34) | 2026-12-11 ⚠️ S2, S5 | OP-02, F1, F2, F19 |
| **O3** | Cada usuario descubre solo lo que su login SQL puede leer, de punta a punta por la API | CA 1–4 de OP-03 y CA 1, 4, 5 y 6 de F14 en verde con dos logins de prueba en dos servidores; **0 fugas** en el set de evaluación | `VisibilityResolver` ya calcula `visible_ids`; falta la sesión y la custodia | D6 de OP-01 (0 fugas) es criterio de salida | 2026-12-11 ⚠️ S2 | OP-03, F14 |
| **O4** | Interfaces publicadas en IIS: chat, API, MCP y administración de ingesta | CA 1–7 de OP-04 en verde en el servidor de piloto | FastAPI, Chainlit y FastMCP son librerías estándar; el contrato está en F12 | RF-50, RF-51, RF-52; los usuarios no usan el CLI | 2027-02-05 ⚠️ S2 | OP-04, F12 |
| **O5** | Toda pregunta queda auditada en SQL Server y el servicio es observable sin contenido | CA 1–5 de OP-05 y CA 1, 3, 4 y 5 de F11 en verde; test de logs con 0 preguntas, SQL o filas | El modelo de F11 ya está en el DDL | RF-53; base de las métricas de F25 | 2027-01-08 ⚠️ S2 | OP-05, F11, F17 |
| **O6** | El conocimiento del dominio clientes / onboarding digital está ingerido con PII redactada | CA 1–5 de F23 y CA 7 de OP-02; CA 3 de OP-06 (0 DUI ni cuentas de prueba en `knowledge`) | Presidio y los conectores son piezas acotadas; el dominio piloto es pequeño | RF-22, RF-23, RF-25; sin ellos la confianza depende de texto IA (tope 0.6) | Semana 3 del piloto (2027-02-26) ⚠️ S2, S6 | F23, OP-02, OP-06 |
| **O7** | El conocimiento de los expertos se captura desde el uso | CA 1–5 de F24 y CA 6–7 de OP-04 en verde | El ciclo ✔/✖ y `golden_discovery` ya tienen tablas | RF-30 a RF-33; objetivo de negocio −30 % consultas a expertos | 2027-01-22 ⚠️ S2 | F24, OP-04 |
| **O8** | Calidad del descubrimiento lista para el piloto con el LLM real | En un set de 50–80 preguntas reales: Hit@3 ≥ 85 %, Hit@1 ≥ 65 %, calibración ≥ 85 %, 0 inventados, p50 < 5 s y p95 < 10 s con Bedrock | Hoy: Hit@3 82,8 % en 31 casos sintéticos; faltan embeddings y vocabulario | D1, D2 y D5 de OP-01 | Inicio del piloto (2027-02-08) ⚠️ S2, S7 | F22, F25, OP-01 |
| **O9** | Instalación y operación reproducibles en Windows Server | Instalación desde cero en un servidor limpio con los scripts de OP-07 en ≤ 1 día laboral ⚠️ S8; restauración de la BD `ConverData` probada; un proceso caído se reinicia solo (OP-04 CA5) | Todo es stack Microsoft que el equipo ya opera | Sin esto no hay entorno de piloto ni camino a producción on-premise | 2027-02-05 ⚠️ S2 | OP-01, OP-07 |
| **O10** | Piloto de 8 semanas ejecutado y decisión de escalar tomada | Línea base firmada antes de empezar; informe con D1–D7 de OP-01 y las 4 métricas de negocio de F25 | Plan de 8 semanas ya definido en F25 | Es la hipótesis central de OP-01 | Línea base: 2027-02-05 · Decisión: 2027-04-09 ⚠️ S2, S9 | OP-01, F25 |

## 3. Plan de entregas
⚠️ SUPUESTO S2/S3: sprints de 2 semanas desde el 2026-11-02, velocidad de 25 puntos por sprint (2 desarrolladores), sin capacidad del
2026-12-21 al 2027-01-01. Las *Must* suman 146 puntos: con esa velocidad hacen falta 6 sprints.

| Sprint | Fechas | Foco | Historias | Puntos | Objetivos |
|---|---|---|---|---|---|
| 1 | 2026-11-02 → 11-13 | Specs y cimientos de persistencia | HU-01, HU-02, HU-03, HU-04, HU-05, HU-34 | 20 | O1, O2, O8 |
| 2 | 2026-11-16 → 11-27 | Identidad, escritura del catálogo y Bedrock | HU-06, HU-10, HU-11, HU-12, HU-35 | 24 | O2, O3, O8 |
| 3 | 2026-11-30 → 12-11 | API y auditoría | HU-09, HU-14, HU-15, HU-20, HU-21 | 24 | O2, O3, O4, O5 |
| 4 | 2026-12-14 → 12-18 y 2027-01-04 → 01-08 | Chat, métricas y curación | HU-17, HU-23, HU-29, HU-30 | 23 | O4, O5, O7 |
| 5 | 2027-01-11 → 01-22 | Roles, ingesta y vista Curación | HU-13, HU-18, HU-28, HU-31, HU-33 | 26 | O3, O4, O6, O7, O8 |
| 6 | 2027-01-25 → 02-05 | Instalación en el servidor del piloto y MCP; línea base en paralelo (HU-40) | HU-16, HU-25, HU-37, HU-38, HU-40 | 26 | O4, O6, O9, O10 |
| Piloto | 2027-02-08 → 04-02 | Semanas 1–8 de F25; ingesta de documentos y linaje del dominio en las semanas 1–3 | HU-26, HU-27, HU-41 y las *Should* que quepan | 21 | O6, O10 |

Las historias *Should* y *Could* no listadas (HU-07, HU-08, HU-19, HU-22, HU-24, HU-32, HU-36, HU-39) entran por capacidad sobrante
o durante el piloto; HU-36 es condición para declarar O8 completo. HU-16 (*Should*) va en el sprint 6 porque OP-04 CA3 la exige.

## 4. Épicas e historias de usuario
Prioridad **MoSCoW** para esta versión. Estimación relativa en **puntos de historia** (Fibonacci: 1, 2, 3, 5, 8, 13).
Roles: los de PRD §4, más *consumer*, *steward*, *data_admin* y *auditor* de F11/F24.

### Resumen
| Épica | Historias | Must | Should | Could | Puntos |
|---|---|---|---|---|---|
| E0 Specs on-premise | HU-01 a HU-03 | 3 | — | — | 7 |
| E1 Persistencia en la BD `ConverData` | HU-04 a HU-09 | 4 | 1 | 1 | 34 |
| E2 Identidad y permisos heredados | HU-10 a HU-13 | 3 | 1 | — | 18 |
| E3 Interfaces | HU-14 a HU-19, HU-42 | 4 | 2 | 1 | 34 |
| E4 Auditoría y observabilidad | HU-20 a HU-24 | 3 | 2 | — | 19 |
| E5 Fuentes de conocimiento | HU-25 a HU-28 | 3 | 1 | — | 24 |
| E6 Curación y aprendizaje | HU-29 a HU-32 | 3 | 1 | — | 21 |
| E7 Calidad del descubrimiento | HU-33 a HU-36 | 3 | 1 | — | 14 |
| E8 Instalación y operación | HU-37 a HU-39 | 2 | 1 | — | 15 |
| E9 Piloto | HU-40, HU-41 | 2 | — | — | 8 |
| **Total** | **42** | **30** | **10** | **2** | **194** |

*Won't (esta versión)*: AskFlow y fase 1b, código Python libre (F20), `candidates: 2`, SSO con Kerberos, alta disponibilidad del
servidor de aplicación, fallback automático a NIM con datos reales (OP-01 §Fuera del alcance).

---

### E0 · Specs on-premise completas (O1)
> **Estado (2026-10-27):** redactadas, pendientes de revisión por la usuaria, Plataformas y Seguridad de la Información. Los valores
> marcados "⚠️ propuesto" en OP-07 (disponibilidad, RPO/RTO y tiempo de reinstalación) siguen abiertos.

#### HU-01 · Spec OP-07 de instalación, entornos y operación
**Como** administrador de Plataformas **quiero** una spec que describa instalación, entornos, requisitos no funcionales, respaldo y
actualización del despliegue on-premise **para** montar y operar el servidor del piloto sin depender del equipo de desarrollo.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | HU-03 | O1, O9 | OP-07 (nueva), equivalente de CN-01 §Entornos, §Requisitos no funcionales e IaC |

- **Dado** OP-07 publicada, **cuando** se compara con CN-01, **entonces** cubre entornos (dev/QA/prod on-prem), disponibilidad, RPO/RTO de
  la BD `ConverData`, scripts de instalación, actualización y rollback.
- **Dado** OP-01, **cuando** se lee su tabla de specs relacionadas, **entonces** enlaza OP-07 y el PRD (anexo A) la lista.

#### HU-02 · Cerrar los huecos de seguridad y residencia en OP-03 a OP-06
**Como** responsable de Seguridad de la Información **quiero** que las specs on-premise tengan los mismos controles que cloud native
**para** aprobar el envío de metadatos y preguntas a Bedrock con el mismo nivel de garantía.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 2 | — | O1 | OP-03, OP-04, OP-05, OP-06, F17 |

- **Dado** OP-01 y OP-06, **cuando** se revisan, **entonces** definen Bedrock Guardrails (`ApplyGuardrail` por el proxy) en entradas y salidas.
- **Dado** OP-04, **cuando** se revisa, **entonces** incluye el límite de tokens por usuario y día y los CA de streaming y de `discover` por MCP.
- **Dado** OP-03 y OP-05, **cuando** se revisan, **entonces** incluyen los CA "A no obtiene la credencial de B manipulando argumentos MCP",
  "fail-closed con alerta si la BD `ConverData` no responde" y alertas de p95 y de throttling de Bedrock.
- **Dado** OP-06, **cuando** se revisa, **entonces** tiene filas para volcados de memoria y WER, pagefile, temporales del servicio, respaldos de
  la BD `ConverData` y ediciones de curación con PII.

#### HU-03 · Decidir el modelo de procesos en IIS
**Como** administrador de Plataformas **quiero** una decisión única sobre cómo corren `ConverData-UI`, `-API` y `-Builder` **para** no
instalar servicios de Windows y procesos de HttpPlatformHandler a la vez y evitar que IIS recicle un batch largo.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 2 | — | O1, O9 | OP-01 §Decisiones, OP-04 §IIS |

- **Dado** OP-01 y OP-04, **cuando** se leen, **entonces** describen un solo modelo (por ejemplo, UI y API bajo HttpPlatformHandler y Builder
  como servicio de Windows con IIS como proxy) sin contradicciones.
- **Dado** el Builder, **cuando** una ingesta dura más que el *idle timeout* de IIS, **entonces** la spec garantiza que no se interrumpe.

---

### E1 · Persistencia en la BD `ConverData` (O2)

#### HU-04 · Completar el DDL de la BD `ConverData`
**Como** DBA **quiero** un DDL con todos los esquemas de OP-02 y sus permisos **para** crear la BD del piloto con un solo script revisable.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | — | O2 | OP-02 §BD de trabajo, OP-05 |

- **Dado** `db/converdata/`, **cuando** se revisa, **entonces** incluye los esquemas `estate` (tablas `AS NODE` / `AS EDGE`) y `semantic` además de
  los actuales, y un rol para `ConverData-Builder` con escritura en `catalog`, `estate` y `knowledge`.
- **Dado** el rol `converdata_app`, **cuando** intenta `UPDATE` o `DELETE` en `audit`, **entonces** SQL Server lo deniega.
- **Dado** el rol `auditor`, **cuando** consulta `audit`, **entonces** tiene `SELECT` y nada más.

#### HU-05 · Validar el DDL y `SqlServerVectorStore` en SQL Server 2025
**Como** desarrollador **quiero** ejecutar los tests de contrato de `VectorStore` contra SQL Server 2025 **para** confirmar que `VECTOR`,
Full-Text y RRF en T-SQL funcionan como en memoria.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-04, instancia SQL Server 2025 de desarrollo ⚠️ S5 | O2 | OP-02 CA 1, 3, 4 y 8 |

- **Dado** una instancia SQL Server 2025 con el DDL aplicado, **cuando** corren los tests de contrato, **entonces** pasan para `search_tables`,
  `search_columns`, `search_knowledge` y `search_golden_discovery`.
- **Dado** un usuario sin acceso a `RRHH`, **cuando** busca, **entonces** no recibe objetos de `RRHH` (filtro `visible_ids` antes del ranking).
- **Dado** el set de BancosSQL, **cuando** se evalúa con el almacén en BD, **entonces** Hit@3 difiere ≤ 1 punto del almacén en memoria.

#### HU-06 · Escribir el catálogo en la BD `ConverData` con historial
**Como** steward **quiero** que el catálogo viva en tablas con historial temporal **para** ver quién cambió una descripción y cuándo.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-05 | O2 | OP-02 §Ingesta, CA 2 y 5; F1; RF-34 |

- **Dado** `converdata catalog build` contra la instancia de desarrollo, **cuando** termina, **entonces** `catalog` tiene servidores, BDs,
  objetos, columnas y FKs, y los vectores están indexados.
- **Dado** una descripción editada, **cuando** se consulta el historial temporal, **entonces** aparece la versión anterior y quién la cambió.
- **Dado** un refresco posterior, **cuando** termina, **entonces** no sobrescribe ninguna edición `human` (F24 CA3).
- **Dado** el test de literales marcados, **cuando** se ejecuta, **entonces** ninguna tabla fuera de `audit`, `golden` y `curation` contiene valores.

#### HU-07 · Grafo del patrimonio en tablas de grafo
**Como** ingeniero de datos **quiero** que entidades, copias y caminos entre BDs se guarden en el esquema `estate` **para** que persistan entre
reinicios y el steward pueda revisarlos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 8 | HU-04, HU-06 | O2 | OP-02 §`estate`, F19 |

- **Dado** un catálogo construido, **cuando** termina la etapa `relate`, **entonces** las entidades y aristas (FK, misma entidad, linaje) quedan en
  tablas `NODE`/`EDGE`.
- **Dado** el grafo en BD, **cuando** se evalúan los tipos C y D del set de BancosSQL, **entonces** los resultados son iguales a los del grafo en memoria.
- **Dado** los sketches MinHash, **cuando** termina el job, **entonces** no quedan escritos en ninguna tabla.

#### HU-08 · Exportar el catálogo a YAML
**Como** data_admin **quiero** `converdata catalog export` **para** revisar cambios de `catalog`, `estate` y `semantic` en pull requests.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Could | 3 | HU-06 | O2 | OP-02 §Versionado en git |

- **Dado** la BD `ConverData` con catálogo, **cuando** se ejecuta el export, **entonces** genera YAML con el formato de `tests/fixtures/*/catalog`
  que `load_catalog` vuelve a leer sin diferencias.

#### HU-09 · Ensamblar el DiscoverFlow desde la BD `ConverData`
**Como** desarrollador **quiero** que `ConverData-API` cargue catálogo, conocimiento y responsables desde la BD **para** que el servicio no
dependa de archivos YAML en el servidor.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-06 | O2, O4 | OP-02, `bootstrap.py` |

- **Dado** la configuración de conexión a `ConverData`, **cuando** arranca el servicio, **entonces** usa `SqlServerVectorStore` y los esquemas de la BD.
- **Dado** el modo de desarrollo, **cuando** se pasa `--root`, **entonces** sigue funcionando con YAML y `InMemoryVectorStore` (los 81 tests actuales siguen en verde).

---

### E2 · Identidad y permisos heredados (O3)

#### HU-10 · Iniciar sesión con login SQL por servidor
**Como** analista BI **quiero** iniciar sesión con mi login SQL en los servidores del piloto **para** descubrir solo lo que ya puedo consultar.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-11, HU-12 | O3 | OP-03 §Decisión, OP-04 §API, F14 |

- **Dado** credenciales válidas para producción y QA, **cuando** llamo a `POST /login`, **entonces** recibo `session_id`, `expires_at`,
  `servers: [{alias, ok}]` y `databases[]`.
- **Dado** "usar la misma credencial en los servidores marcados", **cuando** inicio sesión, **entonces** se valida en cada servidor por separado y
  los que fallan quedan con `ok: false`.
- **Dado** una contraseña incorrecta, **cuando** inicio sesión, **entonces** recibo un error sin indicar qué objetos existen en el servidor.

#### HU-11 · Custodia de credenciales en `SessionVault`
**Como** responsable de Seguridad de la Información **quiero** que las contraseñas solo vivan cifradas en memoria **para** que no queden en
disco, logs ni BD.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | — | O3 | OP-03 §Custodia, CA 2 y 3 |

- **Dado** una sesión activa, **cuando** pasan 8 h sin actividad, **entonces** expira; con actividad, la expiración se desliza.
- **Dado** `POST /logout` o un reinicio del servicio, **cuando** se usa el `session_id` anterior, **entonces** la API devuelve 401.
- **Dado** un flujo completo de login y descubrimiento, **cuando** se inspeccionan logs, Visor de eventos y BD, **entonces** no aparece la contraseña.
- **Dado** el vault, **cuando** se lee su estado interno, **entonces** la contraseña está cifrada con Fernet y una clave efímera del proceso.

#### HU-12 · Conexiones con la credencial del usuario
**Como** DBA **quiero** que todas las conexiones de usuario lleven `ApplicationName=ConverData` y `Encrypt=yes` **para** filtrar su
actividad en SQL Server Audit.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | HU-11 | O3, O5 | OP-03 §Custodia y CA 4, OP-05 §Rastro |

- **Dado** una sesión, **cuando** `ConnectionFactory.for_session(session_id, database)` conecta, **entonces** la cadena ODBC lleva `Encrypt=yes`
  y `ApplicationName=ConverData`, y la contraseña solo se descifra durante `pyodbc.connect`.
- **Dado** el login, **cuando** `VisibilityResolver` calcula `visible_ids`, **entonces** usa esa conexión (no el login de metadatos).
- **Dado** SQL Server, **cuando** el DBA consulta las sesiones, **entonces** las de ConverData tienen `program_name = 'ConverData'` y el login del usuario.

#### HU-13 · Grupos y roles desde Active Directory
**Como** data_admin **quiero** que los roles `steward` y `data_admin` se asignen a grupos de AD **para** no mantener roles login por login.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 5 | HU-10, acceso LDAP de solo lectura ⚠️ S10 | O3, O7 | OP-03 §Grupos, OP-04 §API, F24 |

- **Dado** un login asociado en `curation.user_directory`, **cuando** inicia sesión, **entonces** la sesión tiene los grupos de su cuenta de AD.
- **Dado** un login sin asociación, **cuando** inicia sesión, **entonces** `groups = []` y solo tiene el rol `consumer` (salvo asignación directa en `curation.owners`).

---

### E3 · Interfaces (O4)

#### HU-14 · API REST de descubrimiento
**Como** ingeniero de datos **quiero** llamar a `/api/discover` y `/api/assets/{asset_key}` **para** integrar el descubrimiento en mis
herramientas.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-09, HU-10, HU-20 | O4 | OP-04 §API, F12, RF-51, RF-10 |

- **Dado** un `Bearer` válido, **cuando** envío una pregunta a `/api/discover`, **entonces** recibo un `AnswerEnvelope` con `flow=discover`.
- **Dado** que no envío token, **cuando** llamo a cualquier ruta de `/api` salvo `/login`, **entonces** recibo 401 (OP-04 CA2).
- **Dado** 31 preguntas en un minuto en la misma sesión, **cuando** envío la 31.ª, **entonces** recibo 429.
- **Dado** un origen distinto del sitio, **cuando** el navegador hace una petición CORS, **entonces** se rechaza.
- **Dado** `/api/assets/{asset_key}` de un activo no visible, **cuando** lo pido, **entonces** recibo 404 sin revelar que existe.

#### HU-15 · Confirmar o rechazar un candidato
**Como** analista BI **quiero** marcar "✔ Es este" o "✖ No es" **para** que la próxima persona encuentre el dato más rápido.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | HU-14, HU-20 | O4, O7 | OP-04 CA6, F12, F24, RF-30 |

- **Dado** una respuesta con candidatos, **cuando** envío `POST /api/discover/feedback` con `confirm`, **entonces** queda una fila en
  `audit.audit_discovery_feedback` con `time_to_verdict_ms`.
- **Dado** un `trace_id` de otro usuario, **cuando** envío feedback, **entonces** la API lo rechaza.

#### HU-16 · Herramientas MCP con la identidad de la sesión
**Como** ingeniero de datos que usa Claude Code **quiero** las herramientas `discover` y `get_asset` en `/mcp` **para** preguntar por datos
desde mi IDE.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 5 | HU-14 | O4 | OP-04 CA3, F12, RF-52 |

- **Dado** `.mcp.json` apuntando a `https://<servidor>/mcp` con un `Bearer` de `/login`, **cuando** invoco `discover`, **entonces** recibo un `AnswerEnvelope`.
- **Dado** un argumento de herramienta con otro `user_id` o `session_id`, **cuando** invoco la herramienta, **entonces** se ignora y se usa la
  identidad del `Bearer` (A no obtiene datos ni credenciales de B).

> **Estado (2026-10-27):** capa de herramientas (`converdata.application.discovery`) y servidor MCP HTTP con `require_bearer`
> (`converdata.integration.mcp.server`) hechos y probados con el cliente MCP oficial (`tests/test_mcp_server.py`). Falta montarlo
> en `/mcp` de `ConverData-API` con el SessionVault real y el nombre del servidor de IIS en `transport_security` (tras HU-14).

#### HU-17 · Chat Chainlit con tarjetas de candidatos
**Como** Product Owner **quiero** preguntar en un chat web y ver tarjetas con BD, ambiente, servidor, descripción, reglas, relaciones,
responsables y confianza **para** entender un dato sin depender de TI.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-14, HU-15 | O4 | OP-04 CA1 y CA6, F12, RF-50, PRD §5 |

- **Dado** que entro a `https://<servidor>/`, **cuando** inicio sesión con mi login SQL, **entonces** puedo preguntar y veo las tarjetas como en el
  ejemplo del README, con los botones "✔ Es este", "✖ No es", "Ver ficha" y "Ver relacionadas".
- **Dado** una respuesta en curso, **cuando** el flujo avanza, **entonces** el chat muestra los pasos en streaming.
- **Dado** Chainlit, **cuando** se revisa su configuración, **entonces** el data layer está desactivado (OP-06).

#### HU-18 · Administración de ingesta en `ConverData-Builder`
**Como** DBA **quiero** que el job de SQL Server Agent dispare `POST /api/admin/catalog/refresh` y `/api/admin/knowledge/ingest` **para**
mantener el catálogo al día cada noche sin intervención manual.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-03, HU-06 | O4, O9 | OP-02 §Ingesta y CA6, OP-04 CA4 |

- **Dado** el token de servicio, **cuando** el job llama a `/api/admin/catalog/refresh`, **entonces** el refresco se encola y el job registra éxito o fallo.
- **Dado** una IP fuera de la lista permitida, **cuando** llama a `/api/admin/*`, **entonces** recibe 403.
- **Dado** un refresco fallido, **cuando** termina el job, **entonces** Database Mail avisa al DBA.

#### HU-19 · Límite de tokens por usuario y día
**Como** data_admin **quiero** un tope diario de tokens por usuario **para** acotar el coste de Bedrock en el piloto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Could | 2 | HU-14, HU-02 | O4 | OP-04 (tras HU-02), CN-04 |

- **Dado** un usuario que alcanzó el tope configurado, **cuando** hace otra pregunta, **entonces** recibe un mensaje claro y el DiscoverFlow
  responde en modo determinista o rechaza, según la configuración.

#### HU-42 · Usar ConverData desde Claude con MCP
**Como** ingeniero de datos o analista que trabaja con Claude Desktop o Claude Code **quiero** conectar ConverData como servidor MCP
**para** preguntar dónde están los datos, ver fichas, reglas, linaje y caminos de unión sin salir de mi conversación con Claude.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | — (local); HU-16 (servidor) | O4 | F12, OP-04 CA3, [capas del backend](../architecture/capas-backend.md) |

- **Dado** `config/mcp.example.json` copiado a la configuración de Claude, **cuando** Claude arranca `converdata mcp serve --root <catálogo>`,
  **entonces** ve las 10 herramientas de lectura (`discover`, `get_asset`, `get_related`, `find_alternatives`, `list_business_rules`,
  `get_lineage`, `search_catalog`, `where_is`, `find_join_path`, `estate_overview`) y ninguna de escritura.
- **Dado** `CONVERDATA_ENV=qa` o `prod`, **cuando** se intenta arrancar el modo stdio, **entonces** se niega e indica usar `/mcp` con `Bearer`.
- **Dado** `--databases RRHH`, **cuando** Claude pide la ficha de `VBank_ING.dbo.Users.ClientCode`, **entonces** recibe `found: false`.
- **Dado** el servidor del piloto con HU-16, **cuando** Claude usa la entrada `converdata` (HTTP) con `Authorization: Bearer ${CONVERDATA_TOKEN}`,
  **entonces** las respuestas respetan los permisos del login SQL de esa sesión.

> **Estado (2026-10-27):** modo local (stdio) hecho y probado, incluido el arranque como proceso (`tests/test_mcp_stdio.py`). El modo HTTP
> depende de HU-16.

---

### E4 · Auditoría y observabilidad (O5)

#### HU-20 · Auditoría fail-closed en SQL Server
**Como** auditor **quiero** que cada pregunta deje su rastro en el esquema `audit` **para** reconstruir qué se preguntó, qué se mostró y con qué confianza.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-05 | O5 | OP-05 §Auditoría y CA1, F11 CA 1, 3, 4 y 5 |

- **Dado** una pregunta a `/api/discover`, **cuando** termina, **entonces** hay exactamente una fila en `audit.audit_question`, N en `audit_step` y una
  en `audit_discovery` por candidato, alternativa y relación, escritas en una sola transacción.
- **Dado** la BD `ConverData` caída y `audit.fail_open: false`, **cuando** llega una pregunta, **entonces** no se entrega la respuesta y queda un error
  en el Visor de eventos.
- **Dado** cualquier registro de auditoría, **cuando** se busca la contraseña de prueba, **entonces** no aparece.

#### HU-21 · Logs JSON sin contenido y Visor de eventos
**Como** administrador de Plataformas **quiero** logs estructurados y eventos de Windows **para** diagnosticar fallos sin ver preguntas ni datos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | — | O5 | OP-05 §Observabilidad y CA3, F17 (lista blanca D5) |

- **Dado** un flujo completo con una pregunta y un literal marcado, **cuando** se inspeccionan los logs JSON, el Visor de eventos (origen `ConverData`)
  y los logs de IIS, **entonces** no aparecen la pregunta, SQL, filas ni la cabecera `Authorization`.
- **Dado** los logs en disco, **cuando** superan el tamaño configurado, **entonces** rotan.

#### HU-22 · Contadores en `/health/metrics`
**Como** administrador de Plataformas **quiero** peticiones, latencia p50/p95, errores y tokens en `/health/metrics` **para** integrarlos en
el monitoreo existente (SCOM o Zabbix ⚠️ S11).

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-14 | O5 | OP-05 §Observabilidad |

- **Dado** tráfico en la API, **cuando** consulto `/health/metrics`, **entonces** veo los contadores sin ningún contenido de preguntas.

#### HU-23 · Scorecard y `converdata metrics report`
**Como** Gerencia de Datos **quiero** un reporte de métricas de negocio, adopción y calidad **para** comparar el piloto con la línea base.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-20, HU-15 | O5, O10 | OP-05 CA2, F25 CA2, RF-54 |

- **Dado** auditoría de al menos una semana, **cuando** ejecuto `converdata metrics report --from --to`, **entonces** obtengo CSV y HTML con tiempo
  hasta "✔", escalamientos, usuarios activos, % resueltas sin escalar y Hit@k del último set de evaluación.
- **Dado** el reporte, **cuando** se genera, **entonces** se calcula desde vistas del esquema `audit` sin leer el texto de preguntas ni SQL.

#### HU-24 · Jobs de mantenimiento y regresión
**Como** DBA **quiero** jobs de SQL Server Agent para la purga de 180 días y la evaluación semanal **para** cumplir la retención y detectar
regresiones sin acordarme de lanzarlas.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-20, HU-33 | O5, O8 | OP-05 §Auditoría y CA5, F25 CA3 |

- **Dado** registros de auditoría con más de 180 días, **cuando** corre el job de purga, **entonces** se eliminan y queda constancia en el historial del job.
- **Dado** una evaluación semanal con Hit@3 más de 5 puntos por debajo de la última aprobada, **cuando** termina, **entonces** `converdata eval discovery`
  sale con código ≠ 0 y Database Mail avisa.

---

### E5 · Fuentes de conocimiento (O6)

#### HU-25 · Ingesta de diccionarios de datos
**Como** steward **quiero** cargar el diccionario Excel/CSV del dominio **para** que las descripciones oficiales reemplacen a las generadas por IA.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-06, HU-18 | O6 | F23 CA1 y CA5, RF-22 |

- **Dado** un diccionario de prueba con 200 columnas, **cuando** se ingiere, **entonces** las descripciones quedan con `description_source: data_dictionary`
  sin sobrescribir las `human`.
- **Dado** una segunda ingesta sin cambios, **cuando** corre, **entonces** no llama al LLM ni reindexa (hash).

#### HU-26 · Ingesta de documentos con redacción de PII
**Como** responsable de Seguridad de la Información **quiero** que los documentos se indexen con DUI, NIT, cuentas y tarjetas redactados
**para** que ningún dato de cliente quede en el índice.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-06, HU-18, ubicación de los documentos ⚠️ S6 | O6 | F23 CA3, OP-02 CA7, OP-06 CA3, RF-23 |

- **Dado** un documento con un DUI y un número de cuenta de prueba, **cuando** se ingiere, **entonces** la búsqueda de ambos literales en `knowledge` da 0.
- **Dado** un fragmento con más del 20 % de PII, **cuando** se procesa, **entonces** se descarta.
- **Dado** la carpeta compartida o SharePoint, **cuando** termina la ingesta, **entonces** los originales no se copiaron a disco ni a la BD.

#### HU-27 · Linaje desde SSIS y SQL Server Agent
**Como** ingeniero de datos **quiero** ver qué paquete o job alimenta una tabla **para** saber cómo se carga sin preguntar al equipo de ETL.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 8 | HU-07, acceso a SSISDB y msdb ⚠️ S6 | O6 | F23 CA2, OP-02 §Fuentes adicionales, RF-24 |

- **Dado** un paquete `.dtsx` de prueba en SSISDB, **cuando** se ingiere, **entonces** aparecen las aristas de linaje esperadas (origen, destino, paquete y job).
- **Dado** la pregunta "¿qué proceso llena `DWH.dim.Cliente`?", **cuando** se descubre, **entonces** el candidato muestra el paquete o job con su fuente.

#### HU-28 · Reglas de negocio gestionadas
**Como** steward **quiero** registrar reglas de negocio vinculadas a activos **para** que aparezcan junto al dato correcto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | HU-06 | O6 | F23 CA4, RF-25, RF-07 |

- **Dado** la regla `BR-ONB-004` vinculada a `ClientCode`, **cuando** pregunto "¿qué reglas aplican al ClientCode?", **entonces** la respuesta la
  incluye con su fuente.
- **Dado** una regla vinculada a un activo que no veo, **cuando** pregunto, **entonces** no aparece.

---

### E6 · Curación y aprendizaje (O7)

#### HU-29 · Golden discovery desde las confirmaciones
**Como** nuevo colaborador **quiero** que las respuestas confirmadas por otros aparezcan primero **para** no repetir la búsqueda que alguien ya resolvió.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-15 | O7 | F24 CA2, F12 CA4, RF-30 |

- **Dado** un "✔" de un steward, **cuando** otro usuario hace una pregunta equivalente, **entonces** el activo recibe el bonus de golden y sube de posición.
- **Dado** un "✖" posterior del steward, **cuando** se repite la búsqueda, **entonces** el golden discovery se retira y el activo pierde el bonus.
- **Dado** `knowledge.golden_discovery`, **cuando** se inspecciona, **entonces** solo contiene la plantilla anonimizada; el original está en `golden`.

#### HU-30 · Preguntar al responsable
**Como** analista BI **quiero** escalar una pregunta sin respuesta al responsable del dominio **para** obtenerla sin buscar a quién preguntar.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-14, HU-20, canal de notificación ⚠️ S12 | O7 | F24 CA1, OP-04 CA7, RF-31 |

- **Dado** una respuesta con `knowledge_gap`, **cuando** pulso "Preguntar al responsable", **entonces** se crea una fila en `curation.curation_request`
  y el steward recibe un correo (Database Mail) o un mensaje de Teams **sin el texto de la pregunta**, solo el dominio y el enlace a `/curation`.
- **Dado** la respuesta del steward, **cuando** otro usuario hace una pregunta equivalente, **entonces** el activo aparece como candidato principal con
  confianza ≥ 0.85.

#### HU-31 · Vista Curación para stewards
**Como** steward **quiero** una vista para revisar descripciones, reglas, entidades, tablas canónicas y dudas escaladas **para** responder una
vez y que quede para todos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-06, HU-13 o asignación directa en `curation.owners`, HU-30 | O7 | F24 CA3 y CA4, OP-02 §Revisión humana, RF-32 |

- **Dado** el rol `steward`, **cuando** edito una descripción, **entonces** queda con `description_source: human` y el cambio entra en el historial temporal.
- **Dado** el rol `consumer`, **cuando** abro `/curation` o intento editar, **entonces** recibo 403.
- **Dado** la cola de revisión, **cuando** la abro, **entonces** está ordenada por demanda (preguntas que tocaron cada activo).

#### HU-32 · Reporte de brechas de conocimiento
**Como** Gerencia de Datos **quiero** un reporte de brechas abiertas y cerradas por dominio **para** priorizar el trabajo de los stewards.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-30, HU-23 | O7 | F24 CA5, RF-33 |

- **Dado** las 3 preguntas sin respuesta sembradas en el set de evaluación, **cuando** genero el reporte, **entonces** aparecen las 3.

---

### E7 · Calidad del descubrimiento (O8)

#### HU-33 · Set de evaluación con preguntas reales
**Como** Gerencia de Datos **quiero** 50–80 preguntas reales del equipo piloto con sus activos correctos validados por un experto **para**
medir la calidad sin el sesgo del set del equipo de desarrollo.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | steward asignado ⚠️ S9, catálogo del dominio piloto (HU-06) | O8, O10 | F25 §Métricas de calidad, OP-01 D1 |

- **Dado** `eval/discovery.yaml` del dominio piloto, **cuando** se revisa, **entonces** tiene 50–80 preguntas con `asset_key` validados y 5 sin respuesta.
- **Dado** el set, **cuando** corre `converdata eval discovery` con Bedrock, **entonces** Hit@3 ≥ 85 %, Hit@1 ≥ 65 %, MRR ≥ 0.75, calibración ≥ 85 %,
  0 inventados y 0 fugas.

#### HU-34 · Medir y ajustar el canal semántico
**Como** desarrollador **quiero** medir el impacto de los embeddings en las 4 combinaciones del plan de desarrollo **para** subir el tipo B
(vocabulario) sin bajar los demás.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | — | O8 | PLAN-desarrollo §3 pasos 1–2, F2, F22 |

- **Dado** las 4 combinaciones (crudo/enriquecido × léxico/+embeddings), **cuando** se evalúan, **entonces** queda registrada la mejor en el plan de desarrollo.
- **Dado** la combinación elegida, **cuando** se compara con la línea base actual (72,4 % / 82,8 %), **entonces** el tipo B sube y A, C, D y G no bajan.

#### HU-35 · Bedrock probado de punta a punta
**Como** desarrollador **quiero** probar los roles `planner`, `fast`, `judge` y `embed` contra Bedrock por el proxy corporativo **para**
conocer latencia y coste reales antes del piloto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | cuenta AWS con Bedrock e IAM Roles Anywhere ⚠️ S4 | O8 | F16, OP-01 §Configuración AWS, D5 |

- **Dado** la configuración de Bedrock, **cuando** corre `converdata llm smoke`, **entonces** cada rol responde con salida estructurada y embeddings de 1024 dimensiones.
- **Dado** el set de BancosSQL con Bedrock, **cuando** se evalúa, **entonces** se reportan p50/p95 y coste por pregunta; el objetivo es p50 < 5 s y p95 < 10 s.
- **Dado** la cuenta AWS, **cuando** se revisa, **entonces** *model invocation logging* está desactivado.

#### HU-36 · Batería de inyección de prompt y Guardrails
**Como** responsable de Seguridad de la Información **quiero** una batería de inyecciones de prompt contra el DiscoverFlow **para** comprobar
que no revela objetos fuera de la visibilidad ni inventa activos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-02, HU-35 | O8 | OP-01 D6, OP-06 (tras HU-02) |

- **Dado** 20 preguntas de inyección ⚠️ S7, **cuando** se evalúan, **entonces** hay 0 fugas de permisos, 0 objetos inventados y los bloqueos de
  Guardrails quedan auditados.

---

### E8 · Instalación y operación (O9)

#### HU-37 · Scripts de instalación en Windows Server
**Como** administrador de Plataformas **quiero** scripts PowerShell que instalen IIS, HttpPlatformHandler, Python con uv, los servicios,
el `web.config`, el certificado y el firewall **para** montar un entorno igual al del piloto en menos de un día.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-01, HU-03, HU-14, HU-17, HU-18 | O9 | OP-07 (HU-01), OP-04 §IIS, OP-01 §Topología |

- **Dado** un Windows Server limpio, **cuando** se ejecutan los scripts, **entonces** `https://<servidor>/` responde con TLS de la PKI corporativa,
  HTTP redirige a HTTPS y HSTS está activo.
- **Dado** un proceso Python que cae, **cuando** pasa el intervalo de supervisión, **entonces** se reinicia solo (OP-04 CA5).
- **Dado** el firewall, **cuando** se revisa, **entonces** solo hay entrada en 443 y salida a 1433, proxy, LDAP/Kerberos y SMB 445.
- **Dado** WebSockets y streaming, **cuando** se usa el chat, **entonces** funcionan a través de IIS.

#### HU-38 · Secretos de servicio sin contraseñas en claro
**Como** responsable de Seguridad de la Información **quiero** el login de metadatos con DPAPI y Bedrock con IAM Roles Anywhere **para** no
tener claves de larga duración en el servidor.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | gMSA creadas por AD ⚠️ S10, HU-35 | O9 | OP-03 §Cuentas técnicas, OP-06 §Secretos |

- **Dado** los servicios, **cuando** se revisan, **entonces** corren con gMSA y la conexión a `ConverData` no usa contraseñas.
- **Dado** el login de metadatos, **cuando** se guarda, **entonces** está cifrado con DPAPI en el ámbito de la cuenta de servicio.
- **Dado** Bedrock, **cuando** se invoca, **entonces** usa IAM Roles Anywhere con un certificado de clave no exportable y solo `bedrock:InvokeModel*` y `bedrock:ApplyGuardrail`.

#### HU-39 · Respaldo y restauración probados
**Como** DBA **quiero** restaurar la BD `ConverData` en otra instancia y que el servicio arranque contra ella **para** saber que el piloto
sobrevive a la pérdida del servidor.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 2 | HU-01, HU-09 | O9 | OP-07 (HU-01), OP-05 §Auditoría |

- **Dado** un respaldo de la BD `ConverData`, **cuando** se restaura y se apunta el servicio a ella, **entonces** el descubrimiento devuelve los mismos
  resultados y el historial temporal se conserva, dentro del RPO/RTO de OP-07.

---

### E9 · Piloto (O10)

#### HU-40 · Línea base firmada
**Como** Gerencia de Datos **quiero** medir la línea base de las 4 métricas de negocio antes del piloto **para** poder demostrar el impacto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | gestor de requerimientos y canal de consultas identificados ⚠️ S13 | O10 | F25 §Métricas de negocio y CA1, PRD §10 fase 0 |

- **Dado** las semanas 0–1, **cuando** terminan, **entonces** hay 15–20 búsquedas cronometradas por perfil, la encuesta de 2 semanas a expertos y las
  etiquetas `usa-discovery-agent` y `reproceso-fuente` creadas, y la Gerencia de Datos firma la línea base.

#### HU-41 · Ejecución del piloto e informe de decisión
**Como** Gerencia de Datos **quiero** correr el piloto de 8 semanas con 10–15 usuarios y un informe contra D1–D7 **para** decidir si se pasa
a la fase 1b o se escala.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | todas las *Must* de E1–E8, HU-40 | O10 | OP-01 §Plan de validación, F25 §Plan del piloto |

- **Dado** el piloto en curso, **cuando** cierra cada semana, **entonces** se publica `converdata metrics report` a la Gerencia de Datos.
- **Dado** la semana 8, **cuando** se entrega el informe, **entonces** compara D1–D7 con sus umbrales y las 4 métricas de negocio con la línea base,
  y termina en una recomendación (fase 1b, escalar dominios, cloud native o producción on-premise).

## 5. Supuestos a confirmar
| ID | Supuesto | Afecta a | Por qué no se deduce del repo |
|---|---|---|---|
| S1 | "Versión on-premise terminada" = fase 0 + fase 1a lista y piloto evaluado; la fase 1b es otra versión | Alcance, O10 | OP-01 incluye 1b en el MVP, pero condicionada a que 1a cumpla |
| S2 | Calendario: 6 sprints de 2 semanas desde el 2026-11-02, sin capacidad del 2026-12-21 al 2027-01-01; piloto del 2027-02-08 al 2027-04-02 y decisión el 2027-04-09 | Todos los plazos | El repo no tiene fechas de inicio ni del piloto |
| S3 | Velocidad de 25 puntos por sprint (2 desarrolladores) | Plan de entregas | No hay datos de equipo ni histórico de velocidad |
| S4 | La cuenta AWS con Bedrock e IAM Roles Anywhere está disponible antes del sprint 2 | HU-35, HU-38, O8 | Dependencia externa (PRD §11) |
| S5 | Hay una instancia SQL Server 2025 de desarrollo antes del sprint 1 (la máquina de desarrollo actual no tiene SQL Server) | HU-05 en adelante, O2 | Dependencia de infraestructura |
| S6 | Diccionarios y documentos del dominio piloto están en una carpeta compartida o SharePoint, y SSISDB y msdb son accesibles con un login técnico | HU-26, HU-27, O6 | Pregunta abierta 1 del PRD |
| S7 | Batería de 20 inyecciones de prompt; umbrales de latencia con Bedrock iguales a los de F22 | HU-36, O8 | F25 no fija el tamaño de la batería |
| S8 | "Instalación reproducible" = desde cero en ≤ 1 día laboral con los scripts | O9 | No hay requisito de tiempo de instalación |
| S9 | Steward funcional y técnico del dominio asignados con tiempo desde el sprint 5 (2027-01-11) | HU-31, HU-33, O7, O8 | PRD §11 lo pide para las semanas 2–3 del piloto, pero el set de evaluación hace falta antes |
| S10 | AD crea las gMSA y permite LDAP de solo lectura | HU-13, HU-38 | Dependencia de Plataformas |
| S11 | El monitoreo existente es SCOM o Zabbix | HU-22 | OP-05 lo da solo como ejemplo |
| S12 | Canal de notificación a stewards: Database Mail (Teams como alternativa) | HU-30 | Pregunta abierta 4 del PRD |
| S13 | Gestor de requerimientos y canal de consultas para la línea base identificados antes del 2027-01-25 | HU-40 | Pregunta abierta 2 del PRD |

## 6. Trazabilidad con la revisión de huecos (2026-10-27)
| Hueco | Historias |
|---|---|
| OP sin instalación, entornos ni requisitos no funcionales (CN-01 sí) | HU-01, HU-37, HU-39 |
| OP sin Bedrock Guardrails | HU-02, HU-36 |
| OP-04 sin límite de tokens por usuario y día | HU-02, HU-19 |
| OP-05 sin alertas ni CA de fail-closed | HU-02, HU-20, HU-24 |
| OP-03 sin CA de suplantación por argumentos MCP | HU-02, HU-16 |
| OP-04 sin CA de streaming ni de `discover` por MCP | HU-02, HU-16, HU-17 |
| OP-06 sin volcados de memoria, temporales, respaldos ni ediciones de curación | HU-02 |
| Contradicción servicios de Windows / HttpPlatformHandler y reciclaje del Builder | HU-03 |
| DDL sin `estate` ni `semantic`, sin vistas ni purga | HU-04, HU-07, HU-23, HU-24 |
| Catálogo y grafo solo en YAML / memoria; `SqlServerVectorStore` sin validar | HU-05, HU-06, HU-07, HU-08, HU-09 |
| Auditoría solo en memoria | HU-20 |
| Sin `SessionVault`, `ConnectionFactory`, `/login` ni grupos | HU-10, HU-11, HU-12, HU-13 |
| Sin API, MCP, Chainlit ni `/api/admin` | HU-14 a HU-18 |
| Sin logs D5, Visor de eventos ni `/health/metrics` | HU-21, HU-22 |
| Sin `web.config`, scripts de instalación ni secretos de servicio | HU-37, HU-38 |
| F23 y F24 sin empezar | HU-25 a HU-32 |
| Embeddings y Bedrock sin medir; set de evaluación sintético | HU-33, HU-34, HU-35 |
