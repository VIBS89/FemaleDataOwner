# Cinco sesiones de desarrollo con goals · versión on-premise

> 2026-10-27. Parte del [backlog on-premise](on-premise.md) y del [reparto entre 5 desarrolladores](reparto-5-devs.md); usa las situaciones
> de desarrollo de [OP-09](../specs/on-premise/OP-09-situaciones-desarrollo.md) y la interfaz de [OP-08](../specs/on-premise/OP-08-interfaz-web.md).
> Cada sesión es una sesión de Claude Code (o un desarrollador con Claude Code) en **su propia rama y worktree**, con su `/goal`.

## 1. Cómo se usa
1. Crear el worktree de la sesión: `git worktree add ../FemaleDataOwner-s<N> -b sesion/<N>-<carril>` y abrir Claude Code allí.
   Conviene crear los worktrees **fuera de OneDrive**: la sincronización de miles de archivos de `node_modules` y `.venv` es lenta y bloquea archivos.
2. Pegar el **mensaje de arranque** de la sesión (§3). Le da el contexto, los archivos que le pertenecen y los que no puede tocar.
3. Fijar el goal de la situación disponible con `/goal <condición>`. Las condiciones de §3 están escritas para el evaluador de `/goal`, que
   **no ejecuta comandos ni lee archivos**: solo juzga lo que Claude muestra en la conversación. Por eso cada condición pide mostrar la salida
   de los comandos de verificación.
4. Usar el modo automático (o permisos amplios para `pytest`, `npm` y `git`) si la sesión debe avanzar sin supervisión; `/goal` no cambia los permisos.
5. Cuando el goal se cumple: abrir un PR por historia (o por grupo de historias pequeñas), actualizar el **Estado** de esas historias en
   [on-premise.md](on-premise.md) y pasar al goal de la siguiente situación cuando esté disponible.
6. `/goal` sin argumentos muestra el avance; `/goal clear` lo detiene.

### Reglas comunes a todos los goals
- La suite base de SD-1 (`python -m pytest -q`) termina **sin fallos** y Claude muestra su línea de resumen. Los tests de SD-2 a SD-5 pueden quedar omitidos con motivo.
- Si la sesión toca `web/`: `npx tsc --noEmit` y `npx eslint .` en `web/` sin errores, con la salida mostrada.
- No se modifica ningún archivo fuera de los **dueños** de la sesión (§2), salvo la línea `include_router` de su área en `api/converdata_api/main.py`
  y el estado de sus historias en `docs/backlog/on-premise.md`. Claude muestra `git diff --stat main...HEAD` al final para probarlo.
- No se omiten hooks (`--no-verify`) ni se editan `.env`, lockfiles a mano ni `config/models.yaml` (los bloquean los hooks del repo).
- Toda condición tiene tope de turnos: si se alcanza, Claude se detiene y deja escrito qué falta y por qué.

## 2. Mapa de sesiones
| Sesión | Carril | Historias | Dueña de | Situación base → objetivo | Depende de otras sesiones |
|---|---|---|---|---|---|
| **S1** | Persistencia y adaptadores | HU-04, HU-05, HU-06, HU-09, HU-07, HU-08, HU-39 | `db/`, `deploy/dev/`, `src/converdata/memory/`, `catalog/`, `graph/` (persistencia), `bootstrap.py`, `config.py`, `pyproject.toml` (marcas) | SD-1 → SD-3 | Ninguna; publica `CatalogStore` y las marcas de pytest |
| **S2** | Identidad, API y MCP | HU-11, HU-12, HU-10, HU-13, HU-14, HU-15, HU-16, HU-17 (sobre `web/`) | `api/converdata_api/` (`main.py`, `routers/`, `vault.py`, `connector.py`, `tokens.py`, `mcp_mount.py`), `src/converdata/identity/`, `integration/mcp/`, `web/src/app/login`, `web/src/app/(app)/page.tsx`, `web/src/components/chat`, `web/src/app/api/` | SD-1 → SD-3 (+SD-5 para OP-08) | Ninguna para empezar; usa `CatalogStore` de S1 cuando esté |
| **S3** | Auditoría, observabilidad e instalación | HU-20, HU-21 (cierre), HU-22 (cierre), HU-23, HU-24, HU-37, HU-38, OP-08 en IIS | `src/converdata/audit/`, `observability/`, `deploy/windows/`, `api/converdata_api/audit.py`, `routers/metrics.py`, `web/src/app/(app)/metricas` | SD-1 → SD-3 → SD-5 | Ninguna para empezar; HU-37 se cierra en SD-5 |
| **S4** | Curación, aprendizaje y piloto | HU-28, HU-29, HU-30, HU-31, HU-32, HU-33 (estructura), HU-40 (plantillas) | `src/converdata/application/curation*`, puertos `CurationStore`, `GoldenStore`, `Notifier`, `api/converdata_api/curation.py`, `routers/curation.py`, `web/src/app/(app)/curacion`, `solicitudes`, `docs/piloto/` | SD-1 → SD-3 | Ninguna; usa `CurationStore` de archivos hasta tener SQL Server |
| **S5** | Calidad del agente y fuentes de conocimiento | HU-34, HU-35, HU-36, HU-18, HU-25 (Excel), HU-26, HU-27 | `src/converdata/discovery/`, `flows/`, `llm/`, `evaluation/`, `builder/`, `knowledge/`, `routers/admin.py`, `tests/fixtures/` (solo añadir), `eval/` | SD-1 → SD-2 → SD-4 | Ninguna; HU-27 usa el grafo en memoria hasta que S1 cierre HU-07 |

