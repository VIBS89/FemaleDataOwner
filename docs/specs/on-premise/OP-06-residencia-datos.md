# OP-06 — Residencia de datos: inventario de controles · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Aplica en on-premise Microsoft el principio de [F17](../comun/F17-data-residency.md). Todo vive en la red corporativa; lo único que sale es el contexto enviado a Bedrock en cada llamada.
> Qué controles están implementados, con qué prueba, y cuáles faltan: [calidad bancaria §3 y §5](../../calidad-bancaria.md).

| Componente | Riesgo | Control |
|---|---|---|
| BD `ConverData`: esquema `catalog` (y `semantic` en la fase 1b) | Valores de columnas | El catálogo nunca lleva valores (F1); no existe índice de valores; los sketches de F19 no se guardan |
| Copia de trabajo del catálogo en el disco del servidor de aplicación (`CONVERDATA_DATA_ROOT`) | Es una copia de `catalog` y `knowledge`, incluidas las preguntas confirmadas (D2) | Se reconstruye desde la BD y se puede borrar con la API parada; ACL solo para la gMSA de la API y los administradores. Deja de hacer falta cuando la curación escriba filas en la BD (plan, bloque C2) |
| Archivos de curación (`CONVERDATA_CURATION_DIR`): responsables, solicitudes escaladas y votos | Las solicitudes contienen la pregunta (D2) | Misma ACL; pendientes de pasar al esquema `curation` (migración `002`) |
| Sin `CONVERDATA_DB` (solo desarrollo): catálogo y auditoría en archivos | Lo mismo que los esquemas equivalentes | No se admite en qa ni en prod: la API no arranca sin `CONVERDATA_DB` |
| Índice léxico en memoria de `ConverData-API` | Copia del catálogo y del conocimiento en RAM | Solo metadatos y fragmentos ya redactados (D3) y plantillas (D4); filtrado por `visible_ids` antes del ranking; no se escribe a disco |
| BD `ConverData`: esquemas `golden` y `audit` | Pregunta y SQL con literales | Quedan on-prem, con los permisos, el cifrado (TDE si se usa) y el respaldo del DBA; en el índice de búsqueda, las preguntas confirmadas normalizadas (aún sin anonimizar, OP-02) |
| Historial temporal del catálogo | Versiones antiguas de descripciones | Solo metadatos (D3) |
| BD `ConverData`: esquema `knowledge` | Datos de clientes dentro de documentos y diccionarios | Redacción de PII antes de indexar; fragmentos con más del 20 % de PII se descartan; el original no se copia (F23). Pendiente con la ingesta de documentos (HU-26) |
| BD `ConverData`: esquema `curation` | Preguntas escaladas (D2) | On-prem con los permisos del DBA; notificaciones sin el texto de la pregunta |
| Ediciones de curación (F24) | Descripciones o reglas con datos pegados por un steward | Pasan por un detector de PII antes de escribirse; si detecta valores, la edición se rechaza con un aviso. Hoy es un detector de cinco patrones (DUI, NIT, correo, teléfono, tarjeta; `api/converdata_api/pii.py`); el de F23 (Presidio) llega con HU-26 |
| Respaldos de la BD `ConverData` | Copias de `audit`, `golden` y `curation` (D2) | `BACKUP ... WITH ENCRYPTION`, acceso solo del DBA y retención no mayor que la de la auditoría (OP-07) |
| Historial de conversación | Respuestas con datos | Solo en la memoria del proceso; se pierde al cerrar la sesión o reiniciar. El historial de preguntas del usuario (`/me/history`) se lee de la auditoría |
| Web (Next.js) | Persistencia de chats, credenciales y archivos | No guarda credenciales ni conversaciones: solo reenvía `/api/*`; la sesión va en una cookie `HttpOnly`; la única subida de archivos es el diccionario CSV de Curación (rol `steward`, tope de 4 MB, pasa por el detector de PII) |
| Memoria de los procesos (SessionVault, historial, resultados) | Volcados de memoria y archivo de paginación | Sin volcados de WER de los procesos de ConverData; volcado del sistema limitado al del kernel; `SeDebugPrivilege` solo para administradores (OP-03, OP-07). Opcional: `ClearPageFileAtShutdown` |
| Disco del servidor de aplicación | Archivos temporales con datos | Sin escritura a disco de resultados ni documentos: DataFrames, documentos de F23 y descargas solo en memoria o en streaming (en la fase 1a no hay resultados de consultas); `TEMP` de las gMSA incluido en la prueba del literal marcado |
| Logs de la aplicación, de IIS y Visor de eventos | Prompts, SQL y filas | Lista blanca D5 y filtro de logger; IIS sin cuerpos, cookies ni `Authorization` |
| Bedrock (única llamada externa) | Procesa D1/D2 | *Model invocation logging* desactivado; IAM Roles Anywhere con permiso solo `bedrock:InvokeModel*` sobre el único modelo del piloto (sin embeddings). **Con datos reales, preferir la cuenta AWS del propio cliente** o un acuerdo de procesamiento de datos. Pendiente de probar de punta a punta (HU-35) |
| Guardas sobre el LLM | Inyección de prompt, texto generado con enlaces, HTML o correos, objetos inventados | Las del código: contenido del catálogo delimitado en los prompts, texto inseguro reemplazado por el determinista, solo se devuelven objetos de `visible_ids` (suites `inyeccion` y `guardas` de `converdata eval gate`). Bedrock Guardrails no es requisito de la fase 1a: es una decisión pendiente de Seguridad de la Información (PRD §13, decisión 13); si se adopta, sin almacenamiento ni logging y añadiendo solo `bedrock:ApplyGuardrail` |
| Webhook de Teams (notificaciones de F24) | Texto de la pregunta escalada | El mensaje solo lleva el dominio y un enlace a Curación; solo `https` |
| NVIDIA NIM y Ollama | NIM envía datos a un tercero; Ollama es solo local | Solo con datos de prueba: con `data_mode: real` el gateway se niega a arrancar si un rol apunta a un proveedor de prueba, y Ollama solo se admite con `environment: local` |
| Código Python libre (F20) | Ejecución arbitraria sobre datos | **No disponible en la v1** on-premise |
| Secretos de servicio | Login de metadatos, código de instalación, sal de MinHash, certificado de Bedrock | DPAPI con ámbito de la cuenta de servicio y almacén de certificados con clave no exportable. Pendiente (HU-37); en desarrollo llegan por variables de entorno |

## Criterios de aceptación
1. La prueba del literal marcado de F17 encuentra el literal solo en los esquemas `audit`, `golden` y `curation` de la BD `ConverData` (o en sus archivos equivalentes mientras no se migren).
2. Ninguna tabla de `catalog` (ni de `semantic` en la fase 1b) contiene valores de datos de prueba.
3. Ningún fragmento de `knowledge` contiene los DUI ni números de cuenta de prueba sembrados en los documentos.
4. La prueba del literal marcado no encuentra el literal en el disco del servidor de aplicación (logs, `TEMP` de las gMSA, carpetas de IIS) ni en volcados de memoria, porque no se generan (OP-03 CA6).
5. Una edición de curación con un DUI de prueba se rechaza y el literal no llega a ninguna tabla.
6. Con `data_mode: real`, la API no arranca si `config/models.yaml` apunta algún rol a NIM alojado u Ollama (test del gateway).

Estado de los criterios: 5 y 6 se cumplen hoy (`api/tests/test_security.py`, `tests/test_llm_gateway.py`); 1, 2 y 4 dependen de la BD y de la instalación (HU-04, HU-20, HU-37); 3 de HU-26.
