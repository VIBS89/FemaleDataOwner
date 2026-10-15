# F12 — Interfaces: API, chat y MCP · común

> Publicación y autenticación por entorno: **cloud native** → ALB + Cognito + AgentCore Gateway ([CN-04](../cloud-native/CN-04-interfaces.md)) · **on-premise** → Chainlit + FastAPI + `/mcp` local ([OP-04](../on-premise/OP-04-interfaces.md))

## Contrato de la API (igual en ambos entornos)
| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| POST | `/ask` | `{question, conversation_id?, database?, confirm_procedure?}` → `AnswerEnvelope` |
| POST | `/ask/stream` | Lo mismo por SSE, con eventos `step` (progreso de cada nodo) y `answer` |
| POST | `/feedback` | `{trace_id, rating, comment?}` |
| POST | `/discover` | `{question, conversation_id?, environment?}` → `AnswerEnvelope` con `flow=discover` (F22). `/ask` también enruta a descubrimiento según F3 |
| GET | `/assets/{asset_key}` | Ficha del activo: ubicaciones por ambiente, descripción y fuente, reglas, responsables, relaciones, linaje, documentos vinculados |
| POST | `/discover/feedback` | `{trace_id, asset_key, verdict, correct_asset_key?}` (F24) |
| POST | `/curation/requests` · GET/PATCH `/curation/*` | Escalamiento a responsables y vista de curación; solo `steward`/`data_admin` para responder (F24) |
| GET | `/metrics` | Métricas de F25 (solo `data_admin`) |
| GET | `/catalog/search?q=` | Búsqueda en el catálogo filtrada por la visibilidad del usuario |
| GET | `/audit` | Solo administradores (F11) |
| GET | `/health` | Estado de Bedrock, memoria semántica, `converdata-discovery` y SQL Server |

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

### Respuestas de descubrimiento (F22)
Cada candidato se muestra como una tarjeta con el formato de la propuesta:
```
1. ClientCode                                      Confianza: 92 %
   Base de datos: VBank_ING · Tabla: dbo.Users · Ambiente: Producción · Servidor: SQL Producción Canales
   Descripción: Código que identifica a los clientes digitales registrados.   [revisada por Banca Digital]
   Reglas: BR-ONB-004 Se asigna al completar la verificación de identidad.
   Relacionadas: UserDevices (FK UserId) · DWH.dim.Cliente (ETL ONB_CargaUsuarios)
   [✔ Es este] [✖ No es] [Ver ficha] [Ver relacionadas]
Alternativas: LegalClientId (71 %) · UserId (64 %)
```
- La fuente de la descripción siempre es visible; las `generated` se marcan "sugerida por IA, sin revisar".
- Solo se muestran activos, ubicaciones y relaciones que el usuario puede leer (F14); lo que no puede ver no aparece en la tarjeta.
- Con `knowledge_gap`, se muestra el botón "Preguntar al responsable" (F24).
- Vista **Curación** (solo `steward`/`data_admin`) y vista **Métricas** (solo `data_admin`).

## Herramientas MCP de `converdata-mcp`
`ask`, `search_catalog`, `where_is`, `estate_overview`, `describe_table`, `find_join_path`, `lookup_values`, `validate_sql`, `run_select`, `list_procedures`, `exec_procedure`, `list_metrics`, `analyze`.
- `where_is`, `estate_overview` y `find_join_path` entre BDs vienen de F19; `list_metrics` de F21; `analyze` ejecuta los modos de F20.
- Descubrimiento (F22–F24): `discover`, `get_asset`, `get_related`, `get_lineage`, `list_business_rules`, `find_alternatives`.
  `discover` devuelve el `AnswerEnvelope` con `flow=discover` y usa `where_is` (F19) para las entidades entre BDs.
- Para un cliente externo (Claude Desktop o Claude Code), basta normalmente con `ask`.
- `run_select` siempre llama primero a `validate_sql`; no hay forma de ejecutar sin validar.
- La identidad del usuario llega por el contexto autenticado de la petición, **nunca como argumento** que el LLM pueda modificar (F14).

## Criterios de aceptación
1. Flujo E2E en el chat: pregunta → tabla, gráfico y SQL → 👍 → el registro aparece en auditoría y en golden.
2. `/ask` sin autenticación devuelve 401.
3. Desde Claude Code, la herramienta `ask` devuelve un `AnswerEnvelope`.
4. Flujo E2E de descubrimiento: pregunta de la propuesta (onboarding digital) → tarjetas de candidatos → "✔ Es este" → registro en
   `audit_discovery_feedback` y aumento del contador de `golden_discovery`.
