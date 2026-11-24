# F3 — Intent & Router

## Historia de usuario
Como **usuario**, quiero que el sistema entienda qué estoy pidiendo y en qué base está, y que me pregunte cuando
mi pregunta sea ambigua en lugar de inventar una respuesta.

## Entrada y salida
- Entrada: `question`, `history[]` (últimos 5 turnos; el cliente los envía), `visible_databases[]`.
- Salida (`IntentResult`, Pydantic):
```python
class IntentResult(BaseModel):
    intent: Literal["discovery", "exploration", "data_query", "procedure", "out_of_scope", "ambiguous", "assistant"]
    analysis_mode: Literal["lookup", "compare", "explain", "explore", "forecast", "report"]  # F20
    entities_resolved: list[str]  # entidades del grafo de F19 (p. ej. "cliente")
    databases: list[str]          # candidatas, ordenadas
    domain: str | None
    entities: list[str]           # sustantivos de negocio ("ventas", "clientes")
    business_context: str | None  # proceso o área ("onboarding digital"); usado por F22
    asset_kind_hint: Literal["column", "table", "indicator", "rule"] | None
    environment_hint: str | None  # "produccion" por defecto (F1)
    literals: list[str]           # valores a resolver en F5 ("Monterrey", "2025")
    time_range: str | None        # normalizado: "2026-07-01..2026-09-30"
    rewritten_question: str       # autocontenida, incorpora el contexto del historial
    confidence: float
    clarification: Clarification | None
```

## Comportamiento
- Nodo `intent` del grafo de LangGraph (rol `planner` de F16, temperatura 0.1, `with_structured_output(IntentResult)`).
- El enrutamiento por BD combina:
  0. las **entidades del grafo** de F19 (dónde vive cada concepto y su tabla canónica); si una entidad vive en varias BDs sin canónica, se pide aclaración,
  1. `search_tables(question)` agrupado por base de datos (votación ponderada por score),
  2. los dominios del `_database.yaml`,
  3. la decisión final del LLM.