**Por qué son independientes:** cada sesión es dueña de carpetas distintas y se comunica con las demás **solo por puertos** (`AuditSink`,
`VectorStore`, `CatalogStore`, `CurationStore`, `ObjectLister`, `SessionVault`) que tienen adaptador de archivos desde el primer día (OP-09).
Ninguna espera a otra para cumplir su goal de SD-1; las situaciones superiores se desbloquean por infraestructura, no por otra sesión.

**Único punto de contacto:** `api/converdata_api/main.py`. S2 lo parte en `routers/` como **primer commit** (goal S2-0) y lo fusiona en `main` en el
día 1. Mientras tanto, S3, S4 y S5 crean su propio `routers/<área>.py` con un `APIRouter` y solo añaden su línea `app.include_router(...)` al
fusionar. El mismo criterio vale para `web/src/lib/api.ts` y `types.ts`: S2 los separa por área en el goal S2-0.

---

## 3. Sesiones

### S1 · Persistencia y adaptadores (BD `ConverData`)
**Mensaje de arranque**
> Eres la sesión S1 de `docs/backlog/sesiones-goals.md`. Lee OP-02, OP-09, `db/converdata/001_esquemas.sql`, `src/converdata/memory/`,
> `src/converdata/catalog/` y `bootstrap.py`. Trabaja con TDD (skill `tdd-ciclo`) y las convenciones de `ddd-convenciones`. Solo puedes
> modificar los archivos de los que S1 es dueña. Empieza por las marcas de pytest y el puerto `CatalogStore` con su adaptador de archivos,
> y después HU-04, HU-05, HU-06 y HU-09.

**Goal S1-A · SD-1 (sin SQL Server)**
```
/goal En la rama sesion/1-persistencia: (1) pyproject.toml registra las marcas llm_local, sqlserver, bedrock y windows_server, y un test con marca sqlserver sin CONVERDATA_TEST_DB aparece como "skipped" con motivo; (2) existe el puerto CatalogStore con adaptador de archivos y una batería de tests de contrato parametrizada por adaptador que pasa con el de archivos; (3) bootstrap.py elige adaptadores solo con CONVERDATA_STORE, CONVERDATA_AUDIT y CONVERDATA_DB según OP-09, y con CONVERDATA_ENV=qa y CONVERDATA_STORE=files el arranque falla con un mensaje que nombra la variable (test que lo prueba); (4) db/converdata/ tiene los scripts numerados con los esquemas estate (NODE/EDGE) y semantic, la tabla dbo.schema_version y el rol converdata_builder, y el rol converdata_app tiene DENY de UPDATE y DELETE en audit (HU-04); (5) muestras la salida de `python -m pytest -q` sin fallos y de `git diff --stat main...HEAD` solo con archivos de S1. O detente tras 40 turnos y explica qué falta.
```

**Goal S1-B · SD-3 (SQL Server 2025 disponible)**
```
/goal Con CONVERDATA_TEST_DB apuntando a SQL Server 2025 con Full-Text: (1) deploy/dev/sqlserver/ crea la BD ConverData, aplica db/converdata/*.sql en orden y crea los logins de prueba cd_analista y cd_rrhh sin contraseñas en el repo; (2) `python -m pytest -q -m sqlserver` pasa los tests de contrato de VectorStore (search_tables, search_columns, search_knowledge, search_golden_discovery) y de CatalogStore con el adaptador sqlserver, incluido el filtro visible_ids antes del ranking (HU-05); (3) `converdata catalog build` escribe en catalog con historial temporal y un test muestra la versión anterior de una descripción y quién la cambió, sin pisar ediciones human (HU-06); (4) con CONVERDATA_STORE=sqlserver la API arranca y responde una pregunta del set de BancosSQL (HU-09); (5) muestras Hit@3 de `converdata eval discovery` con el almacén en BD y en memoria y la diferencia es ≤ 1 punto; (6) la suite completa `python -m pytest -q` sigue sin fallos y muestras ambas salidas. O detente tras 60 turnos y explica qué falta.
```
Después: HU-07 (grafo en `estate`), HU-08 (export a YAML) y HU-39 (restauración, en SD-5 junto con S3).

