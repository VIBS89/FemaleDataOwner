# PRD — Enterprise Data Discovery Agent

| | |
|---|---|
| **Producto** | Enterprise Data Discovery Agent (nombre técnico: ConverData) |
| **Cliente** | Gerencia de Datos, Banco Atlántida El Salvador |
| **Origen** | *Propuesta 1 — Agente de descubrimiento y conocimiento de datos corporativos* |
| **Estado** | Borrador para revisión · 2026-10-14 |
| **Fase** | Especificación y arquitectura terminadas; implementación sin iniciar |
| **Alcance de este documento** | Producto, requisitos, principios, contrato de respuesta, trazabilidad con la propuesta y catálogo de specs (sustituye a `features.md` y `propuesta-trazabilidad.md`) |
| **Documentos relacionados** | [specs](specs/) (catálogo en el anexo A) · [arquitectura on-premise](architecture/onpremise-architecture.html) · [arquitectura cloud native](architecture/cloud-native-architecture.html) |

---

## 1. Resumen
Un asistente conversacional que permite a cualquier colaborador de datos describir en lenguaje natural la información que necesita y recibir
en segundos una **lista priorizada de fuentes candidatas**: campo, tabla, base de datos, ambiente y servidor, con su descripción funcional,
las reglas de negocio que aplican, sus relaciones, sus responsables y un **nivel de confianza**. El agente razona sobre los metadatos de las
bases de datos y sobre el conocimiento hoy disperso (diccionarios, documentación, procesos ETL y la experiencia de los expertos), y convierte
cada respuesta de un experto en conocimiento reutilizable por toda la organización.

El producto tiene dos flujos sobre la misma plataforma (agentes CrewAI con Amazon Bedrock):
1. **DiscoverFlow (F22), el caso de uso principal**: el usuario describe el dato que necesita y recibe una lista priorizada de campos y
   tablas candidatas, con base de datos, ambiente, servidor, descripción funcional, reglas de negocio, relaciones, responsables y nivel
   de confianza. Razona sobre metadatos, diccionarios, documentación, ETL y conocimiento capturado de expertos (F23, F24). No ejecuta SQL.
2. **AskFlow (F3–F10, F20, F21), la evolución**: genera y valida T-SQL (o elige un stored procedure de una lista blanca),
   lo ejecuta **con los permisos del usuario** y devuelve resultados procesados, verificados y trazables. Corresponde a la visión
   futura "Recomendación y generación de SQL" de la propuesta.


## 2. Problema
La información del banco está distribuida en múltiples bases de datos, ambientes y plataformas. Encontrar la fuente correcta depende del
**conocimiento tribal** de expertos, dueños funcionales y analistas con experiencia, y de documentación parcial o desactualizada. Consecuencias:
- tiempo considerable dedicado a localizar información y retrasos en la fase de análisis de requerimientos;
- dependencia de personas específicas y cuellos de botella cuando no están disponibles;
- esfuerzos de investigación duplicados entre equipos;
- reprocesos cuando se elige una fuente incorrecta;
- pérdida de conocimiento cuando un colaborador cambia de rol o deja la organización.

Hoy **no existe medición** del tiempo de búsqueda; establecer esa línea base es parte del producto (§9).

## 3. Objetivos y no-objetivos
### Objetivos
| # | Objetivo | Medida (§9) |
|---|---|---|
| O1 | Reducir el tiempo para localizar y entender una fuente de datos | −50 % tiempo de localización |
| O2 | Reducir la dependencia de expertos | −30 % consultas a expertos |
| O3 | Acelerar el análisis de requerimientos | −20 % a −40 % |
| O4 | Reducir reprocesos por fuente incorrecta | −20 % |
| O5 | Capturar y preservar el conocimiento institucional | % de activos consultados con descripción revisada; golden discovery por semana |
| O6 | Fortalecer el gobierno de datos | Dominios con responsable asignado; brechas abiertas y cerradas |

### No-objetivos (v1)
- Ejecutar consultas o devolver datos de clientes en el piloto de descubrimiento (llega en la fase 1b; ver §10).
- Escribir o modificar datos en cualquier base.
- Ampliar los permisos de un usuario: nadie descubre ni consulta algo a lo que no tiene acceso.
- Sustituir un catálogo de datos corporativo completo (linaje extremo a extremo, calidad de datos).
- Plataformas distintas de SQL Server (data lakes, SaaS) en la v1.

