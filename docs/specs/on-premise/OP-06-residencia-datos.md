# OP-06 — Residencia de datos: inventario de controles · on-premise

> Aplica en on-premise Microsoft el principio de [F17](../comun/F17-data-residency.md). Todo vive en la red corporativa; lo único que sale es el contexto enviado a Bedrock en cada llamada.

| Componente | Riesgo | Control |
|---|---|---|
| BD `ConverData`: esquemas `catalog`, `estate`, `semantic` | Valores de columnas | El catálogo nunca lleva valores (F1); no existe índice de valores; los sketches de F19 no se guardan |
| BD `ConverData`: esquemas `golden` y `audit` | Pregunta y SQL con literales | Quedan on-prem, con los permisos, el cifrado (TDE si se usa) y el respaldo del DBA; en los vectores solo plantillas anonimizadas |
| Historial temporal del catálogo | Versiones antiguas de descripciones | Solo metadatos (D3) |
| BD `ConverData`: esquema `knowledge` | Datos de clientes dentro de documentos y diccionarios | Redacción de PII antes de indexar; fragmentos con más del 20 % de PII se descartan; el original no se copia (F23) |
| BD `ConverData`: esquema `curation` | Preguntas escaladas (D2) | On-prem con los permisos del DBA; notificaciones sin el texto de la pregunta |
| Ediciones de curación (F24) | Descripciones o reglas con datos pegados por un steward | Pasan por el mismo detector de PII de F23 antes de escribirse; si detecta valores, la edición se rechaza con un aviso |
| Respaldos de la BD `ConverData` | Copias de `audit`, `golden` y `curation` (D2) | `BACKUP ... WITH ENCRYPTION`, acceso solo del DBA y retención no mayor que la de la auditoría (OP-07) |
| Historial de conversación | Respuestas con datos | Solo en la memoria del servicio; se pierde al cerrar la sesión o reiniciar |
| Chainlit | Persistencia de chats y archivos | Data layer desactivado; subida de archivos desactivada |
| Memoria de los procesos (SessionVault, historial, resultados) | Volcados de memoria y archivo de paginación | Sin volcados de WER de los procesos de ConverData; volcado del sistema limitado al del kernel; `SeDebugPrivilege` solo para administradores (OP-03, OP-07). Opcional: `ClearPageFileAtShutdown` |
| Disco del servidor de aplicación | Archivos temporales con datos | Sin escritura a disco de resultados ni documentos: DataFrames, documentos de F23 y descargas solo en memoria o en streaming; `TEMP` de las gMSA incluido en la prueba del literal marcado |
| Logs de la aplicación, de IIS y Visor de eventos | Prompts, SQL y filas | Lista blanca D5 y filtro de logger; IIS sin cuerpos ni `Authorization` |
| Bedrock (única llamada externa) | Procesa D1/D2 | *Model invocation logging* desactivado; IAM Roles Anywhere con permiso solo `bedrock:InvokeModel*` y `bedrock:ApplyGuardrail`. **Con datos reales, preferir la cuenta AWS del propio cliente** o un acuerdo de procesamiento de datos |
| Bedrock Guardrails | Evaluación de la pregunta y la respuesta | Procesamiento sin almacenamiento; logging del guardrail desactivado; el permiso IAM mínimo solo se amplía con `bedrock:ApplyGuardrail` |
| NVIDIA NIM | Envía datos a un tercero | Solo con datos de prueba |
| Código Python libre (F20) | Ejecución arbitraria sobre datos | **No disponible en la v1** on-premise |
| Secretos de servicio | Login de metadatos, sal de MinHash, certificado de Bedrock | DPAPI con ámbito de la cuenta de servicio y almacén de certificados con clave no exportable |

## Criterios de aceptación
1. La prueba del literal marcado de F17 encuentra el literal solo en los esquemas `audit`, `golden` y `curation` de la BD `ConverData`.
2. Ninguna tabla de `catalog`, `estate` o `semantic` contiene valores de datos de prueba.
3. Ningún fragmento de `knowledge` contiene los DUI ni números de cuenta de prueba sembrados en los documentos.
4. La prueba del literal marcado no encuentra el literal en el disco del servidor de aplicación (logs, `TEMP` de las gMSA, carpetas de IIS) ni en volcados de memoria, porque no se generan (OP-03 CA6).
5. Una edición de curación con un DUI de prueba se rechaza y el literal no llega a ninguna tabla.