---

### S2 · Identidad, API y MCP
**Mensaje de arranque**
> Eres la sesión S2 de `docs/backlog/sesiones-goals.md`. Lee OP-03, OP-04, OP-08, F12, F14 y `api/converdata_api/`. Tu primer entregable
> (S2-0) es partir `main.py` en `routers/` sin cambiar el comportamiento, para fusionarlo en `main` hoy. Después HU-11, HU-12, HU-10, HU-14,
> HU-15 y el cierre de HU-16. Solo modificas los archivos de los que S2 es dueña. Usa el agente `verificador-contrato-web-api` antes de cada PR.

**Goal S2-0 · SD-1 (refactor de arranque, bloquea a nadie si se fusiona el día 1)**
```
/goal api/converdata_api/main.py solo crea la app, el middleware y llama a include_router; todas las rutas actuales viven en api/converdata_api/routers/ (auth, discover, curation, catalog, admin, metrics, me) con las mismas rutas, métodos y códigos; web/src/lib/api.ts y types.ts están separados por área (discover, curation, admin) sin cambiar el comportamiento; muestras la salida de `python -m pytest -q` sin fallos, de `npx tsc --noEmit` y `npx eslint .` en web/ sin errores, y la lista de rutas de app.routes antes y después idéntica. O detente tras 20 turnos.
```

**Goal S2-A · SD-1**
```
/goal En la rama sesion/2-identidad-api: (1) SessionVault cifra contraseñas con Fernet y clave efímera, expira a las 8 h sin actividad con expiración deslizante, y logout o reinicio invalidan el session_id (tests de HU-11); (2) ConnectionFactory.for_session construye cadenas ODBC con Encrypt=yes y ApplicationName=ConverData y descifra la contraseña solo durante connect (test con fake de pyodbc, HU-12); (3) POST /login devuelve session_id, expires_at, servers [{alias, ok}] y databases, valida cada servidor por separado y no revela objetos con contraseña errónea (HU-10); (4) la API acepta cookie o Bearer, devuelve 401 si llegan los dos con valores distintos y 403 en POST con Origin ajeno (OP-08 §Sesión); (5) ninguna ruta ni herramienta MCP acepta user_id, session_id ni credenciales como argumento (test con argumentos manipulados, HU-16); (6) un test busca la contraseña de prueba en logs, auditoría y archivos generados y da 0; (7) muestras `python -m pytest -q` sin fallos y `npx tsc --noEmit` limpio. O detente tras 50 turnos y explica qué falta.
```

**Goal S2-B · SD-3**
```
/goal Con CONVERDATA_TEST_DB y los logins cd_analista y cd_rrhh de SD-3: `python -m pytest -q -m sqlserver` muestra que cd_analista no recibe objetos de RRHH por /api/discover, /api/assets ni /mcp (404 sin revelar existencia), que sys.dm_exec_sessions muestra program_name ConverData con el login del usuario, y que la suite completa sigue sin fallos; muestras ambas salidas. O detente tras 30 turnos.
```
Después: HU-13 (grupos de AD con LDAP falso en SD-1 y real en SD-5), HU-17 reescrita sobre `web/` (OP-08 CA1, CA2 y CA6), `CONVERDATA_MCP_HOSTS` y límite por minuto en `/mcp`.

---

### S3 · Auditoría, observabilidad e instalación
**Mensaje de arranque**
> Eres la sesión S3 de `docs/backlog/sesiones-goals.md`. Lee OP-05, OP-06, OP-07, OP-08, F11 y `src/converdata/audit/`. Trabajas contra
> el puerto `AuditSink`; no cambies su firma sin avisar a las demás sesiones. Solo modificas los archivos de los que S3 es dueña. Los scripts
> PowerShell van en `deploy/windows/` y se verifican con PSScriptAnalyzer y Pester mientras no haya servidor.

