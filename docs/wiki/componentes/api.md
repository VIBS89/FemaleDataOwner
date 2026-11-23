# ConverData-API

Actualizado el 2026-11-17.

**Para qué sirve.** Es el único proceso de backend en línea. Atiende a la web (Next.js la llama bajo `/api/*`), a los clientes MCP
(`/mcp`) y a scripts con `Bearer`. Valida el login SQL de cada usuario contra los servidores del inventario, guarda la credencial
cifrada en memoria, calcula qué objetos puede ver, ejecuta el DiscoverFlow, sirve el explorador del catálogo, la curación y la
administración, y lanza la construcción del catálogo con la credencial del administrador.

**Lo esencial**
- FastAPI en **un solo proceso** (`uvicorn converdata_api.main:app --app-dir api`): sesiones, límites y cachés viven en su memoria.
- La identidad sale solo de la cookie `cd_session` o del `Authorization: Bearer`. Ninguna ruta acepta `user_id` ni credenciales,
  salvo el login.
- `visible_ids` se calcula con el login del propio usuario en cada servidor y se cachea 15 min.
- Con `CONVERDATA_DB` el catálogo, la curación y la auditoría viven en la BD `ConverData`; sin ella, en archivos (solo desarrollo).
- Todo cambio de estado se audita antes de aplicarse; si la auditoría falla, el cambio no ocurre.
- Con `CONVERDATA_ENV=qa|prod` la API se niega a arrancar con ajustes inseguros.

Diagramas: [componentes de la API (C4)](../../architecture/c4-componentes-api.html) ·
[on-premise](../../architecture/onpremise-architecture.html) · [permisos heredados](../../architecture/permisos-heredados.html).

## Responsabilidades
- Autenticación con login SQL, sesiones y roles (`consumer`, `steward`, `data_admin`).
- Visibilidad por usuario (F14) y entrega de todo filtrado por ella.
- DiscoverFlow por HTTP y SSE, con límite de ritmo y tope diario de tokens.
- Explorador del catálogo y ficha de activo.
- Curación: dudas escaladas, votos, descripciones, reglas, diccionario e historial.
- Administración: inventario, responsables, build del catálogo, auditoría, sesiones, métricas y manual.
- Montaje del servidor MCP con las mismas sesiones y topes.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| `create_app`, rutas | `api/converdata_api/main.py` | Composición, dependencias de rol, rutas, `MetricsMiddleware`, `RateLimiter` |
| `AgentRuntime` | `api/converdata_api/runtime.py` | Inventario, `DiscoverService` vigente, `visible_ids`, votos, curación, build |
| `SecurityMiddleware`, `LoginThrottle`, validaciones | `api/converdata_api/security.py` | Cabeceras, CSRF por `Origin`, tope de cuerpo, bloqueo de logins, reglas de qa/prod |
| `SessionVault` | `api/converdata_api/vault.py` | Sesiones en memoria con contraseñas cifradas (Fernet, clave efímera) |
| `SqlConnector`, `DemoConnector` | `api/converdata_api/connector.py` | Conexión ODBC con la credencial del usuario; servidores simulados |
| `CurationDesk`, métricas | `api/converdata_api/curation.py` | Responsables, dudas, aviso por webhook, cola de revisión, scorecard |
| `find_pii` | `api/converdata_api/pii.py` | Rechaza textos de curación con datos personales |
| `TokenLedger` | `api/converdata_api/tokens.py` | Tope diario de tokens por usuario (UTC) |
| `FileAuditSink`, `open_audit` | `api/converdata_api/audit.py` | Auditoría en JSONL encadenado o en SQL Server |
| `build_mcp_mount` | `api/converdata_api/mcp_mount.py` | `/mcp` con `Bearer` de la misma sesión |
| `ApiSettings` | `api/converdata_api/settings.py` | Variables `CONVERDATA_*` |
| Modo demo | `api/converdata_api/demo.py`, `demo_history.py` | Inventario y conocimiento de los fixtures; historial simulado |

## Rutas por rol
Sacadas de `api/converdata_api/main.py`. La web las llama con el prefijo `/api`.

