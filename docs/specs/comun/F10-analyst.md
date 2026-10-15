# F10 — Analyst (post-proceso y respuesta)

> Los modos analíticos avanzados (comparar, explicar, explorar, pronosticar, informe) están en [F20](F20-analysis-engine.md).

## Historia de usuario
Como **usuario de negocio**, quiero una respuesta clara en español, con los datos en una tabla, un gráfico cuando
aporte valor y una explicación de cómo se obtuvo.

## Comportamiento
1. **Post-proceso determinista (pandas)**:
   - Formato de moneda y porcentajes según los metadatos de columna.
   - Totales y subtotales cuando la pregunta lo pide.
   - Variaciones (%, delta) si hay comparación entre periodos.
   - Ordenación coherente con la pregunta ("top", "mayor").
2. **Selección de gráfico** (reglas primero; el LLM solo desempata):
   - 1 fila y 1 métrica: *KPI*.
   - Serie temporal: *line*.
   - Categoría (12 o menos) con métrica: *bar*.
   - Más de 12 categorías: *bar* horizontal con top 12.
   - Dos métricas numéricas: *scatter*.
   - En otro caso, sin gráfico.
   Salida: `chart_spec` compatible con Plotly (`{type, x, y, color?, title}`).
3. **Narrativa**: el agente `Data Analyst` (modelo planner) escribe 2 a 5 frases que:
   - responden directamente con las cifras clave;
   - mencionan supuestos y avisos de F9;
   - **no inventan cifras**: cada número de la narrativa debe existir en el resultado o derivarse de él (validación con regex de números contra el DataFrame).
4. Construye el `AnswerEnvelope` (ver `docs/features.md`).

## Criterios de aceptación
1. La narrativa no contiene números que no aparezcan en los datos (test automatizado sobre el set de evaluación).
2. Una serie temporal de 12 meses produce `chart_spec.type = "line"`.
3. El texto está en español y tiene 120 palabras o menos, salvo que el usuario pida detalle.