## 4. Usuarios
| Persona | Necesidad principal | Ejemplo |
|---|---|---|
| **Ingeniero de datos** | Saber de qué tabla y ambiente extraer, cómo se carga y qué ETL la alimenta | "¿Qué proceso llena `DWH.dim.Cliente`?" |
| **Analista / desarrollador BI** | Encontrar el campo correcto y su regla de negocio para un reporte | "¿Dónde está la fecha de apertura de cuenta digital?" |
| **Científico de datos** | Descubrir variables disponibles para un modelo | "¿Qué datos tenemos del comportamiento en la app?" |
| **Product Owner / analista de negocio** | Entender qué significa un dato sin depender de TI | "¿Qué significa `EstadoCta = 'S'`?" |
| **Responsable de dominio (steward)** | Responder una vez y que la respuesta quede para todos | Revisar descripciones y contestar dudas escaladas |
| **Nuevo colaborador** | Entender el ecosistema de datos sin mentoría extensa | "¿Qué tablas hay de onboarding digital?" |
| **Administrador de datos / Plataformas** | Gestionar fuentes, dominios, permisos y métricas | Configurar ambientes, cargar diccionarios |

## 5. Experiencia de usuario
**Canal**: chat web corporativo (y herramienta MCP para otros agentes, como Claude Code). El usuario entra con su login SQL.

**Flujo principal**
1. El usuario escribe: *"Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital."*
2. El agente muestra el progreso (buscando en catálogo, diccionarios, documentos…) y responde en menos de 10 s:
```
Posibles coincidencias

1. ClientCode                                                  Confianza: 92 %
   Base de datos: VBank_ING · Tabla: dbo.Users · Ambiente: Producción · Servidor: SQL Producción Canales
   Descripción: Código que identifica a los clientes digitales registrados.  [revisada por Banca Digital]
   Regla: BR-ONB-004 · Se asigna al completar la verificación de identidad.
   Relacionadas: UserDevices (FK UserId) · DWH.dim.Cliente (ETL ONB_CargaUsuarios)
   [✔ Es este]  [✖ No es]  [Ver ficha]  [Ver relacionadas]

Alternativas: LegalClientId (71 %) — identificador legal del core · UserId (64 %) — usuario técnico de la app
```
3. El usuario confirma con **✔ Es este**; la confirmación fortalece la recomendación para los siguientes usuarios.
4. Si nada alcanza confianza suficiente, el agente lo dice y ofrece **Preguntar al responsable**; el steward responde y la respuesta queda
   como conocimiento revisado.

**Principios de UX**
- La fuente de cada descripción siempre es visible (revisada por humano, diccionario, documento o "sugerida por IA, sin revisar").
- Nunca se inventan objetos: todo lo mencionado existe en el catálogo.
- Diálogo iterativo: aclaraciones con botones y preguntas de seguimiento sugeridas.
- Español como idioma de interacción.

## 6. Requisitos funcionales
Prioridad: **P0** imprescindible para el piloto · **P1** necesario para producción · **P2** posterior.

### 6.1 Descubrimiento
| ID | Requisito | Prioridad | Spec |
|---|---|---|---|
| RF-01 | Interpretar preguntas en lenguaje natural y distinguir descubrimiento ("¿dónde está?") de consulta de datos ("¿cuánto?") | P0 | F3 |
| RF-02 | Devolver una lista priorizada de campos y tablas candidatas con BD, esquema, tabla, campo, tipo, ambiente y servidor (alias) | P0 | F22, F1 |
| RF-03 | Mostrar descripción funcional con su fuente | P0 | F22, F23 |
| RF-04 | Calcular y mostrar un nivel de confianza calibrado por candidato | P0 | F22 |
| RF-05 | Sugerir campos alternativos con la misma semántica | P0 | F22 |
| RF-06 | Mostrar relaciones: FKs, relaciones entre BDs y linaje ETL a un salto | P0 | F22, F19, F23 |
| RF-07 | Explicar reglas de negocio conocidas del activo | P0 | F23 |
| RF-08 | Mostrar responsables funcional y técnico del dominio | P0 | F24 |
| RF-09 | Agrupar el mismo objeto en varios ambientes y avisar si sus estructuras difieren | P1 | F1, F22 |
| RF-10 | Ficha completa de un activo (`/assets/{id}`) | P1 | F12 |
| RF-11 | Resumen de un dominio ("¿qué datos tenemos de X?") | P1 | F3, F22 |

