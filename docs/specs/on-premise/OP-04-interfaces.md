# OP-04 — Publicación de interfaces en IIS · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Implementa en on-premise Microsoft: [F12](../comun/F12-interfaces.md). El contrato de la API, la web y las herramientas MCP son los de F12.
> Controles de cada petición y su prueba: [calidad bancaria §3](../../calidad-bancaria.md).

| Interfaz | Implementación | Autenticación |
|---|---|---|
| Web | **Next.js** (`web/`), proceso Node lanzado por HttpPlatformHandler, publicado en `/`: chat con tarjetas de candidatos, Catálogo, Solicitudes, Curación, Métricas y Administración | Pantalla de login con el login SQL (OP-03); sesión en la cookie `cd_session` (`HttpOnly`) |
| API REST | **FastAPI**, `ConverData-API` (HttpPlatformHandler, un solo proceso uvicorn en `127.0.0.1`). **No se publica directamente**: el navegador la ve bajo `/api/` porque la web le reenvía `/api/*` (`web/src/app/api/[...path]/route.ts`) | Cookie de sesión (navegador) o `Authorization: Bearer <session_id>` |
| MCP | Servidor del SDK oficial de MCP (`MCPServer`) montado en `/mcp` de `ConverData-API`; IIS envía `/mcp` a la API | `Bearer` obtenido con `POST /api/auth/login` |
| Administración (inventario, responsables, build, auditoría, sesiones, métricas) | Rutas `/admin/*` de la misma `ConverData-API`, usadas desde la vista Administración de la web | Sesión con rol `data_admin` |

No hay un proceso de administración aparte ni token de servicio ni lista de IPs: el Builder es un comando (OP-02; PRD §13, decisión 12).

**Estado.** Construido: la web, la API con todas las rutas de §API, `/mcp` y el reenvío `/api/*`; se ejecutan con `docker compose` en
desarrollo. Pendiente: la publicación en IIS (`web.config`, HttpPlatformHandler, certificado, firewall), que es HU-37.

## IIS
- **HttpPlatformHandler** lanza y supervisa los dos procesos (Node para la web, uvicorn para la API) y les reenvía las peticiones; es la opción recomendada por Microsoft frente a WFastCGI, que ya no se mantiene. No hacen falta URL Rewrite ni otros módulos de proxy: cada aplicación de IIS atiende su ruta (`/` y `/mcp`) (modelo de procesos en [OP-07](OP-07-instalacion-operacion.md)).
- Grupos de aplicaciones con identidad gMSA, `idleTimeout = 0`, sin reciclaje periódico y, en `ConverData-API`, sin reciclaje superpuesto (SessionVault, OP-03).
- Sitio HTTPS en 443 con certificado de la **PKI corporativa**; HTTP redirige a HTTPS; HSTS activado.
- Respuestas en ***streaming* sin búfer** para `/api/discover/stream` (eventos SSE) y para `/mcp`. No se usan WebSockets.
- *Request Filtering*: tamaño máximo de petición (la API ya rechaza cuerpos de más de 4 MB) y verbos permitidos; las preguntas viajan en el cuerpo, no en la URL.
- Los logs de IIS (W3C) no registran cuerpos, cookies ni la cabecera `Authorization`.
- **Firewall de Windows**: entrada solo en 443 desde las redes de los usuarios; salida solo a los SQL Server (1433), al proxy corporativo (Bedrock, el webhook de Teams y SharePoint Online si se usa), a AD (LDAP/Kerberos) y al servidor de archivos (SMB 445).

## API
Rutas de `ConverData-API` (`api/converdata_api/main.py`; PRD §13, decisión 15). El navegador las llama con el prefijo `/api`.

