# OP-04 — Publicación de interfaces en IIS · on-premise

> Implementa en on-premise Microsoft: [F12](../comun/F12-interfaces.md). El contrato de la API, el chat y las herramientas MCP son los de F12.

| Interfaz | Implementación | Autenticación |
|---|---|---|
| Chat web | **Chainlit**, aplicación de IIS `ConverData-UI` (HttpPlatformHandler), publicada en `/` | Login de Chainlit con el login SQL (OP-03) |
| API REST | **FastAPI**, aplicación de IIS `ConverData-API` (HttpPlatformHandler, un solo proceso), publicada en `/api` (con `POST /login` y `POST /logout` adicionales) | `Authorization: Bearer <session_id>` |
| MCP | **FastMCP** montado en `/mcp` del servicio `ConverData-API`; los agentes lo llaman en proceso | `Bearer` obtenido con `/login` |
| Administración de ingesta (`/api/admin/*`) | Servicio de Windows `ConverData-Builder` (Catalog Builder + `converdata-discovery` como biblioteca) en `127.0.0.1:8100`, al que IIS reenvía con URL Rewrite + ARR solo desde las IPs de los SQL Server (SQL Agent) y de administración | Token de servicio |

## IIS
- **HttpPlatformHandler** lanza y supervisa los procesos Python (uvicorn) de UI y API, y reenvía las peticiones; es la opción recomendada por Microsoft frente a WFastCGI, que ya no se mantiene. `ConverData-Builder` es un servicio de Windows para que IIS no recicle una ingesta larga (modelo de procesos en [OP-07](OP-07-instalacion-operacion.md)).
- Grupos de aplicaciones con identidad gMSA, `idleTimeout = 0`, sin reciclaje periódico y, en `ConverData-API`, sin reciclaje superpuesto (SessionVault, OP-03).
- Sitio HTTPS en 443 con certificado de la **PKI corporativa**; HTTP redirige a HTTPS; HSTS activado.
- Soporte de **WebSockets** activado en IIS (Chainlit lo usa) y respuestas en *streaming* para `/ask/stream`.
- *Request Filtering*: tamaño máximo de petición y verbos permitidos; las preguntas viajan en el cuerpo, no en la URL.
- Los logs de IIS (W3C) no registran cuerpos ni la cabecera `Authorization`.
- **Firewall de Windows**: entrada solo en 443 desde las redes de los usuarios (y `/api/admin/*` restringido por IP en IIS); salida solo a los SQL Server (1433), al proxy corporativo (Bedrock y SharePoint Online si se usa), a AD (LDAP/Kerberos) y al servidor de archivos (SMB 445).

## API
- `POST /login`: `{credentials: [{server, login, password}]}` → `{session_id, expires_at, servers: [{alias, ok}], databases[]}` (F14, OP-03).
  Es la implementación on-premise de `/credentials` de F12.
- Rutas de descubrimiento de F12 (`/api/discover`, `/api/assets/{asset_key}`, `/api/discover/feedback`, `/api/curation/*`, `/api/metrics`), en el mismo servicio `ConverData-API`.
- Los roles `steward` y `data_admin` (F24) se asignan a grupos de AD (resueltos con `curation.user_directory`, OP-03) o, en su defecto, a logins SQL, en la tabla `curation.owners`.
- **Notificaciones a responsables** (F24): correo con **Database Mail** de la BD `ConverData` o webhook de Teams. El mensaje solo lleva el dominio y un enlace a `/curation`; la pregunta se lee dentro de la aplicación.
- Rate limit simple en FastAPI: 30 preguntas por minuto y sesión.
- **Tope diario de tokens por usuario** (configurable en `settings.yaml`, contado en memoria de la API y reiniciado a medianoche): al alcanzarlo, el DiscoverFlow responde en modo determinista (sin LLM) y avisa al usuario.
- CORS restringido al origen del sitio.

## Criterios de aceptación
1. Flujo E2E en Chainlit a través de `https://<servidor>/`: login → pregunta → tabla, gráfico y SQL → 👍.
2. `curl https://<servidor>/api/discover` (y `/api/ask` en la fase 1b) sin token devuelve 401.
3. Claude Code, con `.mcp.json` apuntando a `https://<servidor>/mcp`, usa `discover` (y `ask` en la fase 1b) y recibe un `AnswerEnvelope` con el `flow` correspondiente.
4. `/api/admin/*` responde 403 desde una IP fuera de la lista permitida (test de red).
5. Si un proceso Python cae, IIS lo reinicia automáticamente.
6. Flujo E2E de descubrimiento: pregunta de onboarding digital → tarjetas de candidatos con ambiente y servidor → "✔ Es este" → registro en `audit.audit_discovery_feedback`.
7. "Preguntar al responsable" envía la notificación sin el texto de la pregunta, y la respuesta del steward aparece como candidato principal en una pregunta equivalente.
8. El chat muestra los pasos del flow en streaming a través de IIS (WebSockets y respuestas en streaming activos).
9. Un usuario que alcanza el tope diario de tokens sigue recibiendo respuestas deterministas, con aviso, y sin llamadas a Bedrock (test con el contador de tokens).
10. Un reciclaje de `ConverData-API` durante una ingesta no interrumpe `ConverData-Builder` (OP-07 CA3).