### 6.2 Fuentes de conocimiento
| ID | Requisito | Prioridad | Spec |
|---|---|---|---|
| RF-20 | Extraer metadatos de SQL Server (tablas, columnas, FKs, vistas, SPs, descripciones) de todos los servidores y ambientes configurados | P0 | F1, F18 |
| RF-21 | Enriquecer con IA descripciones, sinónimos y dominios, marcados como no revisados | P0 | F1 |
| RF-22 | Ingerir diccionarios de datos (Excel/CSV) | P0 | F23 |
| RF-23 | Ingerir documentación (DOCX, PDF, Markdown, HTML; carpeta compartida o SharePoint) con redacción de datos personales | P0 | F23 |
| RF-24 | Extraer linaje de SSIS, SQL Agent, SPs y vistas | P1 | F23 |
| RF-25 | Gestionar reglas de negocio (manuales y sugeridas) | P0 | F23 |
| RF-26 | Detectar relaciones y entidades de negocio entre BDs | P1 | F19 |
| RF-27 | Interfaz para conectar otras plataformas (DWH, data lake) | P2 | F23 |

### 6.3 Conocimiento institucional y gobierno
| ID | Requisito | Prioridad | Spec |
|---|---|---|---|
| RF-30 | Confirmar o rechazar candidatos y convertir las confirmaciones en conocimiento reutilizable | P0 | F24 |
| RF-31 | Escalar dudas sin respuesta al responsable del dominio, con notificación | P0 | F24 |
| RF-32 | Vista de curación para stewards: revisar descripciones, reglas, vínculos y conflictos | P0 | F24 |
| RF-33 | Reporte de brechas de conocimiento | P1 | F24 |
| RF-34 | Historial de cambios del conocimiento (quién y cuándo) | P1 | F24, OP-02 |

### 6.4 Consulta de datos (fase 1b, visión "Recomendación y generación de SQL")
| ID | Requisito | Prioridad | Spec |
|---|---|---|---|
| RF-40 | Generar, validar y ejecutar T-SQL de solo lectura con los permisos del usuario | P2 | F4–F10 |
| RF-41 | Usar métricas certificadas y consultas verificadas | P2 | F21 |
| RF-42 | Análisis comparativo, de causa raíz y exploratorio | P2 | F20 |

### 6.5 Interfaces y medición
| ID | Requisito | Prioridad | Spec |
|---|---|---|---|
| RF-50 | Chat web con tarjetas de candidatos y botones de confirmación | P0 | F12 |
| RF-51 | API REST (`/discover`, `/assets`, `/curation`, `/metrics`) | P0 | F12 |
| RF-52 | Servidor MCP para otros agentes (`discover`, `get_asset`, `get_lineage`…) | P1 | F12 |
| RF-53 | Auditoría completa de preguntas, candidatos y confirmaciones | P0 | F11 |
| RF-54 | Reporte de métricas de negocio, adopción y calidad | P0 | F25 |
| RF-55 | Set de evaluación automatizado con alerta de regresión | P0 | F25 |

## 7. Requisitos no funcionales
| Área | Requisito | Spec |
|---|---|---|
| **Permisos** | Cada usuario solo descubre y consulta lo que su login SQL puede leer, incluidos metadatos, relaciones, reglas y documentos. Si nada visible responde, no se revela la existencia de otros objetos | F14 |
| **Residencia de datos** | Ningún dato de cliente se persiste fuera de la red del banco; el catálogo no contiene valores; los documentos se indexan con PII redactada | F17, F23 |
| **Seguridad** | Credenciales cifradas fuera del alcance del LLM; TLS en todas las conexiones; login de metadatos de solo lectura; sin SQL libre en las herramientas de metadatos | F14, F18 |
| **Rendimiento** | Descubrimiento p50 < 5 s, p95 < 10 s | F22 |
| **Calidad** | Hit@3 ≥ 85 %, Hit@1 ≥ 65 %; candidatos con confianza ≥ 0.8 correctos ≥ 85 % | F25 |
| **Trazabilidad** | Toda respuesta auditada; logs sin contenido | F11 |
| **Operación** | Despliegue on-premise en el stack Microsoft (Windows Server, IIS, SQL Server 2025, SQL Server Agent); camino a cloud native en AWS sin cambiar la lógica | OP-01, CN-01 |
| **IA** | Amazon Bedrock por rol, sin logging de invocaciones; modelos configurables sin cambios de código | F16 |
| **Licencias** | Componentes propios bajo Apache-2.0; sin dependencias AGPL | F18 |
| **Idioma** | Español | — |

