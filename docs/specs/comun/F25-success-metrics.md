# F25 — Métricas de éxito y piloto · común

> Origen: Propuesta, sección 4 ("Evidencia cuantificable propuesta") y "Métricas propuestas de éxito". La propuesta reconoce que hoy
> **no hay línea base**; esta spec define cómo medirla antes del piloto y cómo instrumentar la solución para medir el después.

## Métricas de negocio (las de la propuesta)
| Métrica | Línea base (antes del piloto) | Medición con ConverData | Objetivo |
|---|---|---|---|
| Tiempo de localización de fuentes de datos | Estudio de tiempos: 15–20 búsquedas reales cronometradas con el método actual, por perfil | Tiempo desde la pregunta hasta el "✔ Es este" (o hasta el clic en "Ver detalle" del candidato elegido); mediana por perfil | −50 % |
| Consultas a expertos funcionales | Encuesta de 2 semanas a los expertos (consultas recibidas por día) + conteo en el canal o tickets donde se piden | Solicitudes escaladas (F24) + misma encuesta durante el piloto | −30 % |
| Tiempo promedio de análisis de requerimientos | Duración de la fase de análisis en el gestor de requerimientos (Jira/Azure DevOps) de los últimos 3 meses, para el equipo piloto | La misma fuente durante el piloto, en requerimientos donde se usó el agente (etiqueta `usa-discovery-agent`) | −20 % a −40 % |
| Reprocesos por selección incorrecta de fuente | Etiqueta `reproceso-fuente` en el gestor de requerimientos (se crea al iniciar la línea base) | La misma etiqueta + candidatos confirmados que luego se rechazan ("✖" posterior) | −20 % |

> Los porcentajes son metas iniciales sujetas a validación en el piloto, como indica la propuesta.

## Métricas de adopción y conocimiento
| Métrica | Fuente | Uso |
|---|---|---|
| Usuarios activos semanales y preguntas por usuario | `audit_question` | Adopción del autoservicio |
| % de preguntas resueltas sin escalar | `audit_discovery` vs `curation_request` | Menor dependencia de expertos |
| % de columnas consultadas con descripción revisada (`human`, `data_dictionary`) | Catálogo + `audit_discovery` | Activos de conocimiento documentados |
| Golden discovery creados por semana | `golden_discovery` | Conocimiento capturado desde el uso |
| Preguntas equivalentes hechas por equipos distintos y resueltas desde golden | `audit_discovery` | Reducción de esfuerzo duplicado |
| Tiempo hasta la primera fuente correcta de colaboradores nuevos (< 90 días en la organización) | Encuesta + métrica de localización por cohorte | Incorporación de nuevos colaboradores |
| Dominios con steward y brechas abiertas/cerradas | F24 | Adopción de prácticas de gobierno de datos |

## Métricas de calidad del agente
Set de evaluación de descubrimiento (`eval/discovery.yaml`): 50–80 preguntas reales del equipo piloto, cada una con los `asset_key` correctos
validados por un experto, más 5 preguntas sin respuesta en las fuentes (para medir brechas).
| Métrica | Umbral de salida del piloto |
|---|---|
| Hit@1 / Hit@3 | ≥ 65 % / ≥ 85 % |
| MRR | ≥ 0.75 |
| Calibración: candidatos con confianza ≥ 0.8 que son correctos | ≥ 85 % |
| Preguntas sin respuesta marcadas como `knowledge_gap` | ≥ 4 de 5 |
| Objetos inventados en la narrativa | 0 |
| Latencia p50 / p95 | < 5 s / < 10 s |
| Fugas de permisos (F14) | 0 |

## Instrumentación
- Todo se calcula desde la auditoría (F11) y el catálogo; **sin contenido** fuera de la auditoría on-prem (F17).
- `converdata metrics report --from --to [--team]` genera un CSV y un HTML con las métricas de esta spec.
- `converdata eval discovery` corre el set de evaluación y publica Hit@k, MRR, calibración y latencia; se ejecuta en cada cambio de prompt,
  modelo o índice (regresión).

## Plan del piloto (8 semanas)
| Semana | Actividad | Entregable |
|---|---|---|
| 0–1 | Línea base: estudio de tiempos, encuesta a expertos, etiquetas en el gestor de requerimientos | Línea base firmada por la Gerencia de Datos |
| 1–3 | Ingesta del dominio piloto (clientes / onboarding digital): catálogo, diccionarios, documentos, SSIS y reglas; steward asignado | Catálogo + `eval/discovery.yaml` validado |
| 2–3 | Curación inicial: el steward revisa los 100 activos más relevantes | % de descripciones revisadas |
| 4–7 | Uso real por 10–15 colaboradores de varios perfiles (ingeniería, analítica, BI, Product Owners) | Métricas semanales |
| 8 | Evaluación contra la línea base y decisión de escalar | Informe de resultados y recomendación |

## Criterios de aceptación
1. Antes del piloto existe una línea base registrada para las 4 métricas de negocio.
2. `converdata metrics report` produce todas las métricas de esta spec a partir de la auditoría, sin leer preguntas ni SQL.
3. `converdata eval discovery` falla (exit code ≠ 0) si Hit@3 baja más de 5 puntos respecto a la última ejecución aprobada.
