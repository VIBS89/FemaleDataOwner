# CN-04 — Publicación de interfaces · cloud native

> Implementa en AWS: [F12](../comun/F12-interfaces.md). El contrato de la API, el chat y las herramientas MCP son los de F12.

| Interfaz | Servicio | Autenticación |
|---|---|---|
| Chat web (Chainlit) y API REST (FastAPI BFF) | **ECS Fargate** detrás de **ALB**, con **AWS WAF** (rate limit, reglas gestionadas) | ALB `authenticate-cognito`; el BFF reenvía el JWT del usuario a `InvokeAgentRuntime` |
| DiscoverFlow y AskFlow | **AgentCore Runtime** (`runtimeSessionId` = `conversation_id`) | Inbound JWT authorizer (Cognito) |
| Descubrimiento, curación y métricas (`/discover`, `/assets`, `/curation`, `/metrics`) | El mismo BFF; `/discover` invoca el DiscoverFlow en AgentCore Runtime | Cognito; los roles `steward` y `data_admin` salen de grupos del IdP (F24) |
| MCP para clientes externos | **AgentCore Gateway** (endpoint MCP) con target `converdata-mcp` (MCP server en AgentCore Runtime) | OAuth 2.0 de Cognito; la identidad del usuario se propaga al target |

- El streaming de pasos (`/ask/stream`) usa la respuesta en streaming de `InvokeAgentRuntime`, que el BFF reenvía como SSE.
- Rate limit en WAF y un límite de tokens por usuario y día en el BFF.
- Los access logs del ALB no incluyen cuerpos de petición.
- **Notificaciones a responsables** (F24): webhook de Teams o correo corporativo; el mensaje solo lleva el dominio y un enlace a `/curation`, nunca el texto de la pregunta (que vive en `ConverData_Audit` on-prem).

## Criterios de aceptación
1. Un usuario sin sesión de Cognito es redirigido al IdP; sin JWT válido, `/ask` devuelve 401.
2. Un cliente MCP externo autenticado con Cognito invoca `ask` a través de AgentCore Gateway.
3. El streaming muestra los pasos del flow en el chat.
4. Un cliente MCP externo invoca `discover` a través de AgentCore Gateway y recibe un `AnswerEnvelope` con `flow=discover`.
