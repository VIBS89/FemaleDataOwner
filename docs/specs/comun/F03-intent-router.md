# F3 — Intent & Router

## Historia de usuario
Como **usuario**, quiero que el sistema entienda qué estoy pidiendo y en qué base está, y que me pregunte cuando
mi pregunta sea ambigua en lugar de inventar una respuesta.

## Entrada y salida
- Entrada: `question`, `history[]` (últimos 5 turnos), `visible_databases[]`.
- Salida (`IntentResult`, Pydantic):
```python
class IntentResult(BaseModel):
    intent: Literal["data_query", "exploration", "procedure", "metadata", "out_of_scope", "ambiguous"]
    databases: list[str]          # candidatas, ordenadas
    domain: str | None
    entities: list[str]           # sustantivos de negocio ("ventas", "clientes")
    literals: list[str]           # valores a resolver en F5 ("Monterrey", "2025")
    time_range: str | None        # normalizado: "2026-07-01..2026-09-30"
    rewritten_question: str       # autocontenida, incorpora el contexto del historial
    confidence: float
    clarification: Clarification | None
```

## Comportamiento
- Agente `Intent Analyst` (rol `planner` de F16, temperatura 0.1, `output_pydantic=IntentResult`).
- El enrutamiento por BD combina:
  1. `search_tables(question)` agrupado por base de datos (votación ponderada por score),
  2. los dominios del `_database.yaml`,
  3. la decisión final del LLM.
- `metadata` cubre preguntas como "¿qué tablas tienen datos de clientes?". Se responde desde el catálogo sin ejecutar SQL.
- `exploration` cubre preguntas como "¿qué datos tenemos de inventario?". Devuelve un resumen del dominio con las tablas, columnas clave y ejemplos de preguntas.
- Con `confidence < 0.6` o el intent `ambiguous`, el flow termina con `status=needs_clarification` y hasta cuatro opciones concretas.
- `out_of_scope` cubre saludos, preguntas generales o peticiones de escritura no permitidas. Devuelve una respuesta educada sin ejecutar nada.

## Criterios de aceptación
1. "ventas del último trimestre" con fecha actual 2026-10-14 se normaliza a `time_range = 2026-07-01..2026-09-30`.
2. "dame los datos" (sin entidad) devuelve `needs_clarification`.
3. "borra los pedidos cancelados" devuelve `out_of_scope` con una explicación.
4. En un conjunto de 30 preguntas etiquetadas, el router acierta la BD en al menos el 90 % de los casos.