**Públicas**
| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/health` | `{ok: true}` |
| GET | `/setup/status` | Si hay inventario y catálogo, servidores (sin host), estado del build, si se pide código de instalación |
| POST | `/auth/login` (alias `/login`) | Login SQL o primer arranque; devuelve sesión, servidores, BDs visibles y roles |

**Cualquier sesión (`consumer`)**
| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/auth/logout` (alias `/logout`) | Cierra la sesión |
| GET | `/auth/me` | Usuario, roles, dominios y servidores |
| POST | `/discover` | DiscoverFlow; cabecera `X-Trace-Id` |
| POST | `/discover/stream` | Igual por SSE: eventos `step` y `answer` |
| POST | `/discover/feedback` | Voto ✔/✖ sobre un activo mostrado en una respuesta propia |
| POST | `/curation/requests` | Escala una duda al responsable del dominio |
| GET | `/me/requests` | Mis dudas, con la respuesta filtrada por mi visibilidad |
| GET | `/me/history` | Mis preguntas en la auditoría |
| GET | `/catalog/databases`, `/catalog/objects`, `/catalog/object?id=` | Explorador, solo lo visible |
| GET | `/assets/{asset_key}` | Ficha del activo (copia de referencia si es visible) |

**Responsable (`steward` o `data_admin`; dependencia `steward_session`)**
| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/curation/requests?status=open\|answered\|all` | Bandeja de dudas de sus dominios |
| POST | `/curation/requests/{request_id}/answer` | Responde con un activo (`asset`) o "no hay fuente" (`no_source`) |
| GET | `/curation/review` | Activos sin descripción o con descripción generada, por demanda |
| PUT | `/curation/description` | Descripción y sinónimos en todas las copias físicas |
| GET | `/curation/history?asset_key=` | Versiones de la descripción (solo con BD) |
| POST | `/curation/dictionary` | Diccionario CSV (hasta 2 MB de texto) |
| GET, PUT | `/curation/rules` | Reglas gestionadas por responsables |
| DELETE | `/curation/rules/{rule_id}` | Borra una regla gestionada |

**Administrador (`data_admin`; dependencia `admin_session`)**
| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/health/metrics` | Contadores, p50/p95 por ruta, tokens |
| GET | `/admin/metrics?days=` | Scorecard de F25 desde la auditoría |
| GET, PUT | `/admin/inventory` | Inventario; los servidores nuevos se prueban con la credencial de la sesión |
| POST | `/admin/inventory/probe` | Asistente: con `{host, trust_server_certificate}` o `{server_id}`, prueba la conexión y lista las bases de usuario (acceso, tablas y vistas). No guarda nada |
| POST | `/admin/inventory/connect` | Asistente: añade un servidor o cambia las bases de uno, sin reenviar el inventario, y lanza el build (202) |
| GET, PUT | `/admin/stewards` | Responsables por login y dominio |
| POST, GET | `/admin/catalog/build` | Lanza y consulta el build del catálogo |
| GET | `/admin/audit?limit=&kind=` | Lectura de la auditoría (se audita) |
| GET | `/admin/audit/verify` | Integridad: cadena de hashes o permisos en SQL Server |
| GET | `/admin/manual` | Manual de desarrollo (se audita antes de entregarlo) |
| GET | `/admin/sessions` | Sesiones activas, sin tokens |
| DELETE | `/admin/sessions/{user_id}` | Revoca todas las sesiones de un usuario |

**MCP**: `/mcp` (montado al final en `/`), con `Bearer` de `/auth/login`. Herramientas de solo lectura: `discover`, `get_asset`,
`get_related`, `find_alternatives`, `list_business_rules`, `get_lineage`, `search_catalog`, `where_is`, `find_join_path`,
`estate_overview` (`src/converdata/integration/mcp/server.py`).

Códigos habituales: 401 sin sesión, 403 sin rol, 404 lo que no existe o no se ve, 409 sin catálogo, 422 texto con datos personales,
429 ritmo, tope de tokens o login bloqueado.

## Cómo funciona

### Ciclo de vida de una sesión
1. `POST /auth/login` con `login`, `password` y, opcional, `servers` (ids; vacío = todos). La misma credencial se prueba en cada
   servidor elegido (`main.py:513`).
2. Antes de probar: si el login o el origen están bloqueados, 429 con `Retry-After` sin tocar SQL Server.
3. `connector.identify` ejecuta `SELECT SUSER_SNAME(), IS_SRVROLEMEMBER('sysadmin'), HAS_PERMS_BY_NAME(... 'VIEW ANY DEFINITION')`.
   Credencial errónea suma un fallo; un servidor caído no.