## 8. Arquitectura (resumen)
- **Orquestación**: agentes CrewAI en flujos deterministas: DiscoverFlow (descubrimiento) y AskFlow (consulta).
- **LLM y embeddings**: Amazon Bedrock (Claude para razonar, un modelo distinto como juez, Cohere multilingüe para embeddings).
- **Memoria**: on-premise en SQL Server 2025 (tipo `VECTOR` + Full-Text, búsqueda híbrida; tablas de grafo para relaciones;
  tablas temporales para el historial); en la nube, OpenSearch Serverless.
- **Metadatos**: `converdata-discovery`, servidor MCP propio de solo lectura.
- **Interfaces**: Chainlit + FastAPI detrás de IIS; MCP en `/mcp`.
- **Despliegue MVP**: un Windows Server de aplicación + BD `ConverData`; Bedrock como único servicio externo.

Detalle en los diagramas de `docs/architecture/` y en las specs OP-01 a OP-06 / CN-01 a CN-06.

### 8.1 Principios de diseño
1. **Determinismo en la orquestación**: un CrewAI Flow con pasos fijos. Los agentes razonan dentro de cada paso, pero no deciden saltarse pasos.
2. **SQL Server es la barrera de seguridad**: cada consulta corre con el login del usuario. Los guardrails de la aplicación son defensa en profundidad.
3. **Nada se ejecuta sin validar**: validación estática, compilación (NOEXEC) y plan estimado (SHOWPLAN) antes de ejecutar.
4. **Toda respuesta es auditable**: SQL, tablas, supuestos, validaciones y confidence acompañan a cada dato.
5. **Memoria revisable por humanos**: el catálogo vive en YAML versionable; el índice vectorial es derivado.
6. **Cero persistencia de datos fuera de la red del cliente**: la nube procesa y muestra; datos, preguntas, SQL y auditoría persisten solo on-premise (F17).
7. **Misma lógica, dos despliegues**: los agentes, las herramientas MCP y el validador son idénticos en cloud native y on-premise; solo cambia la infraestructura.
8. **Descubrir antes que consultar**: ante la duda, el router elige el DiscoverFlow, que no toca datos (F3, F22).
9. **El conocimiento se captura con el uso**: cada confirmación de un usuario o respuesta de un responsable se convierte en conocimiento revisado y reutilizable (F24).
10. **Cada recomendación muestra su evidencia**: fuente de la descripción (humana, diccionario, documento o IA sin revisar) y por qué se recomienda.
11. **El éxito se mide contra una línea base**: las métricas de la propuesta se instrumentan desde el día uno (F25).

### 8.2 Despliegues
| Despliegue | Spec principal | Diagrama | Cuándo |
|---|---|---|---|
| **On-premise** | [OP-01](specs/on-premise/OP-01-despliegue-local.md) | `docs/architecture/onpremise-architecture.html` | Primero: MVP para validar la solución sin infraestructura cloud nueva (solo Bedrock) |
| **Cloud native** | [CN-01](specs/cloud-native/CN-01-despliegue-aws.md) | `docs/architecture/cloud-native-architecture.html` | Después del MVP, si se decide invertir en AWS |

Los permisos heredados se explican en `docs/architecture/permisos-heredados.html` (F14) y aplican igual a los dos despliegues.

### 8.3 Contrato de respuesta: `AnswerEnvelope`
Lo devuelven `/ask`, `/discover` y la herramienta MCP `ask`/`discover` (F12).
```json
{
  "trace_id": "uuid",
  "status": "ok | needs_clarification | rejected | error",
  "answer_text": "Resumen en español",
  "clarification": {"question": "...", "options": ["..."]},
  "data": {"columns": [{"name": "...", "type": "..."}], "rows": [[...]], "row_count": 0, "truncated": false},
  "sql": "SELECT TOP (1000) ...",
  "procedure": {"name": "dbo.usp_x", "params": {}},
  "databases": ["Ventas"],
  "tables_used": ["Ventas.dbo.Pedido"],
  "assumptions": ["'último trimestre' = 2026-Q3"],
  "validation": {
    "static": "pass",
    "compile": "pass",
    "plan": {"estimated_cost": 0.42, "estimated_rows": 1200},
    "checks": [{"name": "fan_out", "status": "pass", "detail": "..."}]
  },
  "confidence": 0.87,
  "chart_spec": {"type": "bar", "x": "...", "y": "..."},
  "discovery": {"candidates": [], "alternatives": [], "related": [], "knowledge_gap": false},
  "timings_ms": {"total": 0, "llm": 0, "db": 0}
}
```
- `flow`: `discover` | `ask` (campo adicional). En `discover` se llena `discovery` (estructura completa en [F22](specs/comun/F22-discovery-flow.md))
  y quedan vacíos `data`, `sql`, `validation` y `chart_spec`; en `ask` es al revés.


