# OP-04 — Publicación de interfaces en IIS · on-premise

> Implementa en on-premise Microsoft: [F12](../comun/F12-interfaces.md). El contrato de la API, el chat y las herramientas MCP son los de F12.

| Interfaz | Implementación | Autenticación |
|---|---|---|
| Chat web | **Chainlit**, servicio de Windows `ConverData-UI`, publicado por IIS en `/` | Login de Chainlit con el login SQL (OP-03) |
| API REST | **FastAPI**, servicio `ConverData-API`, publicado por IIS en `/api` (con `POST /login` y `POST /logout` adicionales) | `Authorization: Bearer <session_id>` |
| MCP | **FastMCP** montado en `/mcp` del servicio `ConverData-API`; los agentes lo llaman en proceso | `Bearer` obtenido con `/login` |
| MCP de descubrimiento (F18) | Servicio `ConverData-Discovery`, **solo `localhost`**, no publicado por IIS | Token de servicio |

## IIS
- **HttpPlatformHandler** lanza y supervisa los procesos Python (uvicorn), y reenvía las peticiones; es la opción recomendada por Microsoft frente a WFastCGI, que ya no se mantiene.
- Sitio HTTPS en 443 con certificado de la **PKI corporativa**; HTTP redirige a HTTPS; HSTS activado.
- Soporte de **WebSockets** activado en IIS (Chainlit lo usa) y respuestas en *streaming* para `/ask/stream`.
- *Request Filtering*: tamaño máximo de petición y verbos permitidos; las preguntas viajan en el cuerpo, no en la URL.
- Los logs de IIS (W3C) no registran cuerpos ni la cabecera `Authorization`.
- **Firewall de Windows**: entrada solo en 443 desde las redes de los usuarios; salida solo a los SQL Server (1433), al proxy corporativo (Bedrock) y a AD.

## API
- `POST /login`: `{server, login, password}` → `{session_id, expires_at, databases[]}`.
- Rate limit simple en FastAPI: 30 preguntas por minuto y sesión.
- CORS restringido al origen del sitio.

## Criterios de aceptación
1. Flujo E2E en Chainlit a través de `https://<servidor>/`: login → pregunta → tabla, gráfico y SQL → 👍.
2. `curl https://<servidor>/api/ask` sin token devuelve 401.
3. Claude Code, con `.mcp.json` apuntando a `https://<servidor>/mcp`, usa `ask` y recibe un `AnswerEnvelope`.
4. `ConverData-Discovery` no responde desde otra máquina (test de red).
5. Si un proceso Python cae, IIS lo reinicia automáticamente.