4. Sin ningún servidor válido: evento `login_failed` (y `login_locked` si bloquea) y 401.
5. Rol `data_admin` (`main.py:533`): con `CONVERDATA_ADMINS_ONLY`, solo si el login está en `CONVERDATA_ADMINS` y la identidad es
   de confianza; sin él, también si es sysadmin o tiene `VIEW ANY DEFINITION` en algún servidor validado.
6. `vault.create` guarda la sesión (token de 256 bits; cierra la más antigua si pasa de 5). Evento `login`; si no se escribe, la
   sesión se borra y no se entrega (`main.py:548`).
7. Cookie `cd_session`: `HttpOnly`, `SameSite=Lax`, `Secure` según `CONVERDATA_COOKIE_SECURE`, `max_age = min(ttl, vida máxima)`.
8. En cada petición, `vault.get` renueva `last_seen`. Caduca a las 8 h sin actividad o 12 h de vida.
9. Termina con `/auth/logout`, `DELETE /admin/sessions/{user_id}`, caducidad o reinicio del proceso (la clave Fernet es efímera).

### Cómo se arma `visible_ids`
`AgentRuntime.visible_ids` (`runtime.py:266`):
1. Sin catálogo, conjunto vacío.
2. Caché por sesión válida si coincide la versión del catálogo y no pasaron `CONVERDATA_VISIBILITY_TTL_S` (900 s).
3. Por cada servidor de la sesión: BDs del catálogo en ese servidor; `PyodbcObjectLister` usa la conexión del usuario:
   pregunta `HAS_DBACCESS` desde `master`, abre solo las bases con acceso y lista tablas/vistas con `SELECT` y SPs con `EXECUTE` (`src/converdata/identity/visibility.py:14`).
4. Cada objeto se convierte en id físico `<env>:<server>.<db>.<schema>.<obj>`.
5. Si un servidor falla, no aporta nada (fail-closed) y se registra un aviso.
Cada recarga del catálogo sube `version` y vacía la caché.

### Primer arranque
Con el inventario vacío (`main.py:489`):
1. El login exige `host` (validado por `valid_host`).
2. Si hay `CONVERDATA_SETUP_TOKEN`, el `setup_token` debe coincidir (`hmac.compare_digest`); si no, evento `setup_denied` y fallo
   por origen. En qa/prod el código es obligatorio (`inventory_violations`).
3. En qa/prod no se admite `trust_server_certificate`.
4. `server_from_host` crea el servidor (id derivado del host, `is_reference`, `databases: ["*"]`).
5. Solo continúa un login que puede descubrir (sysadmin, `VIEW ANY DEFINITION` o en la lista); si no, 403.
6. Evento `inventory_updated` (con host) antes de guardar el inventario. La sesión nace con `data_admin`.
El catálogo aún no existe: `/discover` y el explorador responden 409 hasta el primer build.

### Construcción del catálogo bajo demanda
`POST /admin/catalog/build` → `runtime.start_build` (`runtime.py:403`): un solo build a la vez, en un hilo.
1. Evento `catalog_build_started`.
2. Copia el inventario. Con BD, trabaja en un directorio temporal que se borra al terminar.
3. Cada servidor se lee con la **credencial del administrador** en la sesión (`source_factory`); sin ella, `PermissionError`.
4. `enrich: true` y `CONVERDATA_MODELS` → descripciones sugeridas por el rol `planner` (`LlmEnricher`).
5. `refresh_catalog` construye y, con BD, publica (alcance `build`; `all` en demo). La BD `ConverData` no se cataloga.
6. Si algún servidor respondió, recarga el servicio antes de marcar el estado.
7. Evento `catalog_build_finished` con estado, objetos e ids de servidores fallidos, sin el texto del error.
Además, `runtime.refresh` (como mucho cada 15 s) carga lo que publique otro proceso, como el Builder programado.

### Conectar un servidor con el asistente
El asistente "Conectar base de datos" de Administración usa dos rutas (`main.py`, `probe_inventory` y `connect_inventory`):
1. `POST /admin/inventory/probe` con un host nuevo o el `server_id` de uno del inventario (con su propia configuración). Un host
   que ya está en el inventario responde 409. En qa/prod, `trust_server_certificate: true` responde 400.
2. La credencial es la de la sesión en ese servidor o, si no la tiene, la misma plantilla que usa `PUT /admin/inventory`
   (`session_credential`). Hasta 30 sondeos por minuto y administrador.