**Goal S3-A · SD-1**
```
/goal En la rama sesion/3-auditoria-operacion: (1) SqlServerAuditSink escribe audit_question, audit_step y audit_discovery en una sola transacción y, con fail_open false y la BD caída (fake que lanza error), la API no entrega la respuesta y registra el error (tests de HU-20 con fake de pyodbc); (2) un test de flujo completo con un literal marcado no encuentra la pregunta, SQL, filas, cookie ni Authorization en logs JSON ni en auditoría; (3) /health/metrics incluye tokens y bloqueos de Guardrails sin contenido; (4) `converdata metrics report --from --to` genera CSV y HTML desde la auditoría de archivos sin leer el texto de las preguntas (HU-23); (5) deploy/windows/ contiene 01 a 10 de OP-07 más web.config de ConverData-UI con HttpPlatformHandler, node server.js, responseBufferLimit 0 y cabeceras de OP-08, y entorno.dev.psd1 sin secretos; (6) muestras la salida de Invoke-ScriptAnalyzer sin errores sobre deploy/windows, de Invoke-Pester con -WhatIf en verde y de `python -m pytest -q` sin fallos. O detente tras 50 turnos y explica qué falta.
```

**Goal S3-B · SD-3**
```
/goal Con CONVERDATA_TEST_DB: `python -m pytest -q -m sqlserver` muestra que una pregunta deja exactamente 1 fila en audit_question, N en audit_step y una por candidato en audit_discovery; que converdata_app recibe error al hacer UPDATE o DELETE en audit; que el job de purga borra solo registros de más de 180 días; y que la suite completa sigue sin fallos. Muestras ambas salidas. O detente tras 30 turnos.
```

**Goal S3-C · SD-5 (Windows Server de QA)**
```
/goal En el Windows Server de QA: ejecutas deploy/windows 01 a 10 con entorno.qa.psd1 y muestras su salida; 10-verificar.ps1 termina en verde (health, login de prueba, /api/discover de una pregunta conocida y escritura en audit); una segunda ejecución de 01 a 09 informa sin cambios; muestras las cabeceras de https://<servidor>/ con HSTS, CSP y X-Frame-Options; matas el proceso node de ConverData-UI y el de la API y muestras que se recuperan solos (OP-07 CA7, OP-08 CA7). O detente tras 40 turnos y documenta los pasos manuales que faltaron en OP-07.
```

---

### S4 · Curación, aprendizaje y piloto
**Mensaje de arranque**
> Eres la sesión S4 de `docs/backlog/sesiones-goals.md`. Lee F24, OP-02 §Revisión humana, OP-04 CA6–CA7, `api/converdata_api/curation.py`
> y `web/src/app/(app)/curacion`. Hoy la curación vive en archivos sin puerto: tu primer paso es extraer `CurationStore`, `GoldenStore` y
> `Notifier` como puertos con adaptador de archivos, sin cambiar el comportamiento. Solo modificas los archivos de los que S4 es dueña.

**Goal S4-A · SD-1**
```
/goal En la rama sesion/4-curacion: (1) existen los puertos CurationStore, GoldenStore y Notifier en la capa de aplicación con adaptadores de archivos y tests de contrato parametrizados por adaptador; curation.py usa solo los puertos; (2) un ✔ de steward da el bonus de golden a una pregunta equivalente de otro usuario y un ✖ posterior lo retira, y knowledge.golden_discovery solo guarda la plantilla anonimizada (HU-29); (3) "Preguntar al responsable" crea la solicitud y el Notifier recibe un mensaje sin el texto de la pregunta, solo dominio y enlace a /curacion, y la respuesta del steward sale como candidato principal con confianza ≥ 0.85 (HU-30); (4) un consumer recibe 403 en todas las rutas de curación y la cola de revisión sale ordenada por demanda (HU-31); (5) el reporte de brechas lista las 3 preguntas sin respuesta sembradas (HU-32); (6) docs/piloto/ tiene la plantilla del set de evaluación (50–80 preguntas, 5 sin respuesta) y de la línea base de F25; (7) muestras `python -m pytest -q` sin fallos y `npx tsc --noEmit` y `npx eslint .` limpios en web/. O detente tras 50 turnos y explica qué falta.
```

**Goal S4-B · SD-3**
```
/goal Con CONVERDATA_TEST_DB: los tests de contrato de CurationStore y GoldenStore pasan con el adaptador sqlserver (`python -m pytest -q -m sqlserver`), una descripción editada por un steward queda con description_source human en el historial temporal con su autor, y la suite completa sigue sin fallos. Muestras ambas salidas. O detente tras 30 turnos.
```
Fuera de código (no tiene goal de Claude): convocar al steward (⚠️ S9), fijar el canal de notificación (⚠️ S12) y recoger las 50–80 preguntas reales (HU-33).

---