## 9. Métricas de éxito
| Métrica | Línea base | Objetivo | Cómo se mide |
|---|---|---|---|
| Tiempo de localización de fuentes | Estudio de tiempos (semana 0–1) | −50 % | Pregunta → "✔ Es este" |
| Consultas a expertos | Encuesta a expertos + canal de consultas | −30 % | Escalamientos + encuesta |
| Tiempo de análisis de requerimientos | Gestor de requerimientos, últimos 3 meses | −20 % a −40 % | Etiqueta `usa-discovery-agent` |
| Reprocesos por fuente incorrecta | Etiqueta `reproceso-fuente` | −20 % | Etiqueta + rechazos posteriores |
| Adopción | — | ≥ 70 % de usuarios piloto activos 2 de 4 semanas | Auditoría |
| Conocimiento documentado | % actual de descripciones revisadas | Crecimiento semanal | Catálogo |
| Calidad del agente | — | Hit@3 ≥ 85 % · calibración ≥ 85 % · 0 objetos inventados | Set de evaluación |

Los porcentajes son metas iniciales sujetas a validación en el piloto. Detalle en [F25](specs/comun/F25-success-metrics.md).

## 10. Alcance y fases
| Fase | Contenido | Criterio de salida |
|---|---|---|
| **0. Preparación** (semanas 0–1) | Línea base; acceso a fuentes; responsables del dominio piloto; servidor y BD `ConverData` | Línea base firmada |
| **1a. Piloto de descubrimiento** (semanas 1–8) | RF P0 de §6.1–6.3 y 6.5 sobre el dominio **clientes / onboarding digital**, producción y QA; 10–15 usuarios | D1–D7 de OP-01 |
| **1b. Consulta de datos** | AskFlow, métricas certificadas y análisis (RF-40 a RF-42) | Criterios 1–7 de OP-01 |
| **2. Escalamiento** | Más dominios, RF P1, cloud native o alta disponibilidad on-premise | Decisión de la Gerencia de Datos |
| **Visión** | Linaje automatizado extremo a extremo, generación de glosarios, reglas de calidad, análisis de impacto, multiplataforma | — |

## 11. Dependencias y supuestos
- Logins SQL por usuario disponibles para los participantes del piloto (Windows/AD con Kerberos es una evolución posterior).
- Login técnico de metadatos con `VIEW DEFINITION` y lectura de SSISDB y msdb.
- Acceso a los diccionarios y a la documentación del dominio piloto (carpeta compartida o SharePoint).
- Cuenta de AWS con Bedrock habilitado (modelos Claude, Nova o Llama, Cohere Embed) e IAM Roles Anywhere.
- Windows Server para la aplicación y una instancia SQL Server 2025 para la BD `ConverData`.
- Un steward funcional y uno técnico asignados al dominio piloto con tiempo para curación (semanas 2–3).
- Aprobación de Seguridad de la Información para enviar metadatos y preguntas a Bedrock (sin almacenamiento).

## 12. Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Descripciones generadas por IA de baja calidad | Recomendaciones erróneas, pérdida de confianza | Fuente visible, tope de confianza 0.6 sin evidencia humana, curación inicial de los 100 activos más relevantes |
| Documentos con datos personales | Incumplimiento de residencia y privacidad | Redacción con Presidio y patrones locales; descarte de fragmentos con alta densidad de PII |
| Permisos heredados limitan la "democratización" | Usuarios sin acceso no descubren datos que existen | Escalamiento al responsable sin revelar nombres; revisar la política tras el piloto |
| Sin línea base | No se pueden demostrar los objetivos | Semana 0–1 dedicada a medirla |
| Baja adopción | No se capturan confirmaciones | Dominio piloto con dolor real, campeones por equipo, métricas semanales visibles |
| Stewards sin tiempo | Brechas sin cerrar | Asignación formal de la Gerencia de Datos; cola priorizada por demanda |
| Dependencia de un proveedor de LLM | Disponibilidad o coste | Modelos configurables por rol; NIM como alternativa con acuerdo de procesamiento |

