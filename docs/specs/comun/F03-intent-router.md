# F3 — Intent & Router

## Historia de usuario
Como **usuario**, quiero que el sistema entienda qué estoy pidiendo y en qué base está, y que me pregunte cuando
mi pregunta sea ambigua en lugar de inventar una respuesta.

## Entrada y salida
- Entrada: `question`, `history[]` (últimos 5 turnos), `visible_databases[]`.
- Salida (`IntentResult`, Pydantic):
```python
class IntentResult(BaseModel):
    intent: Literal["discovery", "exploration", "data_query", "procedure", "out_of_scope", "ambiguous"]
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
  (`features.ask_flow: false`, fase 1 del piloto), se responden como `discovery` y se indica qué tabla o SP usar.
- Ante la duda entre `discovery` y `data_query`, gana `discovery` (no ejecuta nada y es más barato).
- Con `confidence < 0.6` o el intent `ambiguous`, el flow termina con `status=needs_clarification` y hasta cuatro opciones concretas.
- `out_of_scope` cubre saludos, preguntas generales o peticiones de escritura no permitidas. Devuelve una respuesta educada sin ejecutar nada.

## Criterios de aceptación
1. "ventas del último trimestre" con fecha actual 2026-10-14 se normaliza a `time_range = 2026-07-01..2026-09-30`.
2. "dame los datos" (sin entidad) devuelve `needs_clarification`.
3. "borra los pedidos cancelados" devuelve `out_of_scope` con una explicación.
4. En un conjunto de 30 preguntas etiquetadas, el router acierta la BD en al menos el 90 % de los casos.
5. "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital" se clasifica como `discovery`
   con `business_context = "onboarding digital"` y `asset_kind_hint = "column"`.
6. En un set de 40 preguntas mixtas, la clasificación `discovery` vs `data_query` acierta en al menos el 95 %.
