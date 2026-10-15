# F9 — Result Verifier

## Historia de usuario
Como **usuario**, quiero saber si el resultado realmente responde a mi pregunta y cuánta confianza merece,
antes de usarlo para tomar decisiones.

## Chequeos deterministas (Python)
| Chequeo | Regla | Severidad |
|---|---|---|
| `empty_result` | 0 filas | warn: puede haber un filtro demasiado estricto o un valor mal resuelto |
| `truncated` | se alcanzó el tope de filas | warn |
| `fan_out` | si hay joins y agregaciones: se re-ejecuta `COUNT(*)` vs `COUNT(DISTINCT pk_base)` sobre el FROM/JOIN sin agregar. Si son distintos, hay duplicación por join | fail → vuelve al planner con feedback |
| `null_ratio` | columna de resultado con más de 50 % de NULL | warn |
| `range_sanity` | porcentajes fuera de 0–100, conteos negativos, fechas fuera de `time_range` | fail |
| `grain` | el número de grupos no cuadra con la intención (por ejemplo "por mes" en un trimestre debería dar 3 filas o menos) | warn |
| `time_coverage` | el min/max de la columna de fecha cubre el `time_range` pedido | warn |

## LLM-judge
- Nodo `judge` del grafo, con un modelo **distinto** al planner (rol `judge` de F16: Amazon Nova o Llama en Bedrock si el coder es Claude).
- Recibe: pregunta reescrita, SQL o SP, supuestos, esquema del resultado, las primeras 20 filas y las estadísticas (`describe()`), y los chequeos.
- Devuelve:
  ```python
  class Verdict(BaseModel):
      answers_question: bool
      issues: list[str]          # "falta filtro de estado", "usa fecha de creación en vez de facturación"
      suggested_fix: str | None
      score: float               # 0..1
  ```
- Con `answers_question=false` y un `suggested_fix`: un único reintento del planner con ese feedback.

## Cálculo de confidence
```
confidence = 0.5*judge.score + 0.2*(golden_similarity≥0.9) + 0.15*checks_pass_ratio
           + 0.15*(candidatos coinciden | o SP oficial)
```
Se limita a 0.5 como máximo si hay algún chequeo `fail` sin resolver. Las respuestas con `confidence < 0.6` se muestran con un aviso visible.

## Criterios de aceptación
1. Un SQL con join 1:N que duplica importes se detecta como `fan_out` y se corrige en el reintento.
2. Las respuestas con confidence menor de 0.6 tienen un error real en al menos el 70 % de los casos del set de evaluación (calibración).
3. El juez nunca recibe más de 20 filas ni valores de columnas PII.