## 13. Decisiones y preguntas abiertas
### Decisiones tomadas
1. **Visibilidad (decidido, 2026-10-14)**: el usuario solo ve información a la que tiene acceso, también en el descubrimiento (metadatos,
   relaciones, reglas, documentos). Consecuencia: quien no tiene acceso a una BD no descubrirá que existe; el agente le ofrece escalar al
   responsable sin revelar nombres. Esto limita en parte la "democratización" de la propuesta a favor de la seguridad.
2. **Autenticación (decidido, 2026-10-14)**: logins SQL por usuario, que también calculan la visibilidad del descubrimiento (OP-03).
   Windows/AD con SSO y delegación restringida de Kerberos queda como evolución, sujeta a una prueba de concepto (OP-03).
3. **Nombre**: la propuesta usa "Enterprise Data Discovery Agent"; ConverData es el nombre técnico del proyecto.

### Preguntas abiertas
1. ¿Dónde viven exactamente los diccionarios y la documentación del dominio piloto, y quién da acceso?
2. ¿Qué gestor de requerimientos y canal de consultas se usan para la línea base?
3. ¿Qué servidores y ambientes entran en el piloto?
4. ¿Qué canal de notificación prefieren los stewards (correo o Teams)?
5. ¿Se mantiene la política de permisos heredados también para metadatos después del piloto?
6. ¿Dónde viven los diccionarios y la documentación (carpeta compartida, SharePoint, Confluence) y son accesibles SSISDB y msdb con un login técnico?

## 14. Trazabilidad con la propuesta
Fuente: *Propuesta 1 — Agente de descubrimiento y conocimiento de datos corporativos* (Gerencia de Datos, Banco Atlántida El Salvador).

| Sección de la propuesta | Requisitos del PRD |
|---|---|
| 3. Elementos que el agente identifica (tabla, campo, BD, ambiente, servidor, descripción, confianza, relaciones) | RF-02 a RF-08 |
| 5. Experiencia conversacional, tablas relacionadas, definiciones, relaciones, reglas, alternativas | §5, RF-05 a RF-07 |
| 6. Fuentes: metadatos, documentación, ETL, diccionarios, conocimiento institucional, búsqueda semántica | RF-20 a RF-27, RF-30 a RF-34 |
| 4. Métricas y validación mediante piloto | §9, §10 |
| Visión futura: SQL, linaje, glosarios, brechas, multiplataforma | §10 (fases 1b, 2 y visión) |
| Democratización del conocimiento | Parcial: limitada por la decisión de permisos heredados (§13) |

### Hallazgo de la revisión (2026-10-14)
Las specs originales describían sobre todo un **agente de texto a SQL**: pregunta → SQL validado → ejecución → resultados. La propuesta pide
otra cosa como producto principal: un **agente de descubrimiento** que responda *dónde está el dato, qué significa, qué reglas aplican, con
qué se relaciona y cuánta confianza merece*, razonando sobre metadatos **y** conocimiento institucional (diccionarios, documentación, ETL,
expertos). La generación de SQL aparece en la propuesta como **visión futura**.

Las specs ya tenían buena base para eso (catálogo, memoria semántica, glosario, permisos, auditoría y residencia de datos), pero faltaban el
flujo de descubrimiento, su contrato de respuesta, las fuentes de conocimiento no estructurales, la captura del conocimiento de expertos,
los ambientes y servidores, y la medición de las métricas de la propuesta. Esta revisión agrega F22–F25 y ajusta F1–F3, F11, F12, F14 y OP-01.

Leyenda: ✅ cubierto · ⚠️ parcial · ❌ no cubierto

### 14.1 Lo que el agente debe identificar (sección 3)
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

### 14.2 Experiencia de usuario (sección 5)
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

### 14.3 Fuentes de conocimiento (sección 6 y "¿Por qué es innovador?")
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

### 14.4 Beneficios e impacto
| Beneficio | Cómo lo soporta la solución | Dónde |
|---|---|---|
| Menor dependencia de expertos | Escalamiento único al responsable; la respuesta se reutiliza para todos | F24 |
| Reutilización y preservación del conocimiento | Respuestas de expertos → descripciones `human`, reglas, golden discovery versionados | F24 |
| Reducción de retrabajos | Evidencia visible, reglas y avisos de *drift* entre ambientes | F22 |
| Gobierno de datos | Responsables por dominio, vista de curación, reporte de brechas | F24 |
| Incorporación de nuevos colaboradores | Autoservicio + métrica por cohorte | F25 |
| Acceso para colaboradores autorizados | Cada usuario descubre solo lo que su login puede leer (permisos heredados, también para metadatos) | F14 |

