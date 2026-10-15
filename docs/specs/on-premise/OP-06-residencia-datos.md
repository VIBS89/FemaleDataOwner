# OP-06 — Residencia de datos: inventario de controles · on-premise

> Aplica en on-premise Microsoft el principio de [F17](../comun/F17-data-residency.md). Todo vive en la red corporativa; lo único que sale es el contexto enviado a Bedrock en cada llamada.

| Componente | Riesgo | Control |
|---|---|---|
| BD `ConverData`: esquemas `catalog`, `estate`, `semantic` | Valores de columnas | El catálogo nunca lleva valores (F1); no existe índice de valores; los sketches de F19 no se guardan |
| BD `ConverData`: esquemas `golden` y `audit` | Pregunta y SQL con literales | Quedan on-prem, con los permisos, el cifrado (TDE si se usa) y el respaldo del DBA; en los vectores solo plantillas anonimizadas |
| Historial temporal del catálogo | Versiones antiguas de descripciones | Solo metadatos (D3) |
| Historial de conversación | Respuestas con datos | Solo en la memoria del servicio; se pierde al cerrar la sesión o reiniciar |
| Chainlit | Persistencia de chats | Data layer desactivado |
| Logs de la aplicación, de IIS y Visor de eventos | Prompts, SQL y filas | Lista blanca D5 y filtro de logger; IIS sin cuerpos ni `Authorization` |
| Bedrock (única llamada externa) | Procesa D1/D2 | *Model invocation logging* desactivado; IAM Roles Anywhere con permiso solo `bedrock:InvokeModel*`. **Con datos reales, preferir la cuenta AWS del propio cliente** o un acuerdo de procesamiento de datos |
| NVIDIA NIM | Envía datos a un tercero | Solo con datos de prueba |
| Código Python libre (F20) | Ejecución arbitraria sobre datos | **No disponible en la v1** on-premise |
| Secretos de servicio | Login de metadatos, certificado de Bedrock | DPAPI con ámbito de la cuenta de servicio y almacén de certificados con clave no exportable |

## Criterios de aceptación
1. La prueba del literal marcado de F17 encuentra el literal solo en los esquemas `audit` y `golden` de la BD `ConverData`.
2. Ninguna tabla de `catalog`, `estate` o `semantic` contiene valores de datos de prueba.