### S5 · Calidad del agente y fuentes de conocimiento
**Mensaje de arranque**
> Eres la sesión S5 de `docs/backlog/sesiones-goals.md`. Lee F2, F16, F22, F23, F25, el PLAN-desarrollo §3 y `src/converdata/discovery/`.
> Regla del plan: un cambio de lógica se acepta solo si mejora el set de evaluación sin bajar otros tipos ni crear fugas; usa el agente
> `evaluador-descubrimiento` antes de cada PR. Solo modificas los archivos de los que S5 es dueña.

**Goal S5-A · SD-1**
```
/goal En la rama sesion/5-calidad-fuentes: (1) la ingesta de diccionarios acepta Excel además de CSV con las mismas reglas (data_dictionary sin pisar human, hash sin reindexar) y hay un test con 200 columnas (HU-25); (2) la ingesta de documentos redacta DUI, NIT, cuentas y tarjetas, descarta fragmentos con más del 20 % de PII y un test busca los literales marcados en knowledge y da 0 (HU-26); (3) un parser de .dtsx de prueba en tests/fixtures produce las aristas de linaje esperadas y "¿qué proceso llena DWH.dim.Cliente?" devuelve el paquete con su fuente (HU-27, grafo en memoria); (4) /api/admin/catalog/refresh y /api/admin/knowledge/ingest encolan con token de servicio y devuelven 403 a IPs fuera de la lista (HU-18, en routers/admin.py); (5) muestras `converdata eval discovery` sin regresión de Hit@1 ni Hit@3 por tipo frente a la línea base actual, con 0 fugas y 0 inventados, y `python -m pytest -q` sin fallos. O detente tras 50 turnos y explica qué falta.
```

**Goal S5-B · SD-2 (Ollama o NIM con datos de prueba)**
```
/goal Con bge-m3 disponible: evalúas las 4 combinaciones de PLAN-desarrollo §3 (crudo/enriquecido × léxico/+embeddings), muestras la tabla de Hit@1, Hit@3 y MRR por tipo de pregunta de cada una, registras la mejor en docs/PLAN-desarrollo.md y muestras que con ella el tipo B sube y A, C, D y G no bajan frente a 72,4 % / 82,8 % (HU-34); `python -m pytest -q` sigue sin fallos. O detente tras 30 turnos.
```

**Goal S5-C · SD-4 (Bedrock)**
```
/goal Con la configuración de Bedrock: `converdata llm smoke` muestra que planner, fast, judge y embed responden con salida estructurada y embeddings de 1024 dimensiones; `converdata eval discovery` con Bedrock muestra p50, p95 y coste por pregunta; `python -m pytest -q -m bedrock` repite la batería de 20 inyecciones con 0 fugas, 0 inventados y los bloqueos de Guardrails auditados (HU-35, HU-36); y muestras que model invocation logging está desactivado en la cuenta. O detente tras 30 turnos y explica qué falta.
```

---

## 4. Integración entre sesiones
| Cuándo | Qué se fusiona | Quién lo verifica |
|---|---|---|
| Día 1 | S2-0 (routers y `api.ts` por área) | S2 con `verificador-contrato-web-api` |
| Al cumplir cada goal A | Un PR por historia; todos deben pasar la suite SD-1 | El revisor del PR con `revisor-arquitectura-specs` y, si toca identidad, auditoría o LLM, `revisor-seguridad-datos` |
| Al cumplir S1-B | Las demás sesiones activan su goal B (SD-3) contra la misma instancia | Cada sesión |
| Antes del sprint 6 | S3-C en el servidor de QA con todo fusionado | S3 con S1 (HU-39) |
| Piloto | HU-40 y HU-41 (Gerencia de Datos, fuera de los goals) | S4 coordina |

## 5. Cobertura de los huecos de la revisión del 2026-10-27
| Hueco | Spec que lo cierra | Sesión |
|---|---|---|
| Specs piden Chainlit; la UI real es Next.js | OP-08 | S2 (pantallas), S3 (IIS) |
| Rutas `/discover` frente a `/api/discover` | OP-08 §Equivalencia de rutas | S2 |
| Sesión por cookie no especificada | OP-08 §Sesión en el navegador | S2 |
| Sin forma de avanzar sin SQL Server, AWS o servidor | OP-09 §Situaciones | Todas |
| Sin selección de adaptadores por configuración ni guarda de entorno | OP-09 §Selección de adaptadores | S1 |
| Curación en archivos sin puerto | OP-09 §Puertos que faltan | S4 |
| Tests de infraestructura sin marcas ni omisión explícita | OP-09 §Tests por situación | S1 |
