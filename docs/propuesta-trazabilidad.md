# Trazabilidad: Propuesta "Enterprise Data Discovery Agent" → ConverData

Fuente: *Propuesta 1 — Agente de descubrimiento y conocimiento de datos corporativos* (Gerencia de Datos, Banco Atlántida El Salvador).
Revisión del 2026-10-14 sobre las specs del commit `7ec2300`, más las mejoras de esta revisión.

## Hallazgo principal
Las specs originales describían sobre todo un **agente de texto a SQL**: pregunta → SQL validado → ejecución → resultados. La propuesta pide
otra cosa como producto principal: un **agente de descubrimiento** que responda *dónde está el dato, qué significa, qué reglas aplican, con
qué se relaciona y cuánta confianza merece*, razonando sobre metadatos **y** conocimiento institucional (diccionarios, documentación, ETL,
expertos). La generación de SQL aparece en la propuesta como **visión futura**.

Las specs ya tenían buena base para eso (catálogo, memoria semántica, glosario, permisos, auditoría y residencia de datos), pero faltaban el
flujo de descubrimiento, su contrato de respuesta, las fuentes de conocimiento no estructurales, la captura del conocimiento de expertos,
los ambientes y servidores, y la medición de las métricas de la propuesta. Esta revisión agrega F22–F25 y ajusta F1–F3, F11, F12, F14 y OP-01.

Leyenda: ✅ cubierto · ⚠️ parcial · ❌ no cubierto

## 1. Lo que el agente debe identificar (sección 3)
| Requisito | Antes | Ahora | Dónde |
|---|---|---|---|
| Tabla candidata | ⚠️ solo internamente (schema linking para generar SQL) | ✅ lista priorizada para el usuario | F22 |
| Campo candidato | ⚠️ ídem | ✅ candidatos a nivel columna, más alternativas | F22 |
| Base de datos | ✅ | ✅ | F1, F22 |
| Ambiente | ❌ no modelado | ✅ `environment` por servidor, `asset_key` lógico entre ambientes, aviso de *drift* | F1, F22 |
| Servidor | ⚠️ en el id, nunca mostrado | ✅ alias mostrable, sin exponer el host | F1, F22 |
| Descripción funcional | ⚠️ generada por LLM o `MS_Description` | ✅ más diccionarios, documentos y expertos, con la fuente visible | F1, F23, F24 |
| Nivel de confianza de la recomendación | ⚠️ solo para resultados de SQL | ✅ confianza de descubrimiento calibrada | F22, F25 |
| Relaciones con otras entidades | ⚠️ FKs para joins | ✅ FKs, relaciones entre BDs, linaje ETL e indicadores | F19, F22, F23 |

## 2. Experiencia de usuario (sección 5)
| Requisito | Antes | Ahora | Dónde |
|---|---|---|---|
| Chat en lenguaje natural | ✅ Chainlit | ✅ | F12 |
| Ejemplo "identificador único del cliente en onboarding digital" | ❌ se habría intentado responder con SQL | ✅ criterio de aceptación explícito | F3, F22 |
| Mostrar tablas relacionadas | ⚠️ | ✅ | F22 |
| Presentar definiciones funcionales | ⚠️ | ✅ | F22, F23 |
| Mostrar relaciones entre entidades | ⚠️ | ✅ | F19, F22 |
| Explicar reglas de negocio conocidas | ❌ | ✅ colección `business_rules` | F23 |
| Sugerir campos alternativos | ❌ | ✅ `alternatives` | F22 |
| Respuesta en segundos | ⚠️ p95 40 s (flujo SQL) | ✅ p95 < 10 s (sin ejecución) | F22 |

## 3. Fuentes de conocimiento (sección 6 y "¿Por qué es innovador?")
| Fuente | Antes | Ahora | Dónde |
|---|---|---|---|
| Metadatos de bases de datos | ✅ SQL Server | ✅ | F1, F18 |
| Data warehouses y data lakes | ⚠️ solo si son SQL Server | ⚠️ interfaz `MetadataConnector`; otros conectores en fases posteriores | F23 |
| Documentación técnica (especificaciones, diagramas) | ❌ | ✅ con redacción de PII | F23 |
| Conocimiento ETL (lógica de transformación y flujos) | ❌ | ✅ SSIS, SQL Agent, SPs y vistas a nivel de tabla | F23 |
| Diccionarios y glosarios de datos | ⚠️ solo glosario manual | ✅ diccionarios Excel/CSV + glosario | F2, F23 |
| Conocimiento institucional (interacciones y expertos) | ⚠️ golden SQL a partir de 👍 | ✅ confirmaciones, escalamiento a responsables, golden discovery | F24 |
| Búsqueda semántica | ✅ | ✅ híbrida (semántica + léxica) | F2 |
| Diálogo y refinamiento iterativo | ✅ historial y aclaraciones | ✅ | F3 |

