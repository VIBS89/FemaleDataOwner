# F17 — Residencia de datos · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Inventario de controles por entorno: **cloud native** → [CN-06](../cloud-native/CN-06-residencia-datos.md) · **on-premise** → [OP-06](../on-premise/OP-06-residencia-datos.md)

## Principio
**La infraestructura cloud procesa y muestra; no guarda.** Ningún dato de clientes ni texto que pueda contenerlos (preguntas, SQL
con literales, resultados, valores de columnas, historial de conversación) se persiste fuera de la red del cliente. Todo lo que debe
persistir y puede contener datos vive **on-premise**.

## Clasificación de la información
| Clase | Ejemplos | Dónde puede persistir |
|---|---|---|
| **D1: datos de clientes** | Filas de resultado, valores de columnas, muestras | En ningún sitio. Solo en memoria durante la petición |
| **D2: texto derivado del usuario** | Pregunta, pregunta reescrita, SQL con literales, narrativa, historial | Solo en la auditoría on-premise (F11) |
| **D3: metadatos estructurales** | Nombres y descripciones de BDs, tablas y columnas, tipos, FKs, conteos, parámetros de SPs; reglas de negocio, linaje ETL y fragmentos de documentos **ya redactados** (F23) | Catálogo e índice (cloud u on-prem) |
| **D4: plantillas anonimizadas** | Golden SQL con literales sustituidos por placeholders (fase 1b) y golden discovery como plantilla sin literales: la pregunta normalizada sin ninguna palabra que lleve un dígito o una arroba (tras normalizar con NFKC), salvo el vocabulario conocido del banco: nombres del catálogo con dígitos (`Ultimos4`) y códigos del conocimiento con letras y dígitos (`NCB-022`, `BR-ONB-004`) (F24; `converdata.memory.text.strip_literals`). Limitación: la plantilla no detecta nombres de personas, texto entre comillas ni los trozos solo de letras de un código partido por espacios | Índice (cloud u on-prem). El original queda en la auditoría on-prem y, solo si la pregunta no traía ningún literal ni parece llevar datos personales, en el esquema `golden` on-prem, con la misma retención |
| **D5: telemetría sin contenido** | Latencias, tokens, códigos de error, ids de traza, nombres de tablas usadas | Logs y métricas (cloud u on-prem) |
| **C: credenciales** | Login SQL por usuario | Custodia cifrada según F14 (CN-03 / OP-03) |

## Reglas comunes
- El catálogo nunca contiene valores (F1) y no existe índice de valores (F5).
- Una pregunta que, quitados los literales, aún parece llevar datos personales no se guarda como golden discovery: el voto cuenta y
  queda en la auditoría, pero no se aprende (F24).
- Los sketches MinHash del descubrimiento (F18, F19) se calculan en memoria con hashes salados y se descartan; solo persisten las relaciones inferidas.
- El sandbox de análisis (F20) no tiene red ni almacenamiento persistente.
- El historial de conversación vive solo en la memoria de la sesión.
- El estado de los grafos de LangGraph (checkpointer) vive **solo en memoria** durante la petición; no se usa un checkpointer persistente.
- La web (Next.js) no persiste chats, credenciales ni archivos; las descargas se generan en streaming al navegador.
- Logs y spans con lista blanca de atributos D5; un filtro descarta `question`, `sql`, `rows`, `prompt` y `completion`.
- **Bedrock**: procesa sin almacenar; *model invocation logging* desactivado en la cuenta usada.
- **NVIDIA NIM (fallback)**: envía D1/D2 a un tercero. Desactivado por defecto con datos reales; solo se activa con un acuerdo de procesamiento de datos o con NIM autoalojado.

## Criterios de aceptación (ambos entornos)
1. Tras 100 preguntas de prueba con literales marcados (por ejemplo "ACME-TEST-123"), una búsqueda de ese literal en todo almacenamiento distinto de la auditoría on-prem devuelve **0 coincidencias**.
2. *Model invocation logging* de Bedrock desactivado (verificado).
3. El indexador rechaza un YAML de catálogo con valores.
4. Al cerrar la sesión, el historial deja de existir.

Estado del criterio 1 (2026-11-17, on-premise): se cumple en lo que cubre `api/tests/test_marked_literals.py`. Son 100 preguntas
con 100 literales distintos en 10 formas (códigos `ACME-TEST-nnn`, documentos, cuentas alfanuméricas, correos, números y, tras la
revisión de seguridad, alfanumérico corto, dígitos en superíndice, raya en vez de guion, guion bajo con guion final y ancho
completo), hechas por la API con tres usuarios (el literal va también en `history` de `/discover`), votadas, 20 escaladas con nota
y varias respondidas por un responsable. El literal se busca después, también transformado (minúsculas, normalizado con NFKC y
recortado a los 6 caracteres del stemmer), en el índice en memoria, en todo el disco del servidor (logs incluidos) y en toda
columna de toda tabla de la BD `ConverData` que no sea número, fecha, bit o `uniqueidentifier`, convertida a texto (historial
incluido). Comprueba además que las plantillas solo contienen palabras de las preguntas base. Solo aparece en `audit.audit_question.question`, `curation.request.question` y `curation.request.note` (en
modo archivos, en `audit/*.jsonl` y `curation/requests.json`): las dudas escaladas son texto D2 on-premise con la retención de la
auditoría (OP-06). Corre en archivos y, con `CONVERDATA_TEST_DB`, en SQL Server real. No cubre el cliente MCP, `/discover/stream`, el Visor de eventos de Windows (`event_log` va apagado en la prueba), `TEMP` de las
cuentas de servicio, las carpetas de IIS ni los volcados de memoria (servidor del piloto, HU-37), ni el despliegue cloud (CN-06),
y los nombres de personas siguen sin detectarse.
