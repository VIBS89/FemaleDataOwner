# F12 — Interfaces: API, chat y MCP · común

> Publicación y autenticación por entorno: **cloud native** → ALB + Cognito + AgentCore Gateway ([CN-04](../cloud-native/CN-04-interfaces.md)) · **on-premise** → Chainlit + FastAPI + `/mcp` local ([OP-04](../on-premise/OP-04-interfaces.md))

## Contrato de la API (igual en ambos entornos)
| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| POST | `/ask` | `{question, conversation_id?, database?, confirm_procedure?}` → `AnswerEnvelope` |
| POST | `/ask/stream` | Lo mismo por SSE, con eventos `step` (progreso de cada nodo) y `answer` |
| POST | `/feedback` | `{trace_id, rating, comment?}` |
| GET | `/catalog/search?q=` | Búsqueda en el catálogo filtrada por la visibilidad del usuario |
| GET | `/audit` | Solo administradores (F11) |
| GET | `/health` | Estado de Bedrock, memoria semántica, sql-to-mcp y SQL Server |

Las preguntas viajan siempre en el cuerpo, nunca en la URL, para que no queden en logs de acceso.

## Chat web (Chainlit)
- Cada respuesta muestra:
  - texto;
  - tabla interactiva (las primeras 200 filas, descarga CSV/XLSX completa generada en streaming al navegador);
  - gráfico Plotly;
  - "🔎 Cómo lo obtuve" plegable con SQL o SP, tablas, supuestos, validaciones y confidence;
  - botones 👍/👎.
- Los pasos del flow se muestran en vivo como `cl.Step`.
- Las aclaraciones se muestran como botones (`cl.Action`) con las opciones de F3.
- Los SPs con `side_effects` piden confirmación explícita.
- **Data layer de Chainlit desactivado**: no se persisten chats (F17).

## Herramientas MCP de `converdata-mcp`
`ask`, `search_catalog`, `describe_table`, `find_join_path`, `lookup_values`, `validate_sql`, `run_select`, `list_procedures`, `exec_procedure`.
- Para un cliente externo (Claude Desktop o Claude Code), basta normalmente con `ask`.
- `run_select` siempre llama primero a `validate_sql`; no hay forma de ejecutar sin validar.
- La identidad del usuario llega por el contexto autenticado de la petición, **nunca como argumento** que el LLM pueda modificar (F14).

## Criterios de aceptación
1. Flujo E2E en el chat: pregunta → tabla, gráfico y SQL → 👍 → el registro aparece en auditoría y en golden.
2. `/ask` sin autenticación devuelve 401.
3. Desde Claude Code, la herramienta `ask` devuelve un `AnswerEnvelope`.