### 14.5 Métricas (sección 4)
| Métrica | Antes | Ahora | Dónde |
|---|---|---|---|
| Tiempo de análisis de requerimientos (−20 % a −40 %) | ❌ | ✅ línea base y medición en el gestor de requerimientos | F25 |
| Consultas a expertos (−30 %) | ❌ | ✅ encuesta + escalamientos | F25 |
| Tiempo de localización de fuentes (−50 %) | ❌ | ✅ estudio de tiempos + `time_to_verdict_ms` | F11, F25 |
| Reprocesos por fuente incorrecta (−20 %) | ❌ | ✅ etiqueta + rechazos posteriores | F25 |
| Adopción, activos documentados, duplicidad, gobierno | ❌ | ✅ | F25 |
| Criterios de salida del MVP | ⚠️ medían precisión de SQL, no descubrimiento | ✅ fase 1a de descubrimiento con Hit@k, calibración y KPIs | OP-01, F25 |

### 14.6 Visión futura de la propuesta
| Capacidad futura | Estado en ConverData |
|---|---|
| Descubrimiento automatizado de linaje | Base en F23 (un salto, nivel de tabla) y F19 (relaciones entre BDs) |
| Recomendación y generación de SQL | Ya especificado: AskFlow F4–F10, capa semántica F21, motor de análisis F20 (fase 1b) |
| Generación de glosarios de negocio | Sugerencias de glosario y reglas con `reviewed: false` (F2, F23) |
| Recomendaciones de reglas de calidad | No cubierto (fase posterior) |
| Análisis de impacto | Parcial: linaje descendente de F23 + dependencias de F19 |
| Identificación de brechas de conocimiento | Cubierto en F24 (reporte de brechas) |
| Descubrimiento multiplataforma | Interfaz `MetadataConnector` (F23); conectores pendientes |

### 14.7 Cobertura por despliegue (revisión del 2026-10-14)
| Capacidad de la propuesta | Común | On-premise (Microsoft) | Cloud native (AWS) |
|---|---|---|---|
| Flujo de descubrimiento y respuesta con candidatos | F3, F22 | OP-01 (fase 1a), OP-04 | CN-01, CN-04 |
| Ambientes y servidores | F1 | OP-02 (`catalog`) | CN-02 |
| Diccionarios, documentos, ETL y reglas | F23 | OP-02 (`knowledge`, Presidio, job de SQL Agent) | CN-02 (tarea ECS, Presidio, S3 `_knowledge/`) |
| Responsables, escalamiento y curación | F24 | OP-02 (`curation`), OP-04 (Database Mail o Teams) | CN-02 (`owners.yaml`), CN-04 (Teams o correo) |
| Auditoría y métricas | F11, F25 | OP-05 (vistas y evaluación semanal) | CN-05 (vistas en `ConverData_Audit`) |
| Residencia de documentos y preguntas escaladas | F17, F23 | OP-06 | CN-06 |
| Permisos heredados también en el descubrimiento | F14 | OP-03 | CN-03 |

Antes de esta revisión, cloud native no cubría F22–F25 y on-premise no tenía dónde guardar el conocimiento ni la curación.
Pendiente: actualizar los diagramas de arquitectura (el on-premise ya muestra "Fuentes de conocimiento"; el cloud native, no).

## Anexo A. Catálogo de specs
```
docs/specs/
├─ comun/          Lógica de la solución, idéntica en ambos despliegues (F1–F25)
├─ cloud-native/   Despliegue en AWS con Bedrock AgentCore (CN-01 a CN-06)
└─ on-premise/     Despliegue local en la red corporativa; sirve también como MVP (OP-01 a OP-06)
```

