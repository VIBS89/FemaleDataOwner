# F17 — Residencia de datos · común

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
| **D3: metadatos estructurales** | Nombres y descripciones de BDs, tablas y columnas, tipos, FKs, conteos, parámetros de SPs | Catálogo e índice (cloud u on-prem) |
| **D4: plantillas anonimizadas** | Golden SQL con literales sustituidos por placeholders | Índice (cloud u on-prem), con el original en la auditoría on-prem |
| **D5: telemetría sin contenido** | Latencias, tokens, códigos de error, ids de traza, nombres de tablas usadas | Logs y métricas (cloud u on-prem) |
| **C: credenciales** | Login SQL por usuario | Custodia cifrada según F14 (CN-03 / OP-03) |

## Reglas comunes
- El catálogo nunca contiene valores (F1) y no existe índice de valores (F5).
- Los sketches MinHash del descubrimiento (F18, F19) se calculan en memoria con hashes salados y se descartan; solo persisten las relaciones inferidas.
- El sandbox de análisis (F20) no tiene red ni almacenamiento persistente.
- El historial de conversación vive solo en la memoria de la sesión.
- Chainlit sin data layer; las descargas se generan en streaming al navegador.
- Logs y spans con lista blanca de atributos D5; un filtro descarta `question`, `sql`, `rows`, `prompt` y `completion`.
- **Bedrock**: procesa sin almacenar; *model invocation logging* desactivado en la cuenta usada.
- **NVIDIA NIM (fallback)**: envía D1/D2 a un tercero. Desactivado por defecto con datos reales; solo se activa con un acuerdo de procesamiento de datos o con NIM autoalojado.

## Criterios de aceptación (ambos entornos)
1. Tras 100 preguntas de prueba con literales marcados (por ejemplo "ACME-TEST-123"), una búsqueda de ese literal en todo almacenamiento distinto de la auditoría on-prem devuelve **0 coincidencias**.
2. *Model invocation logging* de Bedrock desactivado (verificado).
3. El indexador rechaza un YAML de catálogo con valores.
4. Al cerrar la sesión, el historial deja de existir.
