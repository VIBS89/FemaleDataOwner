# F20 — Motor de análisis: de "responder una consulta" a "analizar" · común

> Amplía [F10](F10-analyst.md). Inspirado en InsightPilot (Microsoft Research), Data Interpreter (MetaGPT), TaskWeaver (Microsoft), PandasAI, ThoughtSpot Spotter y Power BI *key influencers*.

## Problema
Hoy el flujo responde **una** consulta SQL y la resume. Las preguntas de negocio valiosas son analíticas: "¿por qué bajaron las
ventas en el norte?", "¿qué cambió respecto al trimestre pasado?", "¿hay algo raro en las devoluciones?". Requieren varias
consultas, cálculos y un razonamiento verificable.

## Modos de respuesta (los elige F3)
| Modo | Ejemplo | Cómo se resuelve |
|---|---|---|
| `lookup` | "ventas por región del Q3" | Flujo actual (una consulta, F6–F10) |
| `compare` | "Q3 vs Q2 por región" | Dos periodos con la misma métrica, deltas absolutos y %, aportación de cada segmento |
| `explain` (*¿por qué?*) | "¿por qué bajaron las ventas del norte?" | **Análisis de causa raíz** (ver abajo) |
| `explore` | "¿qué hay de interesante en devoluciones?" | **Motor de insights** automático |
| `forecast` | "¿cuánto venderemos el próximo mes?" | Serie temporal + modelo simple con intervalo; siempre marcado como **estimación** |
| `report` | "resumen ejecutivo de ventas del trimestre" | Plan multi-paso que combina los anteriores en un informe con secciones |

## Planificador de análisis
Inspirado en el grafo jerárquico de Data Interpreter y el enfoque *code-first* de TaskWeaver:
- El nodo `analysis_planner` descompone la pregunta en un **DAG de pasos tipados**: `query` (SQL validado por F7 y ejecutado con el login del usuario), `compute` (función de la biblioteca de análisis), `insight` (detector) y `narrate`.
- Cada nodo tiene entradas y salidas declaradas; un fallo reintenta solo ese nodo (máximo 2 intentos).
- Límites: 8 consultas y 60 s de BD por análisis. Si se superan, entrega lo obtenido y lo indica.
- El DAG se muestra en el chat como pasos en vivo y queda en auditoría (F11) para reproducirlo.

## Biblioteca de análisis determinista (antes que código libre)
Funciones Python probadas que el planner invoca por nombre con parámetros. El LLM **elige y parametriza**, pero **no calcula**:

| Función | Qué hace |
|---|---|
| `period_compare(df, metric, period_a, period_b, by)` | Deltas, % y contribución de cada segmento al cambio total |
| `variance_decomposition(df, metric, dims)` | Descompone un cambio en efecto **volumen, precio y mezcla**, y por dimensión (contribution analysis) |
| `drill_down(df, metric, dims, top_k)` | Árbol de descomposición: busca la combinación de dimensiones que más explica el cambio |
| `detect_anomalies(series)` | Outliers robustos (MAD / IQR) y cambios de nivel (*change points*) |
| `trend_seasonality(series)` | Tendencia y estacionalidad (STL), con pendiente y significancia |
| `top_contributors(df, metric, dim)` | Pareto: qué segmentos suman el 80 % |
| `correlate(df, cols)` | Correlaciones con advertencia explícita de "correlación ≠ causalidad" |
| `distribution_shift(a, b)` | Cambio de distribución entre periodos (KS / chi²) |
| `cohort_retention(df, entity, date, event)` | Cohortes y retención |
| `forecast(series, horizon)` | ETS / ARIMA simple (statsmodels) con intervalo de predicción |
| `significance(a, b)` | Test estadístico apropiado, con resultado en lenguaje llano |

Todas devuelven resultados estructurados, sin texto, que después narra F10.

## Motor de insights (modo `explore`)
Siguiendo InsightPilot, los insights los **calculan detectores** y el LLM solo los selecciona, ordena y narra; así se evitan
"insights" inventados:
1. Para la tabla o métrica elegida, recorre las dimensiones candidatas (baja cardinalidad, del catálogo) y aplica detectores: tendencia, outlier, cambio de nivel, dominancia (Pareto), estacionalidad y correlación.
2. Puntúa cada insight por **significancia estadística × magnitud × relevancia** para la pregunta.
3. Devuelve los 3–5 mejores, cada uno con su gráfico y la consulta que lo respalda.
4. Propone **preguntas de seguimiento** ("¿quieres ver el detalle por producto?").

## Análisis de causa raíz (modo `explain`)
1. Confirma el hecho ("las ventas del norte bajaron un 12 % vs Q2"); si no se confirma, lo dice.
2. `variance_decomposition` y `drill_down` sobre las dimensiones disponibles (producto, canal, cliente, vendedor…), guiados por las entidades del grafo de F19.
3. Para los principales contribuyentes, busca cambios coincidentes en otras tablas relacionadas del grafo (por ejemplo, devoluciones o precio).
4. Presenta una **explicación ordenada por aportación**, con cifras, y separa "lo que los datos muestran" de "hipótesis no verificadas".

## Código Python libre (último recurso)
Solo cuando ninguna función de la biblioteca sirve, y siempre en sandbox:

| Entorno | Sandbox |
|---|---|
| Cloud native | **AgentCore Code Interpreter** (aislado por sesión) |
| On-premise (Windows Server) | **No disponible en la v1**: solo la biblioteca determinista. Más adelante, contenedor aislado con Hyper-V, sin red, con pandas, numpy, scipy, statsmodels y duckdb |

- El sandbox recibe los DataFrames ya obtenidos con el login del usuario; **no tiene conexión a SQL Server ni a internet**.
- El código generado se registra en auditoría y se muestra en "cómo lo obtuve".
- Ningún archivo persiste al terminar la sesión (F17).

## Verificación (amplía F9 y F10)
- Cada cifra de la narrativa debe existir en la salida de una función o consulta (validación con regex de números contra los resultados).
- El verificador revisa la coherencia del DAG: periodos comparables, misma definición de métrica en ambos lados y denominadores correctos.
- La causa raíz nunca afirma causalidad: usa "contribuyó", "coincide con" y "se asocia a".

## Criterios de aceptación
1. Con datos sintéticos donde la caída se debe a un solo producto en una región, el modo `explain` identifica esa combinación como principal contribuyente.
2. En un dataset con 3 insights plantados (tendencia, outlier y dominancia), el modo `explore` encuentra al menos 2 en el top 5.
3. Ninguna cifra de la narrativa sale de fuera de los resultados calculados (test automático).
4. El código libre en el sandbox no puede abrir conexiones de red (test).
5. Los pronósticos siempre incluyen intervalo y la etiqueta "estimación".