| ID | Feature | Spec | Implementación cloud native | Implementación on-premise |
|---|---|---|---|---|
| F1 | Catalog Builder (ingesta y mapeo) | [F01](specs/comun/F01-catalog-builder.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) |
| F2 | Memoria semántica (`VectorStore`) | [F02](specs/comun/F02-semantic-memory.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) OpenSearch | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) SQL Server 2025 (`VECTOR` + Full-Text) |
| F3 | Intent & Router | [F03](specs/comun/F03-intent-router.md) | = | = |
| F4 | Schema Linking | [F04](specs/comun/F04-schema-linking.md) | = | = |
| F5 | Value Resolution (en vivo) | [F05](specs/comun/F05-value-resolution.md) | = | = |
| F6 | Planner T-SQL / SP | [F06](specs/comun/F06-planner.md) | = | = |
| F7 | Validator | [F07](specs/comun/F07-validator.md) | = | = |
| F8 | Executor | [F08](specs/comun/F08-executor.md) | = | = |
| F9 | Result Verifier | [F09](specs/comun/F09-result-verifier.md) | = | = |
| F10 | Analyst | [F10](specs/comun/F10-analyst.md) | = | = |
| F11 | Auditoría | [F11](specs/comun/F11-audit.md) | [CN-05](specs/cloud-native/CN-05-auditoria-observabilidad.md) `ConverData_Audit` on-prem | [OP-05](specs/on-premise/OP-05-auditoria-observabilidad.md) esquema `audit` de la BD `ConverData` |
| F12 | Interfaces (API, chat, MCP) | [F12](specs/comun/F12-interfaces.md) | [CN-04](specs/cloud-native/CN-04-interfaces.md) | [OP-04](specs/on-premise/OP-04-interfaces.md) |
| F13 | Arquitectura documentada (Archify) | [F13](specs/comun/F13-architecture-docs.md) | = | = |
| F14 | Identidad y permisos heredados | [F14](specs/comun/F14-identity.md) | [CN-03](specs/cloud-native/CN-03-identidad.md) Cognito + Secrets Manager | [OP-03](specs/on-premise/OP-03-identidad.md) SessionVault |
| F16 | Proveedores LLM: Bedrock (+ NIM opcional) | [F16](specs/comun/F16-llm-providers.md) | = | = |
| F17 | Residencia de datos | [F17](specs/comun/F17-data-residency.md) | [CN-06](specs/cloud-native/CN-06-residencia-datos.md) | [OP-06](specs/on-premise/OP-06-residencia-datos.md) |
| F18 | `converdata-discovery`: MCP propio de metadatos (Apache-2.0, sustituye a sql-to-mcp) | [F18](specs/comun/F18-discovery-mcp.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) ECS privado | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) contenedor |
| F19 | Descubrimiento entre múltiples BDs (grafo del patrimonio, joins entre BDs, planes federados) | [F19](specs/comun/F19-multi-db-discovery.md) | = | = |
| F20 | Motor de análisis (compare, explain, explore, forecast, sandbox) | [F20](specs/comun/F20-analysis-engine.md) | = | = |
| F21 | Capa semántica (métricas certificadas, consultas verificadas) | [F21](specs/comun/F21-semantic-layer.md) | = | = |
| **F22** | **DiscoverFlow: candidatos con ubicación, descripción, reglas, relaciones y confianza** | [F22](specs/comun/F22-discovery-flow.md) | = | = |
| F23 | Fuentes de conocimiento: diccionarios, documentación, ETL (SSIS, SQL Agent) y reglas de negocio | [F23](specs/comun/F23-knowledge-sources.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) |
| F24 | Curación y captura del conocimiento institucional (responsables, escalamiento, brechas) | [F24](specs/comun/F24-knowledge-curation.md) | = | = |
| F25 | Métricas de éxito, línea base y piloto | [F25](specs/comun/F25-success-metrics.md) | = | = |

"=" significa que no hay diferencias entre entornos.

## Anexo B. Glosario
- **Catálogo**: descripción de BDs, esquemas, tablas, columnas, FKs y SPs, **sin valores de datos** (`**/*.yaml`).
- **Golden SQL**: pares pregunta→SQL validados por un humano. El original vive en la auditoría on-prem; en el índice solo su plantilla anonimizada.
- **Visibilidad**: conjunto de objetos que el login del usuario puede leer o ejecutar, según SQL Server.
- **Confidence**: puntuación de 0 a 1. En el AskFlow combina los chequeos deterministas con el veredicto del LLM-judge (F9); en el DiscoverFlow combina relevancia, evidencia, confirmaciones y acuerdo entre fuentes (F22).
- **`asset_key`**: identificador lógico de un objeto (`db.schema.objeto[.columna]`) que agrupa sus copias en todos los ambientes (F1).
- **Golden discovery**: pregunta de descubrimiento (plantilla anonimizada) confirmada por usuarios o por un responsable, ligada a los activos correctos (F24).
- **Steward / responsable**: grupo funcional o técnico dueño de un dominio de datos (`config/owners.yaml`, F24).
- **Brecha de conocimiento**: pregunta sin candidato con confianza suficiente, o activo muy consultado sin descripción revisada (F24).