| Grupo | Rutas |
|---|---|
| Sesión | `POST /auth/login` (alias `/login`): `{login, password, auth, servers[]}` (una sola credencial; `servers` lista los servidores donde se usa, y en el primer arranque `host`, `alias`, `environment`, `setup_token`; modelo `LoginRequest` en `api/converdata_api/main.py`) → sesión, servidores y roles (F14, OP-03). `POST /auth/logout` (alias `/logout`), `GET /auth/me` |
| Descubrimiento | `POST /discover`, `POST /discover/stream` (SSE con un evento `step` por nodo y `answer` al final), `POST /discover/feedback`, `GET /assets/{asset_key}` |
| Catálogo | `GET /catalog/databases`, `/catalog/objects`, `/catalog/object`, filtradas por la visibilidad del usuario |
| Curación (F24) | `POST /curation/requests` (escalar una duda, cualquier usuario); `GET /curation/requests`, `POST /curation/requests/{id}/answer`, `GET /curation/review`, `PUT /curation/description`, `GET /curation/history?asset_key=` (versiones de la descripción de un activo con autor y fecha, solo para responsables de su dominio que además pueden ver el activo con su login; sale del historial temporal de la BD y sin ella responde `available: false`), `POST /curation/dictionary`, `GET`/`PUT /curation/rules`, `DELETE /curation/rules/{id}` (rol `steward` o `data_admin`) |
| Del usuario | `GET /me/requests`, `GET /me/history` |
| Administración (`data_admin`) | `GET`/`PUT /admin/inventory`, `GET`/`PUT /admin/stewards` (responsables de curación por login y dominio), `POST`/`GET /admin/catalog/build`, `GET /admin/audit`, `GET /admin/audit/verify`, `GET /admin/sessions`, `DELETE /admin/sessions/{user_id}`, `GET /admin/metrics`, `GET /admin/manual` (manual de desarrollo; cada lectura se audita como `manual_read`) |
| Estado | `GET /health` y `GET /setup/status` (públicas), `GET /health/metrics` |

- **Toda ruta no pública exige sesión**; `/admin/*` y `/curation/*` exigen rol. Las públicas son `/health`, `/setup/status` y el login.
- Los roles `steward` y `data_admin` (F24): `data_admin` sale de la lista `CONVERDATA_ADMINS`; `steward`, de la lista de responsables de curación por login y dominio que mantiene el administrador desde la pestaña Responsables de Administración (`PUT /admin/stewards`): se guarda en `curation.steward` (tabla temporal), el cambio se audita como `stewards_updated` antes de aplicarse y surte efecto en segundos (la API cachea la lista 5 s y la refresca al guardar). Sin BD (desarrollo) la lista vive en `stewards.yaml`. Un rol que se da por nombre de login solo cuenta si la sesión validó ese login en un servidor con `environment: produccion`, cuando el inventario tiene alguno (`identity_trusted`): quien administra un servidor de desarrollo o de QA puede crear allí un login con cualquier nombre. Es una política por confirmar con el banco (PRD §13, pregunta abierta 9). `curation.owners` es otra cosa: los responsables de negocio y técnico que se muestran en cada ficha. La asignación por grupos de AD (con un directorio `curation.user_directory`, OP-03) es HU-13.
- **Alcance de la curación** (`require_curable`, `manages_rule`): ser responsable no da lectura. Fuera de sus dominios un responsable recibe 403 solo si ya puede ver el activo con su login, y 404 si no (igual que si no existiera, F14); el historial exige además visibilidad; la bandeja de solicitudes solo muestra en `shown` activos de sus dominios; `GET /me/requests` no entrega la nota libre de la respuesta cuando el usuario necesita pedir acceso (`needs_access`); en el diccionario, `forbidden` solo lista lo que el responsable ve y el resto va a `unknown`; una regla cuyos activos ya no existen solo la gestiona quien cura `rule.domain`, y usar el id de una regla ajena o importada da un 409 genérico. La cola de revisión y la edición dentro de sus dominios siguen sin filtrar por visibilidad (PRD §13, pregunta abierta 7).
- **Cambios fallidos**: cada cambio se audita antes de aplicarse y, si falla, queda además `<evento>_failed` con el tipo del error (F11).
- **Notificaciones a responsables** (F24): **webhook de Teams** (`CONVERDATA_NOTIFY_WEBHOOK`, solo `https`). El mensaje solo lleva el dominio y un enlace a la vista Curación; la pregunta se lee dentro de la aplicación.
- Límite de ritmo: 30 preguntas por minuto **y usuario** (no por sesión), también por `/mcp`.
- **Tope diario de tokens por usuario** (`CONVERDATA_TOKEN_LIMIT`, contado en memoria de la API y reiniciado a medianoche UTC): al alcanzarlo, con `CONVERDATA_TOKEN_LIMIT_MODE=deterministic` el DiscoverFlow responde en modo determinista (sin LLM) y avisa al usuario; el valor por defecto rechaza la pregunta con 429.
- Cabeceras de seguridad, `Cache-Control: no-store`, verificación de `Origin` en los cambios de estado con cookie y CORS restringido al origen del sitio. La web envía además sus propias cabeceras de seguridad (CSP con `frame-ancestors 'none'`, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y HSTS en producción; `web/next.config.ts`), y su proxy reenvía `Origin` y `X-Forwarded-Host` y solo expone las rutas que usa la web (`auth`, `login`, `setup`, `me`, `discover`, `catalog`, `assets`, `curation`, `admin`): `/api/mcp` y `/api/health/metrics` no salen por ahí.
- **Detrás de IIS**: se define `TRUST_FORWARDED_FOR=1` en la web y `CONVERDATA_TRUST_PROXY=1` en la API, para que el bloqueo de logins por origen cuente la dirección de cada cliente y no la del proxy; IIS debe añadir esa dirección al final de `X-Forwarded-For`. `CONVERDATA_CORS_ORIGINS` lleva el origen público del sitio (`https://…`): si IIS cambia `Host`, sin él la API rechaza con 403 los cambios de estado. Se prueba en HU-37 (DT-02).
- Con `CONVERDATA_ENV=qa` o `prod`, `/docs` y `/openapi.json` no se publican y la API no arranca con ajustes inseguros ([calidad bancaria §4](../../calidad-bancaria.md)).

