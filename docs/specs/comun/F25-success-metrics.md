# F25 — Métricas de éxito y piloto · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
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
- `converdata metrics report --from --to [--team]` genera un CSV y un HTML con las métricas de esta spec (comando pendiente; hoy las métricas se consultan en `GET /admin/metrics` y en la vista Métricas de la web, solo `data_admin`).
- `converdata eval discovery` corre el set de evaluación y publica Hit@k, MRR, calibración y latencia; se ejecuta en cada cambio de prompt,
  modelo o catálogo (regresión), con `--min-hit3` como umbral de alerta.
- `converdata eval gate` es la **compuerta de calidad** previa a cada despliegue: 7 suites (`calidad`, `permisos`, `inyeccion`, `guardas`,
  `robustez`, `determinismo`, `auditoria`) contra los umbrales de esta spec y la línea base `eval/baseline.yaml`
  ([calidad bancaria §2](../../calidad-bancaria.md)). Toda mejora se acepta solo si no baja ningún tipo de pregunta (A–G).
- Hoy (2026-11-23) el set de evaluación son 89 preguntas escritas por el equipo sobre dos catálogos de prueba (58 de BancosSQL y 31 de VBank), más 25 de reporte y 67 de chat; el set de 50–80 preguntas reales del piloto está pendiente (HU-33). Resultado en modo determinista (medido de nuevo el 2026-11-23, sin cambio): Hit@1 y Hit@3 98,0 % en BancosSQL y 96,2 % en VBank, con una pregunta sin candidatos en cada uno ([plan de desarrollo §2](../../PLAN-desarrollo.md#2-resultados-medidos)).
- **Con y sin fuentes de conocimiento.** `converdata eval discovery --knowledge <dir>` añade al catálogo de `--root` las fuentes de `<dir>` (`items/`, `rules/`, `golden/`, `lineage/`) sin tocarlo, para medir cuánto aportan (no se combina con `--db`). Medición del 2026-11-23 con 25 preguntas de reporte sobre BancosSQL (`tests/fixtures/bancos/eval/reportes.yaml`: 9 normativas, 8 de tablero, 8 de estudio) y un glosario y manual de indicadores de prueba de 20 entradas: Hit@1 28 % solo con catálogo → 64 % con conocimiento; Hit@3 32 % → 64 %; normativas 22,2 → 66,7 %, tablero 50 → 87,5 %, estudio 12,5 → 37,5 % (el 2026-11-17 eran 16 % → 60 % de Hit@1; subió al entender mejor la redacción de chat). Las preguntas y el glosario los escribió el equipo (primero las preguntas, después el glosario): el resultado muestra el sentido del efecto, no predice el acierto con los documentos y las preguntas reales. Sustituye a la cifra "4 % → 40 %" que citaba el diagrama on-premise, cuyo set nunca estuvo en el repo.
- **Preguntas de reporte con modelo y con catálogo descrito por IA** (2026-11-23, mismas 25 preguntas, sin glosario salvo donde se dice). Con modelo en el rol `fast`, la primera reformulación de `LlmQueryExpander` se mide contra el catálogo cuando la búsqueda cubre poco la pregunta (F22, F16); antes de ese cambio el modelo no movía la cifra (28 % con o sin él).

| Configuración | Hit@1 | Hit@3 |
|---|---|---|
| Determinista, solo catálogo | 28 % | 32 % |
| Determinista + glosario de prueba | 64 % | 64 % |
| Catálogo descrito por IA, sin modelo en la consulta | 40 % | — |
| Catálogo descrito por IA + glosario, sin modelo | 72 % | — |
| `nvidia/nemotron-3.5-bolt-e4b` (perfil `nvidia`) | 52 % | 56 % |
| `claude-sonnet-5-5` (perfil `claude`) | 68 % | 80 % |

  Con el perfil `claude`, el set de chat sigue en 97,8 % y 100 %, y el set base en 98,0 % y 98,0 %, con brechas correctas al 100 % en ambos. Los dos modelos se probaron sin Bedrock (HU-35); los sets los escribió el equipo.
- **Set de chat** (2026-11-23). `converdata eval discovery --root tests/fixtures/bancos --cases tests/fixtures/bancos/eval/chat.yaml` mide 67 preguntas de usuarios de
  negocio (frases largas, sin tildes, con erratas, términos de cálculo y de periodo, seguimientos). `EvalCase` admite `history` (preguntas anteriores),
  `expect_assistant` (tema fijo esperado) y `expect_rejected` (petición de escritura). Resultado (2026-11-23, última corrida): Hit@1 97,8 %, Hit@3 100 %, brechas 100 %, 0 fugas, 0 inventados,
  con un fallo abierto (L09; una corrida anterior del mismo día tenía cinco: F04, L09, X04, X05 y K03). Es un set del equipo, como los demás, y no entra a la compuerta `eval gate`: se corre aparte.
  Una pregunta de cifras (tipo F) se evalúa por la información que permite calcularla, no por el número: las cifras agregadas se verificaron contra SQL Server con
  datos ficticios (1 790 clientes con préstamo de 3 000; saldo de cartera 25 507 803,93; promedio desembolsado 14 566,69), no con este set.

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
2. `converdata metrics report` (hoy, `GET /admin/metrics`) produce todas las métricas de esta spec a partir de la auditoría, sin leer preguntas ni SQL.
3. `converdata eval discovery` falla (exit code ≠ 0) si Hit@3 baja más de 5 puntos respecto a la última ejecución aprobada (`--min-hit3`; la suite `calidad` de `converdata eval gate` lo comprueba además contra la línea base).
