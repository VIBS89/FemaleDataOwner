# CN-06 — Residencia de datos: inventario de controles · cloud native

> Aplica en AWS el principio de [F17](../comun/F17-data-residency.md): AWS procesa y muestra; no guarda.

| Componente | Riesgo | Control |
|---|---|---|
| Catálogo en S3 y OpenSearch | Valores de columnas | El YAML nunca lleva valores (F1); el indexador rechaza los que los tengan; no existe índice de valores |
| Golden SQL | Pregunta y SQL con literales | Original en `ConverData_Audit` on-prem; en OpenSearch solo la plantilla anonimizada |
| Documentos y diccionarios (F23) | Datos de clientes en ejemplos o capturas | Se leen por la VPN (SMB) o por Graph con egress filtrado (CN-01); redacción de PII en memoria en la tarea ECS antes de escribir; a S3 y OpenSearch solo llegan fragmentos redactados; el original no se copia ni pasa a disco |
| Ediciones de curación en S3 (F24) | Descripciones o reglas con datos pegados por un steward | Pasan por el mismo detector de PII antes de escribirse en `_curation/`; el indexador rechaza valores |
| Golden discovery y curación (F24) | Pregunta de descubrimiento (D2) | Original y solicitudes escaladas en `ConverData_Audit` on-prem; en OpenSearch solo la plantilla; notificaciones sin texto de la pregunta |
| Auditoría | Pregunta, SQL, supuestos | `ConverData_Audit` en SQL Server on-prem (CN-05) |
| Historial de conversación | Respuestas con datos | Solo en la memoria de la sesión de AgentCore Runtime (microVM); **no se usa AgentCore Memory** |
| Chainlit en ECS | Persistencia de chats | Data layer desactivado; descargas en streaming, sin pasar por S3 |
| CloudWatch Logs / X-Ray | Prompts, SQL y filas | Lista blanca D5 y filtro de logger; tests que inspeccionan la salida |
| Bedrock | Logs de invocación | *Model invocation logging* desactivado, verificado por AWS Config |
| Bedrock Guardrails | Evaluación de texto | Procesamiento sin almacenamiento; logging del guardrail desactivado |
| NVIDIA NIM (fallback) | Envía datos a un tercero | Desactivado en prod; solo con acuerdo de procesamiento de datos o NIM autoalojado en la VPC |
| ALB / WAF logs | URLs y cabeceras | Preguntas en el cuerpo, nunca en la URL; los access logs no incluyen cuerpos |
| Disco efímero de AgentCore Runtime | Resultados | Sin escritura a disco; DataFrames solo en memoria |
| AgentCore Code Interpreter (F20) | Código y DataFrames | Sesión aislada, sin persistencia; se cierra al terminar el análisis |
| Sketches de descubrimiento (F19) | Huellas de valores | Calculados en memoria en la tarea ECS con hashes salados; nunca se escriben |
| Secrets Manager | Credenciales SQL | No son datos de clientes; cifradas con CMK y acceso restringido (CN-03) |

## Criterios de aceptación
1. La prueba del literal marcado de F17 devuelve 0 coincidencias en S3, OpenSearch, CloudWatch Logs, X-Ray y AgentCore, incluidos literales sembrados en documentos de prueba (F23).
2. Una AWS Config rule marca como no conforme cualquier cuenta con *model invocation logging* activado.