3. Evento `inventory_probe` (host, sin contraseña) **antes** de conectar; si no se registra, no se conecta.
4. `connector.probe` lee `sys.databases` y `HAS_DBACCESS` desde `master`; solo abre las bases con acceso para contar tablas y
   vistas en `sys.objects` (lo que el login ve). Un conteo que falla sale `null` y sigue; a partir de 100 bases no se cuenta.
5. Se quitan las bases de sistema y la propia (`ConverData` o la de `CONVERDATA_DB`), como en el build.
6. Un fallo de login o de red responde 200 con `connected: false` y el mensaje de `LoginFailed` (sin host, login ni texto del
   driver); cualquier otro error, un mensaje genérico. No se guarda nada.
7. `POST /admin/inventory/connect` con `host` + `alias` (obligatorio: el host no se muestra a los usuarios) + `environment`, o
   con `server_id`; y `databases` (`["*"]` = todas, también las futuras). Con un build en curso, 409.
8. `replacing_inventory` (el mismo bloque que el PUT) audita `inventory_updated` con `servers` y `previous` (hosts) y
   `via: "connect"` antes de aplicar; prueba la credencial (`connector.identify`); si no entra, 400 y evento
   `inventory_updated_failed`, sin guardar. Si entra, guarda el inventario y lanza el build con la sesión.

Se eligió una ruta propia en lugar de que la web encadene `PUT /admin/inventory` y el build: el PUT reemplaza el inventario
entero con lo que la web tenga en memoria (pisa el cambio de otro administrador) y guarda aunque el servidor nuevo no conecte.

### Curación
- **Dudas**: `POST /curation/requests` exige que el `trace_id` sea una respuesta reciente del mismo usuario (últimas 500 en memoria).
  El dominio es el del candidato principal. Una duda repetida no se duplica. El webhook solo lleva dominio y enlace.
- **Respuesta**: con `asset`, el activo debe existir y ser de un dominio del responsable. Texto con PII → 422. Se audita
  `curation_answer`, se escribe la descripción (si viene), entra una confirmación de responsable al índice y se marca la duda.
- **Votos**: `/discover/feedback` solo acepta un activo mostrado en esa respuesta al mismo usuario. Se audita `feedback` antes de
  guardar. La plantilla es la pregunta sin literales; si aún parece llevar PII, el voto cuenta pero no se aprende. Regla de votos en
  `resolve_golden` (`src/converdata/curation.py:60`): un responsable decide al momento; usuarios, por confirmaciones netas (≥ 2 pesa
  en la confianza; ≤ 0 retira). El voto de un responsable recarga el índice antes de responder; el de un usuario, en segundo plano.
- **Descripciones**: `PUT /curation/description` escribe en todas las copias físicas como `human`.
- **Reglas**: solo las de `source` `steward:` se gestionan; las importadas con el catálogo no se pisan (409 genérico).
- **Diccionario**: CSV con `asset_key` o `database,schema,table[,column]`; entra como `data_dictionary`, no pisa `human`, idempotente.
  Lo fuera del dominio que el login no ve se informa como `unknown`, no como `forbidden`.
- Cada edición corre bajo `runtime.editing()`: un candado y el catálogo vigente; tras escribir, recarga (`_written`) y, si no puede,
  devuelve error aunque lo escrito ya sea firme.

## Contratos y datos
- `LoginRequest`: `login`, `password`, `auth` (`sql`|`windows`), `servers`, y para el primer arranque `host`, `alias`, `environment`,
  `trust_server_certificate`, `setup_token`.
- Respuesta del login: `session_id`, `token`, `expires_at`, `servers [{alias, ok}]`, `databases`, `user`, `warnings`.
- `DiscoverRequest`: `question` (2–2000), `history` (hasta 10 textos de 2000).
- `/discover` devuelve el `AnswerEnvelope` (`src/converdata/models/discovery.py:113`).
- Límites de entrada en los modelos Pydantic de `main.py:65-168` y `CONVERDATA_MAX_BODY_BYTES` (4 MB).

## Configuración
Variables leídas en `api/converdata_api/settings.py:72` (salvo indicación).