- **`discovery` es el intent por defecto** cuando la pregunta busca *dónde está* o *qué significa* un dato ("necesito el identificador del
  cliente de onboarding", "¿qué tablas tienen datos de clientes?", "¿qué significa EstadoCta?"). Se enruta al **DiscoverFlow (F22)**,
  que responde desde el catálogo y el conocimiento, sin ejecutar SQL sobre datos.
- `exploration` cubre preguntas como "¿qué datos tenemos de inventario?". Se enruta al DiscoverFlow en modo **resumen de dominio**
  (F22, §Resumen de dominio) con tablas, columnas clave, responsables, reglas y ejemplos de preguntas.
- `data_query` y `procedure` (piden cifras o filas) se enrutan al AskFlow (F4–F10). Si el despliegue no tiene habilitado el AskFlow
  (`features.ask_flow: false`, fase 1 del piloto), se responden como `discovery` y se indica qué tabla o SP usar. **Primer corte de
  cifras (2026-11-23, PRD §13, decisión 17):** con `features.ask_flow` (o `CONVERDATA_ASK_FLOW=1`) y un ejecutor de la sesión, una pregunta
  de `data_query` se descubre primero y después el nodo `compute` calcula, si puede, un `COUNT`, `COUNT DISTINCT`, `SUM` o `AVG` sobre una
  tabla (`src/converdata/discovery/figures.py`); el sobre lleva `flow: "ask"` y `figure`. Con periodo, cruce, medida no numérica o sin saber
  qué contar no calcula y lo dice en `assumptions`.
- Ante la duda entre `discovery` y `data_query`, gana `discovery` (no ejecuta nada y es más barato).
- **`asset_kind_hint`** (actualizado el 2026-11-17). Sin LLM lo fija el clasificador por reglas
  (`discovery/deterministic.py: _kind_hint`), en este orden: `table` para exploración, cifras, preguntas que nombran "tabla" y
  preguntas de ETL; `column` si se pregunta "¿qué / cuál campo, columna o llave…?" (`_ASKS_FIELD`); `table` para las preguntas de
  cruce "¿cómo relaciono / cruzo / uno A con B?" (`_JOIN`; "cada uno de" no es un cruce); después `indicator` y `rule`. Si la
  intención (con o sin LLM) no trae tipo y el intent es `discovery`, el nodo `intent` del DiscoverFlow lo completa con el catálogo
  (`engine.entity_kind_hint`): un plural que nombra una tabla o vista visible para el usuario pide `table` (F22, §Qué tipo de
  activo se pide).
- Con `confidence < 0.6` o el intent `ambiguous`, el flow termina con `status=needs_clarification` y hasta cuatro opciones concretas.
- `out_of_scope` cubre preguntas generales o peticiones de escritura no permitidas. Devuelve una respuesta educada sin ejecutar nada.
  La orden de modificar datos se evalúa **solo sobre la pregunta actual**, no sobre el historial que manda el cliente
  (`deterministic.is_write_request`); una pregunta que solo describe un cambio no se rechaza.
- **`assistant`** (2026-11-23). Saludos, cortesía y preguntas sobre el propio asistente ("¿cómo te enteras de tablas nuevas?", "¿qué bases
  conoces?"). El tema lo fijan reglas (`discovery/assistant.py::topic_of`; temas: `greeting`, `thanks`, `farewell`, `identity`,
  `capabilities`, `freshness`, `sources`, `privacy`, `databases`, `corrections`, `permissions`, `execution`, `confidence`) y el texto de
  cada respuesta es fijo: el modelo nunca redacta cómo funciona la herramienta. El sobre trae `status: ok` y `discovery: null`; el tema
  `databases` lista solo las bases que el usuario ve. Un saludo seguido de una pregunta de datos se busca sin el saludo. Si la búsqueda
  no encuentra nada y hay modelo, `LlmGuide` (rol `fast`) puede reconocer una pregunta sobre el asistente entre esos mismos temas.
- **Seguimientos** (2026-11-23). "¿Y los de leasing?" se entiende con la pregunta anterior: `deterministic.contextualize` la completa con
  el historial (hasta tres turnos atrás) cuando el mensaje es corto, empieza con un conector o trae una anáfora; una pregunta nueva no se
  toca. La auditoría conserva la pregunta tal como se escribió.
- **Redacción de chat** (2026-11-23). Las palabras de relleno ("necesito saber", "por favor") y los términos de cálculo y de periodo
  ("total", "promedio", "el mes pasado") no cuentan como parte de lo que se busca (`expansion.QUESTION_FILLER`, `expansion.ANALYSIS_TERMS`,
  `engine.kept_analysis_terms`, que conserva el término si forma parte de un nombre del catálogo: "monto total").

## Estado (2026-11-23)
- Sin LLM, el clasificador por reglas (`RuleBasedIntentClassifier`) no rellena `time_range`: el criterio 1 solo vale con LLM y no se midió.
- No se midieron los criterios 4 (30 preguntas de BD) ni 6 (40 preguntas mixtas). Hay un set de 67 preguntas de chat que mide el efecto
  de punta a punta, no solo la intención (`tests/fixtures/bancos/eval/chat.yaml`; [plan §2](../../PLAN-desarrollo.md#2-resultados-medidos)).
- Con `planner` declarado, el LLM clasifica la intención; la medición lo desaconseja por ahora (el orden es determinista).
- Pruebas: `tests/test_chat_conversacional.py` (temas, seguimientos, escrituras) y `tests/test_cifras_agregadas.py` (enrutado a `compute`).

## Criterios de aceptación
1. "ventas del último trimestre" con fecha actual 2026-10-14 se normaliza a `time_range = 2026-07-01..2026-09-30`.
2. "dame los datos" (sin entidad) devuelve `needs_clarification`.
3. "borra los pedidos cancelados" devuelve `out_of_scope` con una explicación.
4. En un conjunto de 30 preguntas etiquetadas, el router acierta la BD en al menos el 90 % de los casos.
5. "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital" se clasifica como `discovery`
   con `business_context = "onboarding digital"` y `asset_kind_hint = "column"`.
6. En un set de 40 preguntas mixtas, la clasificación `discovery` vs `data_query` acierta en al menos el 95 %.