## Criterios de aceptación
1. Flujo E2E en la web a través de `https://<servidor>/`: login → pregunta → tarjetas de candidatos → "✔ Es este" (en la fase 1b: tabla, gráfico y SQL → 👍).
2. `curl https://<servidor>/api/discover` (y `/api/ask` en la fase 1b) sin token devuelve 401.
3. Claude Code, con `.mcp.json` apuntando a `https://<servidor>/mcp`, usa `discover` (y `ask` en la fase 1b) y recibe un `AnswerEnvelope` con el `flow` correspondiente.
4. `/api/admin/*` responde 403 a una sesión sin rol `data_admin` y 401 sin sesión, y el intento queda auditado (test).
5. Si un proceso de ConverData (web o API) cae, IIS lo reinicia automáticamente.
6. Flujo E2E de descubrimiento: pregunta de onboarding digital → tarjetas de candidatos con ambiente y servidor → "✔ Es este" → registro en `audit.audit_discovery_feedback`.
7. "Preguntar al responsable" envía la notificación sin el texto de la pregunta, y la respuesta del steward aparece como candidato principal en una pregunta equivalente.
8. El chat muestra los pasos del flow en streaming a través de IIS (SSE de `/api/discover/stream` sin búfer).
9. Un usuario que alcanza el tope diario de tokens sigue recibiendo respuestas deterministas, con aviso, y sin llamadas a Bedrock (test con el contador de tokens y `CONVERDATA_TOKEN_LIMIT_MODE=deterministic`).
10. Un build lanzado por la tarea programada termina aunque IIS recicle la web o la API durante ese tiempo (OP-07 CA3).

Estado de los criterios (2026-11-17): 2, 4 y 9 tienen tests en `api/tests/`; 6 y 7 se prueban contra la BD `ConverData` (el voto en
`audit.audit_discovery_feedback`, la duda escalada en `curation.request`; `api/tests/test_audit_db.py`, `api/tests/test_catalog_db.py`); 1, 3, 5, 8 y 10 a través de IIS dependen de HU-37 (hoy se comprueban con `docker compose`).