| Variable | Por defecto | Efecto |
|---|---|---|
| `CONVERDATA_ENV` | `dev` | `qa`/`prod` activan las comprobaciones de arranque y ocultan `/docs`; también fija el ambiente del gateway LLM |
| `CONVERDATA_DB` | — | Cadena ODBC de la BD `ConverData`; obligatoria en qa/prod; sin contraseña ni `TrustServerCertificate` |
| `CONVERDATA_DATA_ROOT` | `data/catalog` | Catálogo en archivos y `config/settings.yaml` |
| `CONVERDATA_INVENTORY` | `data/inventory.yaml` | Inventario sin BD |
| `CONVERDATA_AUDIT_DIR` | `data/audit` | Auditoría JSONL sin BD |
| `CONVERDATA_CURATION_DIR` | `data/curation` | Curación sin BD |
| `CONVERDATA_LOG_DIR` | `data/logs` | Logs JSON rotados |
| `CONVERDATA_EVENT_LOG` | `1` | Errores al Visor de eventos de Windows |
| `CONVERDATA_MODELS` | — | `config/models.yaml`; si no existe el archivo, modo determinista |
| `CONVERDATA_ADMINS` | — | Logins con `data_admin` (separados por coma) |
| `CONVERDATA_ADMINS_ONLY` | `0` | Solo la lista da `data_admin`; obligatorio en qa/prod |
| `CONVERDATA_SETUP_TOKEN` | — | Código de instalación del primer arranque |
| `CONVERDATA_ALLOW_WINDOWS_AUTH` | `0` | Login con la cuenta del proceso; prohibido en qa/prod |
| `CONVERDATA_COOKIE_SECURE` | `0` | Cookie `Secure` y HSTS; obligatorio en qa/prod |
| `CONVERDATA_CORS_ORIGINS` | `http://localhost:3000` | Orígenes CORS y de CSRF; en qa/prod solo `https://` explícitos |
| `CONVERDATA_PUBLIC_URL` | — | Enlace del aviso y origen permitido |
| `CONVERDATA_SESSION_TTL_S`, `CONVERDATA_SESSION_MAX_AGE_S` | 28800, 43200 | Inactividad y vida máxima; tope 8 h/12 h en qa/prod |
| `CONVERDATA_MAX_SESSIONS` | 5 | Sesiones por usuario |
| `CONVERDATA_VISIBILITY_TTL_S` | 900 | Relectura de permisos |
| `CONVERDATA_LOGIN_MAX_FAILURES`, `CONVERDATA_LOGIN_IP_MAX_FAILURES` | 5, 30 | Fallos antes del bloqueo; >0 en qa/prod |
| `CONVERDATA_LOGIN_WINDOW_S`, `CONVERDATA_LOGIN_LOCKOUT_S` | 600, 900 | Ventana y duración del bloqueo |
| `CONVERDATA_TRUST_PROXY` | `0` | Toma el origen del último valor de `X-Forwarded-For`. Solo detrás de un proxy propio; la web debe tener a la vez `TRUST_FORWARDED_FOR=1`, o no reenvía esa cabecera (DT-02) |
| `CONVERDATA_RATE_LIMIT` | 30 | Preguntas por minuto y usuario (herramientas MCP de detalle: ×4) |
| `CONVERDATA_TOKEN_LIMIT`, `CONVERDATA_TOKEN_LIMIT_MODE` | 0, `reject` | Tope diario de tokens; `deterministic` responde sin LLM |
| `CONVERDATA_MAX_BODY_BYTES` | 4194304 | Tope del cuerpo |
| `CONVERDATA_NOTIFY_WEBHOOK` | — | Aviso de dudas; `https` en qa/prod |
| `CONVERDATA_MCP`, `CONVERDATA_MCP_HOSTS`, `CONVERDATA_MCP_ORIGINS` | `1`, —, — | `/mcp`; hosts obligatorios en qa/prod (DNS rebinding) |
| `CONVERDATA_DEMO`, `CONVERDATA_DEMO_FIXTURE`, `CONVERDATA_DEMO_PRELOAD`, `CONVERDATA_DEMO_HISTORY` | `0`, fixtures, `1`, `1` | Modo demo; prohibido en qa/prod |
| `CONVERDATA_MANUAL` | `docs/manual-desarrollo.md` | Manual de `/admin/manual` |

`CONVERDATA_BUILDER_HOSTS` la usa la CLI del Builder (`src/converdata/cli.py:351`), no la API.

## Pruebas que lo cubren
- `api/tests/test_api.py`: primer arranque, descubrimiento, voto y auditoría, explorador, herencia de permisos, stream, escalamiento,
  reglas, tope de tokens, diccionario, responsables, manual.
- `api/tests/test_security.py`: sesión obligatoria, roles, bloqueo de logins, caducidad, cabeceras, CSRF, validaciones, arranque en
  qa/prod, barrido sin fugas, curación sin fugas.
