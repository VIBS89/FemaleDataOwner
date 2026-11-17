# Backlog — versión on-premise (fase 0 + fase 1a)

> Creado: 2026-10-27. Revisado el 2026-11-16 con la arquitectura simplificada ([PRD §13](../PRD.md#13-decisiones-y-preguntas-abiertas), decisiones 9–16).
> Documento vivo: se actualiza al cerrar cada sesión de trabajo.
> Base: [PRD](../PRD.md) §6, §10 y §11 · [OP-01](../specs/on-premise/OP-01-despliegue-local.md) a [OP-07](../specs/on-premise/OP-07-instalacion-operacion.md) · [F25](../specs/comun/F25-success-metrics.md) · [plan de desarrollo](../PLAN-desarrollo.md) · [calidad bancaria](../calidad-bancaria.md).
>
> Las marcas **⚠️ SUPUESTO** son plazos, capacidades o métricas que no se deducen del repo. Hay que confirmarlas antes de
> comprometer fechas; la lista completa está en la [§5](#5-supuestos-a-confirmar).

## 1. Alcance de esta versión
"Versión on-premise terminada" significa: **el piloto de descubrimiento (fase 1a de OP-01) corre en el Windows Server del banco,
sobre la BD `ConverData` en SQL Server 2016 o posterior, con 10–15 usuarios reales, y se evalúa contra D1–D7**. ⚠️ SUPUESTO S1.

| Dentro | Fuera (otra versión) |
|---|---|
| Fase 0 (preparación y línea base) y fase 1a (descubrimiento) de PRD §10 | Fase 1b: AskFlow, F4–F10, F20, F21 (RF-40 a RF-42) |
| Requisitos P0 de PRD §6.1–6.3 y 6.5, y los P1 que exigen las specs OP para el piloto (MCP, linaje SSIS) | Alta disponibilidad del servidor de aplicación, SSO con Kerberos (OP-03 §Evolución) |
| Compuerta de calidad y controles de [calidad bancaria](../calidad-bancaria.md) | Despliegue en AWS (CN-01 a CN-06) |

### Qué cambió con la arquitectura simplificada (2026-11-16)
| Antes | Ahora | Historias afectadas |
|---|---|---|
| SQL Server 2025 con `VECTOR`, Full-Text y tablas de grafo | Tablas normales en SQL Server 2016+; búsqueda léxica y grafo en memoria | HU-04, HU-05 y HU-07 redefinidas; ya no dependen de una instancia 2025 (se cae el supuesto S5) |
| Chat en Chainlit | Web Next.js (`web/`), ya construida | HU-17 |
| Servicio `ConverData-Builder` con `/api/admin/*` y job de SQL Server Agent | Comando `converdata catalog build` lanzado por el Programador de tareas o desde Administración | HU-03, HU-18, HU-24, HU-37 |
| Bedrock con cuatro roles (planner, fast, judge, embed) y Guardrails | Un modelo para intención y orden; Guardrails es decisión de Seguridad | HU-02, HU-35, HU-36 |
| Database Mail | Webhook de Teams | HU-18, HU-24, HU-30 |

### Estado al 2026-11-16
**360 tests en verde** (297 sin SQL Server, más 63 contra una BD `ConverData` real y desechable) y compuerta `converdata eval gate`
aprobada en los dos catálogos de prueba, también con el catálogo cargado desde la BD (modo determinista).

| Estado | Historias |
|---|---|
| ✅ Hechas | HU-01, HU-02, HU-03 (specs revisadas el 2026-11-16), **HU-04, HU-05, HU-08, HU-20** (2026-11-16; cada una con las salvedades de su bloque **Estado**), HU-10, HU-11, HU-12, HU-14, HU-16, HU-17, HU-19, HU-21, HU-22, HU-34, HU-42 |
| 🟡 Hechas en lo principal; falta una parte | **HU-06 y HU-09** (catálogo y conocimiento en la BD y la API arranca desde ella; faltan responsables, solicitudes, votos e inventario, que siguen en archivos) |
| 🟡 Hechas, con parte en archivos del servidor | HU-15 (el voto ya queda en `audit`; el recuento sigue en `feedback.jsonl`), HU-29, HU-30, HU-31, HU-32; HU-25 (CSV) y HU-28 ya se publican en la BD |
| 🟡 Parciales | HU-18 (falta la tarea programada), HU-23 (hay `/admin/metrics`; falta `converdata metrics report`), HU-24 (hay regresión con `eval gate` y purga `converdata audit purge`; faltan las tareas programadas), HU-36 (falta repetirla con LLM real y validarla con Seguridad) |
| ⏳ Pendientes que se pueden hacer ya en desarrollo | El resto de HU-06/HU-09 (bloque C2 del plan), HU-26, HU-37 (scripts), HU-39 |
| ⛔ Pendientes que dependen del banco o de terceros | HU-13 (LDAP), HU-27 (SSISDB y msdb), HU-33 (preguntas reales y steward), HU-35 (cuenta AWS), HU-38 (gMSA, certificados), HU-40, HU-41 |
| ❌ Retirada | HU-07 como "tablas de grafo" (PRD §13, decisión 10); su parte útil pasa a HU-06 |

El detalle de cada una está en su bloque **Estado** de la §4. Los pendientes de seguridad que no son historias están en
[calidad bancaria §5](../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto).

## 2. Objetivos SMART
| ID | Objetivo (específico) | Medida de cumplimiento | Alcanzable porque… | Relevante para | Plazo | Specs |
|---|---|---|---|---|---|---|
| **O1** ✅ | Specs on-premise completas y coherentes con el PRD, los diagramas y CN: OP-07 (instalación y operación) y huecos de OP-01 a OP-06 cerrados | Las 9 brechas de la revisión del 2026-10-27 (§6) cerradas o con decisión registrada; 0 contradicciones abiertas entre PRD, specs y diagramas (revisión del 2026-11-16) | Es trabajo de documentación sobre specs ya maduras | Desbloquea instalación, seguridad y criterios de aceptación de todo lo demás | 2026-11-13 ⚠️ S2 | OP-01…OP-07, F17 |
| **O2** | La BD `ConverData` (SQL Server 2016+) es el almacén de trabajo: catálogo con historial, conocimiento, curación y auditoría | Criterios de OP-02 en verde contra una instancia real de SQL Server; la compuerta `eval gate` da el mismo resultado con el catálogo cargado desde la BD que desde YAML | El modelo ya existe en YAML y el DDL está escrito; hay un SQL Server 2022 Express de desarrollo | Sin persistencia no hay piloto multiusuario ni historial (RF-34) | 2026-12-11 ⚠️ S2 | OP-02, F1, F2, F19 |
| **O3** | Cada usuario descubre solo lo que su login SQL puede leer, de punta a punta por la API | CA 1–4 de OP-03 y CA 1, 4, 5 y 6 de F14 en verde con dos logins de prueba en dos servidores; **0 fugas** en el set de evaluación | `VisibilityResolver` ya calcula `visible_ids`; falta la sesión y la custodia | D6 de OP-01 (0 fugas) es criterio de salida | 2026-12-11 ⚠️ S2 | OP-03, F14 |
| **O4** | Interfaces publicadas en IIS: web, API, MCP y administración | CA 1–7 de OP-04 en verde en el servidor de piloto | La web Next.js, la API y el MCP ya funcionan en desarrollo (docker compose); falta IIS | RF-50, RF-51, RF-52; los usuarios no usan el CLI | 2027-02-05 ⚠️ S2 | OP-04, F12 |
| **O5** | Toda pregunta queda auditada en SQL Server y el servicio es observable sin contenido | CA 1–5 de OP-05 y CA 1, 3, 4 y 5 de F11 en verde; test de logs con 0 preguntas, SQL o filas | El modelo de F11 ya está en el DDL | RF-53; base de las métricas de F25 | 2027-01-08 ⚠️ S2 | OP-05, F11, F17 |
| **O6** | El conocimiento del dominio clientes / onboarding digital está ingerido con PII redactada | CA 1–5 de F23 y CA 7 de OP-02; CA 3 de OP-06 (0 DUI ni cuentas de prueba en `knowledge`) | Presidio y los conectores son piezas acotadas; el dominio piloto es pequeño | RF-22, RF-23, RF-25; sin ellos la confianza depende de texto IA (tope 0.6) | Semana 3 del piloto (2027-02-26) ⚠️ S2, S6 | F23, OP-02, OP-06 |
| **O7** | El conocimiento de los expertos se captura desde el uso | CA 1–5 de F24 y CA 6–7 de OP-04 en verde | El ciclo ✔/✖ y `golden_discovery` ya tienen tablas | RF-30 a RF-33; objetivo de negocio −30 % consultas a expertos | 2027-01-22 ⚠️ S2 | F24, OP-04 |
| **O8** | Calidad del descubrimiento lista para el piloto con el LLM real | En un set de 50–80 preguntas reales: Hit@3 ≥ 85 %, Hit@1 ≥ 65 %, calibración ≥ 85 %, 0 inventados, p50 < 5 s y p95 < 10 s con Bedrock; compuerta `eval gate` aprobada con `--models` | Hoy: Hit@1 y Hit@3 93,1 % en 31 casos escritos por el equipo, sin LLM; faltan las preguntas reales y Bedrock | D1, D2 y D5 de OP-01 | Inicio del piloto (2027-02-08) ⚠️ S2, S7 | F22, F25, OP-01 |
| **O9** | Instalación y operación reproducibles en Windows Server | Instalación desde cero en un servidor limpio con los scripts de OP-07 en ≤ 1 día laboral ⚠️ S8; restauración de la BD `ConverData` probada; un proceso caído se reinicia solo (OP-04 CA5) | Todo es stack Microsoft que el equipo ya opera | Sin esto no hay entorno de piloto ni camino a producción on-premise | 2027-02-05 ⚠️ S2 | OP-01, OP-07 |
| **O10** | Piloto de 8 semanas ejecutado y decisión de escalar tomada | Línea base firmada antes de empezar; informe con D1–D7 de OP-01 y las 4 métricas de negocio de F25 | Plan de 8 semanas ya definido en F25 | Es la hipótesis central de OP-01 | Línea base: 2027-02-05 · Decisión: 2027-04-09 ⚠️ S2, S9 | OP-01, F25 |

## 3. Plan de entregas
⚠️ SUPUESTO S2/S3: el calendario original (6 sprints de 2 semanas desde el 2026-11-02, 25 puntos por sprint, piloto del 2027-02-08 al
2027-04-02) **hay que volver a confirmarlo**: se hizo antes de la simplificación y parte del trabajo de los sprints 3 a 6 ya está hecho.
Mientras tanto vale este orden, que es el del [plan de desarrollo §3](../PLAN-desarrollo.md#3-próximos-pasos-en-orden):

| Bloque | Foco | Historias | Depende de | Objetivos |
|---|---|---|---|---|
| A | BD `ConverData`: DDL por migraciones, validado en SQL Server real | HU-04, HU-05 | — | O2 |
| B | Auditoría fail-closed en SQL Server | HU-20 | A | O5 |
| C | Catálogo, conocimiento y curación en la BD; la API arranca desde ella | HU-06, HU-09, y el paso a BD de HU-15, HU-25, HU-28 a HU-32 | A | O2, O6, O7 |
| D | Métricas, purga y regresión programada | HU-23, HU-24 | B | O5, O10 |
| E | Fuentes de conocimiento del dominio piloto | HU-25 (Excel), HU-26, HU-27 | C; documentos y SSISDB ⚠️ S6 | O6 |
| F | Instalación y operación | HU-37, HU-38, HU-39, HU-18 (tarea programada) | C; gMSA ⚠️ S10 | O9 |
| G | Bedrock y calidad con preguntas reales | HU-35, HU-36, HU-33 | cuenta AWS ⚠️ S4; steward ⚠️ S9 | O8 |
| H | Piloto | HU-40, HU-41, HU-13 si hay LDAP | F, G | O10 |

Los bloques A a D y los scripts de F no dependen de nadie externo. E, G y H necesitan al banco.

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

Los puntos son los de la estimación original; HU-04, HU-05 y HU-07 cambiaron de contenido el 2026-11-16 y no se han vuelto a estimar.

*Won't (esta versión)*: AskFlow y fase 1b, código Python libre (F20), `candidates: 2`, SSO con Kerberos, alta disponibilidad del
servidor de aplicación, fallback automático a NIM con datos reales (OP-01 §Fuera del alcance), y lo retirado por PRD §13: índice
vectorial y embeddings, Full-Text, tablas de grafo, Chainlit, servicio `ConverData-Builder` y jobs de SQL Server Agent.

---

### E0 · Specs on-premise completas (O1)
> **Estado (2026-11-16):** hechas. Redactadas el 2026-10-27 y reescritas el 2026-11-16 para la arquitectura simplificada (PRD §13,
> decisiones 9–16). Falta la revisión de Plataformas y de Seguridad de la Información; los valores "⚠️ propuesto" de OP-07
> (disponibilidad, RPO/RTO y tiempo de reinstalación) siguen abiertos.

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

- **Dado** OP-01 y OP-06, **cuando** se revisan, **entonces** dicen qué guardas protegen entradas y salidas del LLM (las del código hoy) y registran
  Bedrock Guardrails como decisión pendiente de Seguridad de la Información (PRD §13, decisión 13).
- **Dado** OP-04, **cuando** se revisa, **entonces** incluye el límite de tokens por usuario y día y los CA de streaming y de `discover` por MCP.
- **Dado** OP-03 y OP-05, **cuando** se revisan, **entonces** incluyen los CA "A no obtiene la credencial de B manipulando argumentos MCP",
  "fail-closed con alerta si la BD `ConverData` no responde" y alertas de p95 y de throttling de Bedrock.
- **Dado** OP-06, **cuando** se revisa, **entonces** tiene filas para volcados de memoria y WER, pagefile, temporales del servicio, respaldos de
  la BD `ConverData` y ediciones de curación con PII.

#### HU-03 · Decidir el modelo de procesos en IIS
**Como** administrador de Plataformas **quiero** una decisión única sobre cómo corren la web, la API y el Builder **para** no
instalar servicios de Windows y procesos de HttpPlatformHandler a la vez y evitar que IIS recicle un batch largo.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 2 | — | O1, O9 | OP-01 §Decisiones, OP-04 §IIS |

- **Dado** OP-01, OP-04 y OP-07, **cuando** se leen, **entonces** describen un solo modelo sin contradicciones: web y API bajo
  HttpPlatformHandler y el Builder como comando lanzado por el Programador de tareas (PRD §13, decisión 12).
- **Dado** el Builder, **cuando** una ingesta dura más que el *idle timeout* de IIS, **entonces** la spec garantiza que no se interrumpe.

---

### E1 · Persistencia en la BD `ConverData` (O2)

#### HU-04 · DDL de la BD `ConverData` por migraciones
**Como** DBA **quiero** el DDL de la BD `ConverData` en scripts numerados, con sus roles y permisos **para** crear y actualizar la BD del
piloto con scripts revisables.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | — | O2 | OP-02 §BD de trabajo, OP-05, OP-07 §Migraciones |

- **Dado** `db/converdata/`, **cuando** se revisa, **entonces** solo usa tablas normales y temporales (sin `VECTOR`, Full-Text ni tablas de
  grafo), corre en SQL Server 2016 o posterior y registra cada script aplicado en `dbo.schema_version`.
- **Dado** el rol de la API, **cuando** intenta `UPDATE` o `DELETE` en `audit`, **entonces** SQL Server lo deniega.
- **Dado** el rol `converdata_auditor`, **cuando** consulta `audit`, **entonces** tiene `SELECT` y nada más.
- **Dado** el rol del Builder, **cuando** escribe, **entonces** solo puede hacerlo en `catalog` y en las tablas de `knowledge` que deriva de
  los metadatos (entidades y linaje), además de dejar eventos en `audit.audit_event`; no lee ni toca reglas, fragmentos, confirmaciones,
  responsables ni preguntas.

> **Estado (2026-11-16):** hecha. `db/converdata/001_esquemas.sql` (esquemas `catalog`, `knowledge`, `golden`, `curation` y `audit`; roles
> `converdata_app`, `converdata_builder`, `converdata_auditor` y `converdata_maintenance`; purga `audit.usp_purge`) y `converdata db migrate`
> (`src/converdata/storage/migrations.py`): una transacción por script, registro en `dbo.schema_version` y rechazo de un script editado
> después de aplicarse. Pruebas: `tests/test_storage_migrations.py` (permisos de cada rol contra SQL Server real, incluido que ni la API ni
> el Builder pueden apagar el versionado temporal ni bajar la versión) y `tests/test_catalog_repository.py` (publicar, cargar y auditar con
> la cuenta de cada rol). Salvedades: probado en SQL Server 2022, no en 2016; el comando `db migrate` se probó a mano.

#### HU-05 · Validar la BD `ConverData` contra un SQL Server real
**Como** desarrollador **quiero** pruebas de integración que apliquen las migraciones y ejerciten los adaptadores contra SQL Server
**para** no descubrir en el piloto que el DDL o los permisos fallan.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-04 | O2 | OP-07 §Migraciones, OP-02 CA2 |

- **Dado** `CONVERDATA_TEST_DB` apuntando a una instancia, **cuando** corren las pruebas de integración, **entonces** crean una BD temporal,
  aplican las migraciones dos veces (la segunda sin cambios) y la eliminan al terminar.
- **Dado** que la variable no está definida (CI, otros equipos), **cuando** corre `pytest`, **entonces** esas pruebas se omiten y el resto pasa.
- **Dado** las tablas temporales, **cuando** se cambia una descripción, **entonces** la versión anterior queda en el historial.

`SqlServerVectorStore` y la comparación de Hit@3 con vectores se retiraron con la decisión 9 del PRD §13.

> **Estado (2026-11-16):** hecha. Fixtures `sqlserver_database` y `converdata_db` en `conftest.py` de la raíz: con `CONVERDATA_TEST_DB` crean una
> BD `ConverData_test_<aleatorio>`, aplican las migraciones (la segunda vez sin cambios) y la eliminan; sin la variable, 63 pruebas se
> omiten. Abortan si la variable nombra una base de datos, para no tocar nunca una real. Validado en SQL Server 2022 Express; **no** en
> 2016 ni en la CI (no tiene SQL Server).

#### HU-06 · Escribir el catálogo en la BD `ConverData` con historial
**Como** steward **quiero** que el catálogo viva en tablas con historial temporal **para** ver quién cambió una descripción y cuándo.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-05 | O2 | OP-02 §Ingesta, CA 2 y 5; F1; RF-34 |

- **Dado** `converdata catalog build` contra la instancia de desarrollo, **cuando** termina, **entonces** `catalog` tiene servidores, BDs,
  objetos, columnas y FKs, y `knowledge` tiene las entidades de negocio y las aristas de linaje (lo que antes era HU-07).
- **Dado** una descripción editada, **cuando** se consulta el historial temporal, **entonces** aparece la versión anterior y quién la cambió.
- **Dado** un refresco posterior, **cuando** termina, **entonces** no sobrescribe ninguna edición `human` (F24 CA3).
- **Dado** el test de literales marcados, **cuando** se ejecuta, **entonces** ninguna tabla fuera de `audit`, `golden` y `curation` contiene valores.

> **Estado (2026-11-16):** hecho el catálogo y el conocimiento (`src/converdata/storage/catalog_repository.py`): `converdata catalog publish`,
> `catalog build --db` y la API publican servidores, objetos, columnas, FKs, fragmentos, reglas, linaje, entidades, confirmaciones y
> responsables por dominio, escribiendo solo lo que cambió; el historial temporal guarda la versión anterior y su autor
> (`description_history`); un refresco (`scope="build"`) no pisa lo `human` ni lo `data_dictionary`, ni toca lo curado. Pruebas:
> `tests/test_catalog_repository.py`, `api/tests/test_catalog_db.py`. Falta (bloque C2): la prueba de literales marcados de punta a punta
> (criterio 4; hoy se comprueba que `catalog` y `knowledge` no tienen columnas de valores, y `knowledge.golden_discovery` guarda la
> pregunta normalizada, no anonimizada); exponer el historial en la vista Curación (hoy solo por SQL); una prueba automática del
> comando `catalog build --db` (probado a mano; el mismo flujo por la API sí está probado).

#### HU-07 · Grafo del patrimonio en tablas de grafo — retirada
> **Estado (2026-11-16):** retirada por la decisión 10 del PRD §13. El grafo del patrimonio (F19) se construye en memoria al cargar el
> catálogo (`converdata.graph.estate`); las entidades de negocio y el linaje se guardan en tablas normales de `knowledge` con HU-06, y
> los tipos C y D del set de evaluación ya se miden así.

#### HU-08 · Exportar el catálogo a YAML
**Como** data_admin **quiero** `converdata catalog export` **para** revisar cambios del catálogo y del conocimiento en pull requests.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Could | 3 | HU-06 | O2 | OP-02 §Versionado en git |

- **Dado** la BD `ConverData` con catálogo, **cuando** se ejecuta el export, **entonces** genera YAML con el formato de `tests/fixtures/*/catalog`
  que `load_catalog` vuelve a leer sin diferencias.

> **Estado (2026-11-16):** hecha: `converdata catalog export --out <dir>` y `write_snapshot`; el directorio exportado se vuelve a leer sin
> diferencias (`test_exportar_e_importar_da_el_mismo_catalogo`). Exporta catálogo y conocimiento sin las confirmaciones, que llevan el
> texto de las preguntas (`--with-questions` las incluye); `semantic` es de la fase 1b. El comando en sí se probó a mano.

#### HU-09 · Ensamblar el DiscoverFlow desde la BD `ConverData`
**Como** desarrollador **quiero** que `ConverData-API` cargue catálogo, conocimiento y responsables desde la BD **para** que el servicio no
dependa de archivos YAML en el servidor.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-06 | O2, O4 | OP-02, `bootstrap.py` |

- **Dado** la configuración de conexión a `ConverData`, **cuando** arranca el servicio, **entonces** carga catálogo, conocimiento y responsables de la BD
  y construye el índice léxico en memoria.
- **Dado** que el Builder publica un catálogo nuevo, **cuando** la API lo detecta, **entonces** recarga el índice sin reiniciar el proceso.
- **Dado** el modo de desarrollo, **cuando** se pasa `--root`, **entonces** sigue funcionando con YAML (todos los tests actuales siguen en verde).
- **Dado** el mismo catálogo en YAML y en la BD, **cuando** corre `converdata eval gate` con cada uno, **entonces** el resultado es el mismo.

> **Estado (2026-11-16):** hecha en lo principal. Con `CONVERDATA_DB`, `ConverData-API` trae el catálogo de la BD al arrancar
> (`build_service_from_db`, `runtime._pull`), publica cada edición de curación antes de recargar (`runtime.commit`), carga lo que publica
> el Builder sin reiniciar (comprueba la versión cada 15 s) y responde 409 si se edita sobre una versión que ya cambió. Otra instancia
> con el catálogo vacío en disco arranca con lo publicado. El descubrimiento da las mismas métricas y los mismos candidatos, caso por caso,
> desde la BD que desde YAML (`test_el_descubrimiento_responde_igual_desde_la_bd_que_desde_yaml`), y `eval gate --db` aprueba las siete
> suites (a mano). Las ediciones corren bajo un solo candado (`runtime.editing`), y `/mcp` también carga la versión nueva. Falta (bloque
> C2): responsables por login, solicitudes escaladas, votos, registro de diccionarios e inventario de la API siguen en archivos, y la API
> trabaja sobre una copia del catálogo en disco, así que el servidor todavía guarda estado propio.

---

### E2 · Identidad y permisos heredados (O3)

#### HU-10 · Iniciar sesión con login SQL por servidor
**Como** analista BI **quiero** iniciar sesión con mi login SQL en los servidores del piloto **para** descubrir solo lo que ya puedo consultar.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-11, HU-12 | O3 | OP-03 §Decisión, OP-04 §API, F14 |

- **Dado** credenciales válidas para producción y QA, **cuando** llamo a `POST /auth/login` (alias `/login`), **entonces** recibo la sesión,
  su caducidad y el resultado por servidor.
- **Dado** "usar la misma credencial en los servidores marcados", **cuando** inicio sesión, **entonces** se valida en cada servidor por separado y
  los que fallan quedan con `ok: false`.
- **Dado** una contraseña incorrecta, **cuando** inicio sesión, **entonces** recibo un error sin indicar qué objetos existen en el servidor.

> **Estado (2026-11-16):** hecha en `ConverData-API` (`main.py: login`, `connector.py`, `vault.py`) y endurecida: bloqueo tras 5 fallos en
> 10 min, código de instalación en el primer arranque, login sin caracteres de cadena ODBC ([calidad bancaria §3](../calidad-bancaria.md)).
> Falta probarla con dos servidores reales (producción y QA) en el piloto.

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

> **Estado (2026-11-16):** hecha (`api/converdata_api/vault.py`): Fernet con clave efímera, 8 h de inactividad y 12 h de vida total,
> 5 sesiones por usuario, revocación por el administrador y pruebas en `api/tests/test_security.py`.

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

> **Estado (2026-11-16):** hecha (`connector.py`: `APP=ConverData`, `Encrypt=yes`; la visibilidad se lee con la credencial del usuario y
> se vuelve a leer cada 15 min). Falta comprobar `program_name` en un SQL Server del banco.

#### HU-13 · Grupos y roles desde Active Directory
**Como** data_admin **quiero** que los roles `steward` y `data_admin` se asignen a grupos de AD **para** no mantener roles login por login.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 5 | HU-10, acceso LDAP de solo lectura ⚠️ S10 | O3, O7 | OP-03 §Grupos, OP-04 §API, F24 |

- **Dado** un login asociado en `curation.user_directory`, **cuando** inicia sesión, **entonces** la sesión tiene los grupos de su cuenta de AD.
- **Dado** un login sin asociación, **cuando** inicia sesión, **entonces** `groups = []` y solo tiene el rol `consumer` (salvo asignación directa en `curation.owners`).

> **Estado (2026-11-16):** pendiente; depende de LDAP de solo lectura (⚠️ S10). En el piloto los roles se asignan por login SQL
> (`curation/stewards.yaml`, `CONVERDATA_ADMINS`), que es lo que OP-04 admite "en su defecto".

---

### E3 · Interfaces (O4)

#### HU-14 · API REST de descubrimiento
**Como** ingeniero de datos **quiero** llamar a `/discover` y `/assets/{asset_key}` (bajo `/api/` desde el navegador) **para** integrar el
descubrimiento en mis herramientas.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-09, HU-10, HU-20 | O4 | OP-04 §API, F12, RF-51, RF-10 |

- **Dado** un `Bearer` válido, **cuando** envío una pregunta a `/discover`, **entonces** recibo un `AnswerEnvelope` con `flow=discover`.
- **Dado** que no envío token, **cuando** llamo a cualquier ruta no pública, **entonces** recibo 401 (OP-04 CA2).
- **Dado** 31 preguntas en un minuto del mismo usuario, **cuando** envío la 31.ª, **entonces** recibo 429.
- **Dado** un origen distinto del sitio, **cuando** el navegador hace una petición CORS, **entonces** se rechaza.
- **Dado** `/assets/{asset_key}` de un activo no visible, **cuando** lo pido, **entonces** recibo 404 sin revelar que existe.

> **Estado (2026-11-16):** hecha (`api/converdata_api/main.py`): la matriz de rutas con sesión y rol se genera de `app.routes` y se prueba
> entera; ritmo por usuario, CORS y CSRF por `Origin`, tope de 4 MB. Deuda: la API llama al DiscoverFlow directamente en vez de pasar
> por `DiscoveryTools` ([capas del backend](../architecture/capas-backend.md)), y arranca desde archivos hasta HU-09.

#### HU-15 · Confirmar o rechazar un candidato
**Como** analista BI **quiero** marcar "✔ Es este" o "✖ No es" **para** que la próxima persona encuentre el dato más rápido.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | HU-14, HU-20 | O4, O7 | OP-04 CA6, F12, F24, RF-30 |

- **Dado** una respuesta con candidatos, **cuando** envío `POST /discover/feedback` con `confirm`, **entonces** queda una fila en
  `audit.audit_discovery_feedback` con `time_to_verdict_ms`.
- **Dado** un `trace_id` de otro usuario, **cuando** envío feedback, **entonces** la API lo rechaza.

> **Estado (2026-11-16):** hecha sobre archivos (`runtime.record_feedback`: solo acepta activos mostrados en esa respuesta y a ese
> usuario). Con la BD, cada voto deja su fila en `audit.audit_discovery_feedback` con `time_to_verdict_ms`. El recuento de votos por
> usuario sigue en `curation/feedback.jsonl` (bloque C2).

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
> (`converdata.integration.mcp.server`) hechos y probados con el cliente MCP oficial (`tests/test_mcp_server.py`). Montado el 2026-10-27
> en `/mcp` de `ConverData-API` con el SessionVault real (`api/converdata_api/mcp_mount.py`, `api/tests/test_mcp.py`). Verificado además con uvicorn real: `initialize` y `tools/call` por SSE responden. En el equipo de desarrollo, cualquier petición con la cabecera
> `mcp-protocol-version` recibe la respuesta reescrita (`transfer-encoding: chunked` sin cuerpo fragmentado), incluso desde un servidor
> HTTP de la biblioteca estándar de Python: lo causa algo de esa red local (inspección de tráfico), no ConverData ni el SDK. Repetir la
> prueba del cliente MCP de Python en el servidor de IIS.
>
> **Estado (2026-11-16):** hecha. `/mcp` respeta el ritmo por usuario y el tope diario de tokens (`mcp_guard`), y en qa y prod la API no
> arranca sin `CONVERDATA_MCP_HOSTS`. Queda fijar ese valor en la instalación (HU-37).

#### HU-17 · Chat web con tarjetas de candidatos
**Como** Product Owner **quiero** preguntar en un chat web y ver tarjetas con BD, ambiente, servidor, descripción, reglas, relaciones,
responsables y confianza **para** entender un dato sin depender de TI.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-14, HU-15 | O4 | OP-04 CA1 y CA6, F12, RF-50, PRD §5 |

- **Dado** que entro a `https://<servidor>/`, **cuando** inicio sesión con mi login SQL, **entonces** puedo preguntar y veo las tarjetas como en el
  ejemplo del README, con los botones "✔ Es este", "✖ No es", "Ver ficha" y "Ver relacionadas".
- **Dado** una respuesta en curso, **cuando** el flujo avanza, **entonces** el chat muestra los pasos en streaming.
- **Dado** la web, **cuando** se revisa, **entonces** no guarda credenciales ni conversaciones fuera de la sesión (OP-06).

> **Estado (2026-11-16):** hecha en Next.js (`web/`), en lugar de Chainlit (PRD §13, decisión 11): chat con tarjetas y pasos en vivo
> (`/discover/stream`), ficha del activo, Catálogo, Curación, Solicitudes, Métricas y Administración. Falta recompilar la web tras el
> endurecimiento (`npm --prefix web ci && npm --prefix web run build`; el campo "Código de instalación" del login no se verificó con
> `tsc`) y probar el streaming a través de IIS (HU-37).

#### HU-18 · Refresco programado del catálogo
**Como** DBA **quiero** que el catálogo se refresque cada noche sin intervención manual **para** que refleje los cambios de esquema.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-03, HU-06 | O4, O9 | OP-02 §Ingesta y CA6, OP-07 |

- **Dado** la tarea programada de Windows, **cuando** corre `converdata catalog build`, **entonces** el catálogo se actualiza en la BD `ConverData`
  y la tarea termina con código 0 o distinto de 0 según el resultado.
- **Dado** un `data_admin`, **cuando** lanza el refresco desde Administración (`POST /admin/catalog/build`), **entonces** ve su estado y su resumen.
- **Dado** un usuario sin el rol, **cuando** llama a `/admin/*`, **entonces** recibe 403 y el intento queda auditado.
- **Dado** un refresco fallido, **cuando** termina, **entonces** queda en el Visor de eventos y el webhook de Teams avisa.

> **Estado (2026-11-16):** hecho el refresco bajo demanda (`/admin/catalog/build`, auditado, con la credencial del administrador) y el
> comando `converdata catalog build --db`, que parte de la BD y publica en ella; la API carga la versión nueva sin reiniciar. Faltan la
> tarea programada (script en HU-37) y el aviso al fallar.

#### HU-19 · Límite de tokens por usuario y día
**Como** data_admin **quiero** un tope diario de tokens por usuario **para** acotar el coste de Bedrock en el piloto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Could | 2 | HU-14, HU-02 | O4 | OP-04 (tras HU-02), CN-04 |

- **Dado** un usuario que alcanzó el tope configurado, **cuando** hace otra pregunta, **entonces** recibe un mensaje claro y el DiscoverFlow
  responde en modo determinista o rechaza, según la configuración.

> **Estado (2026-10-27):** hecho el modo *rechazar*: `CONVERDATA_TOKEN_LIMIT` (0 = sin tope), `TokenLedger` por usuario y día UTC, gancho `usage_hook` del gateway
> (tokens del proveedor o estimación de ~4 caracteres por token con salida estructurada), 429 con mensaje claro y contador `token_limit`. Los mismos tokens
> alimentan `/health/metrics` (cierra ese pendiente de HU-22). Verificado en pantalla (aviso en el chat y toast, catálogo accesible). Modo *determinista* hecho (`CONVERDATA_TOKEN_LIMIT_MODE=deterministic`: responde sin LLM con un aviso y cuenta `token_limit_deterministic`), también verificado en pantalla. Falta probar con Bedrock real (HU-35).

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

- **Dado** una pregunta a `/discover`, **cuando** termina, **entonces** hay exactamente una fila en `audit.audit_question`, N en `audit_step` y una
  en `audit_discovery` por candidato, alternativa y relación, escritas en una sola transacción.
- **Dado** la BD `ConverData` caída y `audit.fail_open: false`, **cuando** llega una pregunta, **entonces** no se entrega la respuesta y queda un error
  en el Visor de eventos.
- **Dado** cualquier registro de auditoría, **cuando** se busca la contraseña de prueba, **entonces** no aparece.

> **Estado (2026-11-16):** hecha. Con `CONVERDATA_DB` (obligatoria en qa y prod) la API usa `SqlServerAuditSink`: una transacción por
> pregunta (`audit_question`, `audit_step`, `audit_discovery`), eventos de la API en `audit_event`, votos en `audit_discovery_feedback`,
> lectura para Administración, historial y métricas, y fail-closed también para los cambios de curación. La cuenta de la API no puede
> modificar ni borrar la auditoría y en qa y prod la API no arranca si puede. Pruebas contra SQL Server real: `tests/test_audit_sqlserver.py`,
> `api/tests/test_audit_db.py`. Un fallo de escritura deja el evento `audit.write_failed` en el log operativo; falta convertirlo en alerta
> en el monitoreo del banco y comprobarlo en el Visor de eventos de un servidor Windows (HU-37).

#### HU-21 · Logs JSON sin contenido y Visor de eventos
**Como** administrador de Plataformas **quiero** logs estructurados y eventos de Windows **para** diagnosticar fallos sin ver preguntas ni datos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | — | O5 | OP-05 §Observabilidad y CA3, F17 (lista blanca D5) |

- **Dado** un flujo completo con una pregunta y un literal marcado, **cuando** se inspeccionan los logs JSON, el Visor de eventos (origen `ConverData`)
  y los logs de IIS, **entonces** no aparecen la pregunta, SQL, filas ni la cabecera `Authorization`.
- **Dado** los logs en disco, **cuando** superan el tamaño configurado, **entonces** rotan.

> **Estado (2026-10-27):** hecho en `ConverData-API` (`CONVERDATA_LOG_DIR`, `CONVERDATA_EVENT_LOG`): un evento `http.request` por petición con ruta,
> método, estado y duración (lista blanca D5), archivo JSON rotado y Visor de eventos en Windows. Test: `test_logs_json_sin_contenido`. Falta comprobar los logs
> de IIS y el origen `ConverData` en un servidor Windows real (HU-37).

#### HU-22 · Contadores en `/health/metrics`
**Como** administrador de Plataformas **quiero** peticiones, latencia p50/p95, errores y tokens en `/health/metrics` **para** integrarlos en
el monitoreo existente (SCOM o Zabbix ⚠️ S11).

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-14 | O5 | OP-05 §Observabilidad |

- **Dado** tráfico en la API, **cuando** consulto `/health/metrics`, **entonces** veo los contadores sin ningún contenido de preguntas.

> **Estado (2026-10-27):** hecho en `ConverData-API`: `MetricsMiddleware` y `GET /health/metrics` (solo administradores; peticiones, errores,
> p50/p95 por ruta, `login_failed` y `rate_limited`), con test en `api/tests/test_api.py`. Faltan los contadores de tokens y de Guardrails
> (HU-35, HU-36) y decidir si el monitoreo (⚠️ S11) usa un login de servicio o una ruta interna sin sesión.

#### HU-23 · Scorecard y `converdata metrics report`
**Como** Gerencia de Datos **quiero** un reporte de métricas de negocio, adopción y calidad **para** comparar el piloto con la línea base.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-20, HU-15 | O5, O10 | OP-05 CA2, F25 CA2, RF-54 |

- **Dado** auditoría de al menos una semana, **cuando** ejecuto `converdata metrics report --from --to`, **entonces** obtengo CSV y HTML con tiempo
  hasta "✔", escalamientos, usuarios activos, % resueltas sin escalar y Hit@k del último set de evaluación.
- **Dado** el reporte, **cuando** se genera, **entonces** se calcula desde vistas del esquema `audit` sin leer el texto de preguntas ni SQL.

> **Estado (2026-11-16):** parcial. `GET /admin/metrics` y la vista Métricas de la web muestran uso, tiempo hasta "✔", escalamientos y
> brechas desde la auditoría en archivos. Faltan el comando `converdata metrics report` (CSV y HTML) y calcularlo desde las vistas del
> esquema `audit` (tras HU-20).

#### HU-24 · Jobs de mantenimiento y regresión
**Como** DBA **quiero** tareas programadas para la purga de 180 días y la evaluación semanal **para** cumplir la retención y detectar
regresiones sin acordarme de lanzarlas.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-20, HU-33 | O5, O8 | OP-05 §Auditoría y CA5, F25 CA3 |

- **Dado** registros de auditoría con más de 180 días, **cuando** corre la purga (con una cuenta distinta de la de la API), **entonces** se eliminan y
  queda constancia de cuántos y hasta qué fecha.
- **Dado** una evaluación semanal por debajo de la línea base, **cuando** termina, **entonces** `converdata eval gate` sale con código ≠ 0 y el
  webhook de Teams avisa.

> **Estado (2026-11-16):** la regresión ya la detecta `converdata eval gate` contra `eval/baseline.yaml` (código ≠ 0) y corre en la CI. La
> purga existe (`audit.usp_purge`, `converdata audit purge`, rol `converdata_maintenance`, mínimo 180 días, deja el evento `audit_purged`).
> Faltan las tareas programadas y el aviso por webhook (HU-37).

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

> **Estado (2026-10-27):** hecho para CSV sobre el catálogo en archivos: `POST /curation/dictionary` (steward, por dominio), pestaña *Diccionario* en Curación,
> descripciones como `data_dictionary` sin pisar las `human`, hash para no repetir y test `test_ingesta_de_diccionario_no_pisa_lo_humano_y_es_idempotente`.
> Con la BD, las descripciones del diccionario se publican en `catalog` con su autor. Falta Excel, probar con un diccionario de 200
> columnas reales y llevar a la BD el registro de diccionarios ya aplicados.

#### HU-26 · Ingesta de documentos con redacción de PII
**Como** responsable de Seguridad de la Información **quiero** que los documentos se indexen con DUI, NIT, cuentas y tarjetas redactados
**para** que ningún dato de cliente quede en el índice.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-06, HU-18, ubicación de los documentos ⚠️ S6 | O6 | F23 CA3, OP-02 CA7, OP-06 CA3, RF-23 |

- **Dado** un documento con un DUI y un número de cuenta de prueba, **cuando** se ingiere, **entonces** la búsqueda de ambos literales en `knowledge` da 0.
- **Dado** un fragmento con más del 20 % de PII, **cuando** se procesa, **entonces** se descarta.
- **Dado** la carpeta compartida o SharePoint, **cuando** termina la ingesta, **entonces** los originales no se copiaron a disco ni a la BD.

> **Estado (2026-11-16):** pendiente. Hoy solo hay un detector de cinco patrones (`api/converdata_api/pii.py`: DUI, NIT, correo, teléfono,
> tarjeta) que rechaza ediciones de curación; no hay ingesta de documentos ni Presidio. La ubicación de los documentos sigue sin
> confirmar (⚠️ S6), pero el conector de carpeta y la redacción se pueden construir y probar con documentos sembrados.

#### HU-27 · Linaje desde SSIS y SQL Server Agent
**Como** ingeniero de datos **quiero** ver qué paquete o job alimenta una tabla **para** saber cómo se carga sin preguntar al equipo de ETL.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 8 | HU-06, acceso a SSISDB y msdb ⚠️ S6 | O6 | F23 CA2, OP-02 §Fuentes adicionales, RF-24 |

- **Dado** un paquete `.dtsx` de prueba en SSISDB, **cuando** se ingiere, **entonces** aparecen las aristas de linaje esperadas (origen, destino, paquete y job).
- **Dado** la pregunta "¿qué proceso llena `DWH.dim.Cliente`?", **cuando** se descubre, **entonces** el candidato muestra el paquete o job con su fuente.

> **Estado (2026-11-16):** pendiente; depende de acceso a SSISDB y msdb (⚠️ S6). El linaje de vistas ya se extrae en el build.

#### HU-28 · Reglas de negocio gestionadas
**Como** steward **quiero** registrar reglas de negocio vinculadas a activos **para** que aparezcan junto al dato correcto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | HU-06 | O6 | F23 CA4, RF-25, RF-07 |

- **Dado** la regla `BR-ONB-004` vinculada a `ClientCode`, **cuando** pregunto "¿qué reglas aplican al ClientCode?", **entonces** la respuesta la
  incluye con su fuente.
- **Dado** una regla vinculada a un activo que no veo, **cuando** pregunto, **entonces** no aparece.

> **Estado (2026-10-27):** hecho sobre archivos (`knowledge/rules/curadas.yaml`): `GET/PUT/DELETE /curation/rules` con control por dominio del steward,
> pestaña *Reglas de negocio* en Curación y test `test_reglas_de_negocio_gestionadas_por_el_steward`. Con la BD, las reglas se publican
> en `knowledge.business_rule` con historial (`test_una_regla_curada_y_una_confirmacion_llegan_a_la_bd`).

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

> **Estado (2026-11-16):** hecha sobre archivos (`knowledge/golden/confirmaciones_usuarios.yaml`): dos confirmaciones de usuarios distintos
> o una del responsable dan el bonus; el "✖" del responsable lo retira. Pendiente: pasarla a la BD (HU-06), que un solo "✖" de un
> consumidor no retire una confirmación de usuarios y no recargar todo el índice en cada voto ([calidad bancaria §5](../calidad-bancaria.md)).

#### HU-30 · Preguntar al responsable
**Como** analista BI **quiero** escalar una pregunta sin respuesta al responsable del dominio **para** obtenerla sin buscar a quién preguntar.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | HU-14, HU-20, canal de notificación ⚠️ S12 | O7 | F24 CA1, OP-04 CA7, RF-31 |

- **Dado** una respuesta con `knowledge_gap`, **cuando** pulso "Preguntar al responsable", **entonces** se crea una fila en `curation.curation_request`
  y el steward recibe un mensaje de Teams **sin el texto de la pregunta**, solo el dominio y el enlace a Curación.
- **Dado** la respuesta del steward, **cuando** otro usuario hace una pregunta equivalente, **entonces** el activo aparece como candidato principal con
  confianza ≥ 0.85.

> **Estado (2026-11-16):** hecha sobre archivos (`curation/requests.json`, `POST /curation/requests`, vista Solicitudes y webhook de Teams
> con solo el dominio y el enlace). Pendiente: pasarla a la BD (HU-06) y confirmar el canal (⚠️ S12).

#### HU-31 · Vista Curación para stewards
**Como** steward **quiero** una vista para revisar descripciones, reglas, entidades, tablas canónicas y dudas escaladas **para** responder una
vez y que quede para todos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-06, HU-13 o asignación directa en `curation.owners`, HU-30 | O7 | F24 CA3 y CA4, OP-02 §Revisión humana, RF-32 |

- **Dado** el rol `steward`, **cuando** edito una descripción, **entonces** queda con `description_source: human` y el cambio entra en el historial temporal.
- **Dado** el rol `consumer`, **cuando** abro `/curation` o intento editar, **entonces** recibo 403.
- **Dado** la cola de revisión, **cuando** la abro, **entonces** está ordenada por demanda (preguntas que tocaron cada activo).

> **Estado (2026-11-16):** hecha sobre archivos (`/curation/review`, `/curation/description`, pestañas de la vista Curación; el consumidor
> recibe 403; las ediciones con datos personales se rechazan). Pendiente: historial temporal en la BD (HU-06) y decidir si el responsable
> ve activos que su login no puede leer (PRD §13, pregunta abierta 7).

#### HU-32 · Reporte de brechas de conocimiento
**Como** Gerencia de Datos **quiero** un reporte de brechas abiertas y cerradas por dominio **para** priorizar el trabajo de los stewards.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-30, HU-23 | O7 | F24 CA5, RF-33 |

- **Dado** las 3 preguntas sin respuesta sembradas en el set de evaluación, **cuando** genero el reporte, **entonces** aparecen las 3.

> **Estado (2026-11-16):** parcial: `/admin/metrics` devuelve la tasa de brechas y la vista Métricas la muestra. Falta el reporte por
> dominio con brechas abiertas y cerradas (va con HU-23).

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

> **Estado (2026-11-16):** pendiente; necesita al steward y a los usuarios del piloto (⚠️ S9). Los 56 casos actuales (25 de VBank y 31 de
> BancosSQL) los escribió el equipo de desarrollo. Existe además una medición con 25 preguntas normativas, de tablero y de estudio
> citada en el diagrama on-premise (4 % solo con catálogo, 40 % con fuentes de conocimiento) cuyo set no está en el repo: hay que
> versionarlo o repetirla.

#### HU-34 · Medir y ajustar el canal semántico
**Como** desarrollador **quiero** medir el impacto de los embeddings en las 4 combinaciones del plan de desarrollo **para** subir el tipo B
(vocabulario) sin bajar los demás.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | — | O8 | PLAN-desarrollo §3 pasos 1–2, F2, F22 |

- **Dado** las 4 combinaciones (crudo/enriquecido × léxico/+embeddings), **cuando** se evalúan, **entonces** queda registrada la mejor en el plan de desarrollo.
- **Dado** la combinación elegida, **cuando** se compara con la línea base actual (72,4 % / 82,8 %), **entonces** el tipo B sube y A, C, D y G no bajan.

> **Estado (2026-10-29):** medidas las 4 combinaciones (tabla en [PLAN-desarrollo §2](../PLAN-desarrollo.md#2-resultados-medidos)). Elegida
> **crudo léxico**: Hit@1 93,1 % / Hit@3 93,1 %, B 87,5 % (antes 25 %), A, C, D y G sin bajar. La subida de B viene de las mejoras de
> descubrimiento del commit `9c700ec`, no de los embeddings: `bge-m3` no cambia ningún caso en crudo y sube p95 a 4,6 s. No se ajusta el
> peso en RRF. Queda abierto el paso 2 del plan (cobertura semántica) para los fallos de ranking B4 y C2, y repetir con el set real de HU-33.

#### HU-35 · Bedrock probado de punta a punta
**Como** desarrollador **quiero** probar el modelo del piloto (intención y orden) contra Bedrock por el proxy corporativo **para**
conocer latencia y coste reales antes del piloto.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 3 | cuenta AWS con Bedrock e IAM Roles Anywhere ⚠️ S4 | O8 | F16, OP-01 §Configuración AWS, D5 |

- **Dado** la configuración de Bedrock, **cuando** corre `converdata llm smoke`, **entonces** cada rol configurado responde con salida estructurada.
- **Dado** el gateway real, **cuando** corre `converdata eval gate --models`, **entonces** las suites `inyeccion` y `guardas` aprueban.
- **Dado** el set de BancosSQL con Bedrock, **cuando** se evalúa, **entonces** se reportan p50/p95 y coste por pregunta; el objetivo es p50 < 5 s y p95 < 10 s.
- **Dado** la cuenta AWS, **cuando** se revisa, **entonces** *model invocation logging* está desactivado.

> **Estado (2026-11-16):** pendiente; necesita la cuenta de AWS (⚠️ S4). El gateway está probado con Ollama y con NIM alojado.

#### HU-36 · Batería de inyección de prompt y Guardrails
**Como** responsable de Seguridad de la Información **quiero** una batería de inyecciones de prompt contra el DiscoverFlow **para** comprobar
que no revela objetos fuera de la visibilidad ni inventa activos.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Should | 3 | HU-02, HU-35 | O8 | OP-01 D6, OP-06 (tras HU-02) |

- **Dado** 20 preguntas de inyección ⚠️ S7, **cuando** se evalúan, **entonces** hay 0 fugas de permisos, 0 objetos inventados y los bloqueos de
  Guardrails quedan auditados.

> **Estado (2026-10-27):** batería de 20 inyecciones en `tests/test_prompt_injection.py` sobre el flujo determinista: 0 fugas de permisos y 0 objetos
> inventados. Falta repetirla con el gateway real (HU-35), validar las preguntas con Seguridad (⚠️ S7) y auditar los bloqueos de Guardrails.
>
> **Estado (2026-11-16):** la compuerta añade la suite `inyeccion` (25 inyecciones que nombran un activo oculto real) y `guardas` (un LLM
> simulado y hostil). Guardrails pasó a ser decisión de Seguridad (PRD §13, decisión 13).

---

### E8 · Instalación y operación (O9)

#### HU-37 · Scripts de instalación en Windows Server
**Como** administrador de Plataformas **quiero** scripts PowerShell que instalen IIS, HttpPlatformHandler, Python, Node, los dos procesos,
el `web.config`, el certificado, el firewall y las tareas programadas **para** montar un entorno igual al del piloto en menos de un día.

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 8 | HU-01, HU-03, HU-14, HU-17, HU-18 | O9 | OP-07 (HU-01), OP-04 §IIS, OP-01 §Topología |

- **Dado** un Windows Server limpio, **cuando** se ejecutan los scripts, **entonces** `https://<servidor>/` responde con TLS de la PKI corporativa,
  HTTP redirige a HTTPS y HSTS está activo.
- **Dado** un proceso Python que cae, **cuando** pasa el intervalo de supervisión, **entonces** se reinicia solo (OP-04 CA5).
- **Dado** el firewall, **cuando** se revisa, **entonces** solo hay entrada en 443 y salida a 1433, al proxy y, si se usan, a LDAP y SMB 445.
- **Dado** el streaming de `/discover/stream`, **cuando** se usa el chat, **entonces** los pasos llegan en vivo a través de IIS.
- **Dado** la instalación, **cuando** termina, **entonces** `CONVERDATA_ENV` queda fijado en `qa` o `prod` (sin él no se exige ningún ajuste seguro).

> **Estado (2026-11-16):** pendiente. Hoy el despliegue de desarrollo es `docker compose`; no hay `deploy/windows/`.

#### HU-38 · Secretos de servicio sin contraseñas en claro
**Como** responsable de Seguridad de la Información **quiero** el login de metadatos con DPAPI y Bedrock con IAM Roles Anywhere **para** no
tener claves de larga duración en el servidor.

> **Estado (2026-11-16):** pendiente; depende de las gMSA (⚠️ S10) y de la cuenta de AWS (⚠️ S4).

| Prioridad | Estimación | Depende de | Objetivo | Spec |
|---|---|---|---|---|
| Must | 5 | gMSA creadas por AD ⚠️ S10, HU-35 | O9 | OP-03 §Cuentas técnicas, OP-06 §Secretos |

- **Dado** los procesos y las tareas programadas, **cuando** se revisan, **entonces** corren con gMSA y la conexión a `ConverData` no usa contraseñas.
- **Dado** el login de metadatos, **cuando** se guarda, **entonces** está cifrado con DPAPI en el ámbito de la cuenta de servicio.
- **Dado** Bedrock, **cuando** se invoca, **entonces** usa IAM Roles Anywhere con un certificado de clave no exportable y solo `bedrock:InvokeModel*`.

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
| S5 | ~~Hay una instancia SQL Server 2025 de desarrollo~~ Ya no aplica: la BD usa tablas normales (SQL Server 2016+) y el equipo de desarrollo tiene SQL Server 2022 Express. Queda confirmar la versión de la instancia del piloto | HU-05 en adelante, O2 | PRD §13, decisión 10 |
| S6 | Diccionarios y documentos del dominio piloto están en una carpeta compartida o SharePoint, y SSISDB y msdb son accesibles con un login técnico | HU-26, HU-27, O6 | Pregunta abierta 1 del PRD |
| S7 | Batería de 20 inyecciones de prompt; umbrales de latencia con Bedrock iguales a los de F22 | HU-36, O8 | F25 no fija el tamaño de la batería |
| S8 | "Instalación reproducible" = desde cero en ≤ 1 día laboral con los scripts | O9 | No hay requisito de tiempo de instalación |
| S9 | Steward funcional y técnico del dominio asignados con tiempo desde el sprint 5 (2027-01-11) | HU-31, HU-33, O7, O8 | PRD §11 lo pide para las semanas 2–3 del piloto, pero el set de evaluación hace falta antes |
| S10 | AD crea las gMSA y permite LDAP de solo lectura | HU-13, HU-38 | Dependencia de Plataformas |
| S11 | El monitoreo existente es SCOM o Zabbix | HU-22 | OP-05 lo da solo como ejemplo |
| S12 | Canal de notificación a stewards: webhook de Teams (es lo construido); correo si el banco lo exige | HU-30 | Pregunta abierta 4 del PRD |
| S13 | Gestor de requerimientos y canal de consultas para la línea base identificados antes del 2027-01-25 | HU-40 | Pregunta abierta 2 del PRD |

## 6. Trazabilidad con la revisión de huecos (2026-10-27)
Los huecos son los de la revisión del 2026-10-27; los que nombran vectores, tablas de grafo, Chainlit o el servicio Builder se cerraron
el 2026-11-16 retirando la pieza (PRD §13), no construyéndola.

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
