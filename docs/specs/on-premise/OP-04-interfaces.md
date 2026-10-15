# OP-04 — Publicación de interfaces · on-premise

> Implementa en local: [F12](../comun/F12-interfaces.md). El contrato de la API, el chat y las herramientas MCP son los de F12.

| Interfaz | Implementación | Autenticación |
|---|---|---|
| Chat web | **Chainlit** en el contenedor `converdata-app` | Login de Chainlit con el login SQL (OP-03) |
| API REST | **FastAPI** en el mismo proceso, con `POST /login` y `POST /logout` adicionales | `Authorization: Bearer <session_id>` |
| MCP | **FastMCP** montado en `/mcp` del mismo proceso; los agentes lo llaman en proceso | Header `X-Session-Id` o `Bearer` obtenido con `/login` |

- `POST /login`: `{server, login, password}` → `{session_id, expires_at, databases[]}`.
- Acceso solo desde la red interna (o `localhost`); TLS con el certificado corporativo si se expone a otros equipos.
- Rate limit simple en FastAPI: 30 preguntas por minuto y sesión.
- CORS restringido al origen de Chainlit.

## Criterios de aceptación
1. Flujo E2E en Chainlit: login → pregunta → tabla, gráfico y SQL → 👍.
2. `curl /ask` sin token devuelve 401.
3. Claude Code, con `.mcp.json` apuntando a `http://<servidor>/mcp`, usa `ask` y recibe un `AnswerEnvelope`.
