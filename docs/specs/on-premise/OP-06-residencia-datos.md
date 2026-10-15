# OP-06 — Residencia de datos: inventario de controles · on-premise

> Aplica en local el principio de [F17](../comun/F17-data-residency.md). Todo vive en la red corporativa; lo único que sale es el contexto enviado a Bedrock en cada llamada.

| Componente | Riesgo | Control |
|---|---|---|
| `catalog/` (git) y `./.chroma` | Valores de columnas | El YAML nunca lleva valores (F1); no existe índice de valores |
| Golden SQL | Pregunta y SQL con literales | Original en `audit.db`; en Chroma solo la plantilla anonimizada |
| `audit.db` | Pregunta, SQL, supuestos | Queda en el servidor on-prem; incluido en su respaldo y control de acceso |
| Historial de conversación | Respuestas con datos | Solo en la memoria del proceso; se pierde al cerrar la sesión o reiniciar |
| Chainlit | Persistencia de chats | Data layer desactivado |
| Logs locales | Prompts, SQL y filas | Lista blanca D5 y filtro de logger |
| Bedrock (única llamada externa) | Procesa D1/D2 | *Model invocation logging* desactivado; perfil IAM con solo `bedrock:InvokeModel*`. **Con datos reales, preferir la cuenta AWS del propio cliente** o un acuerdo de procesamiento de datos |
| NVIDIA NIM | Envía datos a un tercero | Solo con datos de prueba |
| `.env` | Login de metadatos y perfil AWS | Fuera del repositorio; permisos del sistema de archivos |

## Criterios de aceptación
1. La prueba del literal marcado de F17 encuentra el literal solo en `audit.db`.
2. `git grep` sobre `catalog/` no encuentra valores de datos de prueba.