## 4. Beneficios e impacto
| Beneficio | Cómo lo soporta la solución | Dónde |
|---|---|---|
| Menor dependencia de expertos | Escalamiento único al responsable; la respuesta se reutiliza para todos | F24 |
| Reutilización y preservación del conocimiento | Respuestas de expertos → descripciones `human`, reglas, golden discovery versionados | F24 |
| Reducción de retrabajos | Evidencia visible, reglas y avisos de *drift* entre ambientes | F22 |
| Gobierno de datos | Responsables por dominio, vista de curación, reporte de brechas | F24 |
| Incorporación de nuevos colaboradores | Autoservicio + métrica por cohorte | F25 |
| Acceso para colaboradores autorizados | Cada usuario descubre solo lo que su login puede leer (permisos heredados, también para metadatos) | F14 |

## 5. Métricas (sección 4)
| Métrica | Antes | Ahora | Dónde |
|---|---|---|---|
| Tiempo de análisis de requerimientos (−20 % a −40 %) | ❌ | ✅ línea base y medición en el gestor de requerimientos | F25 |
| Consultas a expertos (−30 %) | ❌ | ✅ encuesta + escalamientos | F25 |
| Tiempo de localización de fuentes (−50 %) | ❌ | ✅ estudio de tiempos + `time_to_verdict_ms` | F11, F25 |
| Reprocesos por fuente incorrecta (−20 %) | ❌ | ✅ etiqueta + rechazos posteriores | F25 |
| Adopción, activos documentados, duplicidad, gobierno | ❌ | ✅ | F25 |
| Criterios de salida del MVP | ⚠️ medían precisión de SQL, no descubrimiento | ✅ fase 1a de descubrimiento con Hit@k, calibración y KPIs | OP-01, F25 |

## 6. Visión futura de la propuesta
| Capacidad futura | Estado en ConverData |
|---|---|
| Descubrimiento automatizado de linaje | Base en F23 (un salto, nivel de tabla) y F19 (relaciones entre BDs) |
| Recomendación y generación de SQL | Ya especificado: AskFlow F4–F10, capa semántica F21, motor de análisis F20 (fase 1b) |
| Generación de glosarios de negocio | Sugerencias de glosario y reglas con `reviewed: false` (F2, F23) |
| Recomendaciones de reglas de calidad | No cubierto (fase posterior) |
| Análisis de impacto | Parcial: linaje descendente de F23 + dependencias de F19 |
| Identificación de brechas de conocimiento | Cubierto en F24 (reporte de brechas) |
| Descubrimiento multiplataforma | Interfaz `MetadataConnector` (F23); conectores pendientes |

## Decisiones abiertas y riesgos
1. **Visibilidad (decidido, 2026-10-14)**: el usuario solo ve información a la que tiene acceso, también en el descubrimiento (metadatos,
   relaciones, reglas, documentos). Consecuencia: quien no tiene acceso a una BD no descubrirá que existe; el agente le ofrece escalar al
   responsable sin revelar nombres. Esto limita en parte la "democratización" de la propuesta a favor de la seguridad.
2. **Autenticación**: las specs asumen login SQL por usuario, que ahora también se necesita para descubrir. Si el banco usa autenticación de
   Windows/AD, hay que definir delegación Kerberos o el mapeo del usuario del IdP a su login.
3. **Disponibilidad de fuentes**: hay que confirmar dónde viven los diccionarios y la documentación (carpeta compartida, SharePoint,
   Confluence) y si SSISDB y msdb son accesibles con un login técnico.
4. **Línea base**: sin las mediciones de la semana 0–1 no se pueden demostrar los porcentajes de la propuesta.
5. **Nombre**: la propuesta usa "Enterprise Data Discovery Agent"; ConverData es el nombre técnico del proyecto.