- `api/tests/test_inventory_wizard.py`: sondeo y conexión del asistente (solo admin, auditado antes de conectar, sin guardar,
  bases sin acceso, BD propia excluida, certificado en producción, errores sin detalles, conectar y descubrir); una prueba
  contra SQL Server real.
- `api/tests/test_catalog_db.py`, `api/tests/test_audit_db.py`: con SQL Server real (`CONVERDATA_TEST_DB`).
- `api/tests/test_demo.py`, `api/tests/test_mcp.py`, `api/tests/test_marked_literals.py`.

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md).
- Un solo proceso: sesiones, límites, tope de tokens, respuestas mostradas (500) y visibilidad se pierden al reiniciar.
- `Session.groups` siempre es `[]`: no hay LDAP (HU-13). Los fragmentos con `allowed_groups` no los ve nadie.
- Los roles `data_admin` se fijan al iniciar sesión; quitar a alguien de `CONVERDATA_ADMINS` exige revocar sus sesiones.
- La cookie dura `min(ttl, vida máxima)` desde el login y no se renueva: en el navegador la sesión dura como mucho 8 h.
- `PUT /admin/inventory`, `/admin/inventory/probe` y `/admin/inventory/connect` prueban los servidores nuevos con la contraseña
  del administrador: un host mal escrito (o cualquiera que el administrador escriba) la recibe. No hay lista de hosts permitidos.
- Por `/mcp`, con el tope de tokens agotado, `discover` se rechaza aunque `CONVERDATA_TOKEN_LIMIT_MODE=deterministic`.
- El build del catálogo con `enrich` usa otro gateway sin gancho de uso: sus tokens no se cuentan.
- Ver los fallos encontrados en [seguridad y auditoría](seguridad-auditoria.md#fallos-encontrados-al-revisar-el-código).

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Añadir una ruta | `create_app` en `api/converdata_api/main.py`, con `current_session`, `steward_session` o `admin_session` |
| Cambiar quién es `steward` o `data_admin` | `domains_of`, `identity_trusted` y el bloque de roles del login en `main.py` |
| Cambiar cómo se calcula la visibilidad | `AgentRuntime.visible_ids` y `src/converdata/identity/visibility.py` |
| Cambiar el build | `AgentRuntime._run_build` y `src/converdata/application/catalog_refresh.py` |
| Cambiar la regla de votos | `resolve_golden` en `src/converdata/curation.py` |
| Añadir una variable de entorno | `ApiSettings` y `from_env` en `settings.py`; si es de seguridad, `production_violations` |
| Cambiar el aviso a responsables | `CurationDesk._notify` en `api/converdata_api/curation.py` |
| Añadir una herramienta MCP | `src/converdata/integration/mcp/server.py` y `DiscoveryTools` |

## Specs y contradicciones
Specs: [OP-03](../../specs/on-premise/OP-03-identidad.md), [OP-04](../../specs/on-premise/OP-04-interfaces.md),
[OP-05](../../specs/on-premise/OP-05-auditoria-observabilidad.md), [F12](../../specs/comun/F12-interfaces.md),
[F14](../../specs/comun/F14-identity.md), [F24](../../specs/comun/F24-knowledge-curation.md).

La spec contradice al código en:
- OP-03 y OP-04: el login recibe `{credentials: [{server, login, password}]}`. El código recibe un solo `login`/`password` y los
  prueba en los `servers` elegidos.
- F14 paso 1: la prueba de conexión usa `SUSER_SNAME(), ORIGINAL_LOGIN()`; el código usa `SUSER_SNAME()`, `IS_SRVROLEMEMBER` y
  `HAS_PERMS_BY_NAME`. F14 paso 3: visibilidad "en paralelo" y DENY por columna; el código es secuencial y no mira columnas.
- OP-04: `GET`/`DELETE /admin/sessions`; la revocación es `DELETE /admin/sessions/{user_id}`.
- OP-04: el límite de ritmo aplica también por `/mcp` (cierto), pero el modo `deterministic` del tope de tokens no aplica por `/mcp`.
- OP-05 §Auditoría y F11: las dudas escaladas "todavía en un archivo"; con BD viven en `curation.request` (lo prueba
  `test_una_duda_escalada_vive_en_la_bd_y_su_respuesta_entra_al_indice`).
- `search_catalog` (MCP) se describe como "léxica y semántica"; solo es léxica.
- `ApiSettings.demo_history` vale `False` en la clase y `True` por defecto desde el entorno.
