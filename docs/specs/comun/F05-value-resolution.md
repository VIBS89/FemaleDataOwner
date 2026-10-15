# F5 — Value Resolution · común

## Historia de usuario
Como **usuario**, quiero escribir "clientes de Monterrey" o "producto bici roja" con mis propias palabras, y que el sistema
encuentre la columna y el valor exactos que existen en la BD.

## Algoritmo (igual en ambos entornos: siempre en vivo, sin índice de valores)
1. Toma los `literals` de F3.
2. Para cada literal y cada columna candidata del `SchemaContext` (texto, baja cardinalidad o nombre similar), consulta en vivo **con la identidad del usuario**:
   `SELECT DISTINCT TOP (10) [col] FROM [t] WHERE [col] LIKE @p`. La consulta va parametrizada, con timeout de 5 s; si la columna tiene índice full-text, usa `CONTAINS`.
3. Ordena los candidatos con `rapidfuzz.WRatio`. Fechas, números y periodos se normalizan de forma determinista (dateparser, locale `es`).
4. Devuelve un `ValueBinding` por literal: `{literal, table, column, value(s), match_score, method}`.
5. Si `match_score < 0.75` o hay varios candidatos con puntuaciones similares (diferencia menor de 0.05), se registra como supuesto. Si el literal es crítico (por ejemplo un filtro de cliente), se pide aclaración.

Los valores devueltos solo viven en memoria durante la petición (F17).

## Criterios de aceptación
1. "Monterey" se resuelve a `Ciudad.Nombre = 'MONTERREY'` con `score ≥ 0.85`.
2. La consulta en vivo siempre está parametrizada (test: un literal con `'; DROP TABLE x--` no altera el SQL).
3. Los valores de columnas PII no se muestran al LLM; solo se confirma que existen coincidencias.
4. Como usa el login del usuario, nunca se resuelven valores de tablas que no puede leer.
