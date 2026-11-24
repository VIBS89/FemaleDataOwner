# PRD — Enterprise Data Discovery Agent

| | |
|---|---|
| **Producto** | Enterprise Data Discovery Agent (nombre técnico: DiscoveryDataAgent) |
| **Cliente** | Gerencia de Datos, Banco Atlántida El Salvador |
| **Origen** | *Propuesta 1 — Agente de descubrimiento y conocimiento de datos corporativos* |
| **Estado** | Revisado el 2026-11-23: primer corte de cifras agregadas del AskFlow, apagado por defecto (§13, decisión 17). Antes, el 2026-11-16: arquitectura simplificada (§13, decisiones 9–16) |
| **Fase** | Fase 1a on-premise en desarrollo: descubrimiento (con chat para usuarios de negocio), API, web y MCP construidos y medidos; la BD `DiscoveryDataAgent` ya existe (`db/discovery_data_agent/`); faltan Bedrock y la instalación en el servidor del piloto ([plan](PLAN-desarrollo.md), [backlog](backlog/on-premise.md)). De la fase 1b existe solo el primer corte de totales (§6.4, decisión 17); el resto sigue sin construir |
| **Alcance de este documento** | Producto, requisitos, principios, contrato de respuesta, trazabilidad con la propuesta y catálogo de specs (sustituye a `features.md` y `propuesta-trazabilidad.md`) |
| **Documentos relacionados** | [specs](specs/) (catálogo en el anexo A) · [arquitectura on-premise](architecture/onpremise-architecture.html) · [arquitectura cloud native](architecture/cloud-native-architecture.html) · [capas del backend](architecture/capas-backend.md) · [calidad bancaria](calidad-bancaria.md) · [plan de desarrollo](PLAN-desarrollo.md) · [backlog on-premise](backlog/on-premise.md) |

---

## 1. Resumen
Un asistente conversacional que permite a cualquier colaborador de datos describir en lenguaje natural la información que necesita y recibir
en segundos una **lista priorizada de fuentes candidatas**: campo, tabla, base de datos, ambiente y servidor, con su descripción funcional,
las reglas de negocio que aplican, sus relaciones, sus responsables y un **nivel de confianza**. El agente razona sobre los metadatos de las
bases de datos y sobre el conocimiento hoy disperso (diccionarios, documentación, procesos ETL y la experiencia de los expertos), y convierte
cada respuesta de un experto en conocimiento reutilizable por toda la organización.

El producto tiene dos flujos sobre la misma plataforma (grafos de LangGraph servidos por FastAPI, con Amazon Bedrock como LLM):
1. **DiscoverFlow (F22), el caso de uso principal**: el usuario describe el dato que necesita y recibe una lista priorizada de campos y
   tablas candidatas, con base de datos, ambiente, servidor, descripción funcional, reglas de negocio, relaciones, responsables y nivel
   de confianza. Razona sobre metadatos, diccionarios, documentación, ETL y conocimiento capturado de expertos (F23, F24). No ejecuta SQL,
   salvo el primer corte de cifras agregadas, apagado por defecto (más abajo y §13, decisión 17). Es también el chat de los usuarios de
   negocio: responde cortesía y preguntas sobre el propio asistente con textos fijos, entiende seguimientos con el historial de la conversación y
   ofrece aclarar, sin bloquear la respuesta, cuando el mismo dato existe en varias áreas.
2. **AskFlow (F3–F10, F20, F21), la evolución**: genera y valida T-SQL (o elige un stored procedure de una lista blanca),
   lo ejecuta **con los permisos del usuario** y devuelve resultados procesados, verificados y trazables. Corresponde a la visión
   futura "Recomendación y generación de SQL" de la propuesta. **Primer corte (decisión 17, 2026-11-23)**: un subconjunto acotado de
   cifras agregadas (conteos, sumas y promedios sobre una tabla) con plantilla de SQL fija, sin SQL generado por un modelo y apagado
   por defecto; el resto del AskFlow sigue en la fase 1b.


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
- Ejecutar consultas o devolver datos de clientes en el piloto de descubrimiento (llega en la fase 1b; ver §10). Excepción acotada
  (decisión 17, 2026-11-23): con `features.ask_flow` activado, totales agregados (`COUNT`, `COUNT DISTINCT`, `SUM`, `AVG`) sobre una
  tabla, con los permisos del usuario y nunca filas ni columnas marcadas como datos personales; apagado por defecto.
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
- Diálogo iterativo: aclaraciones con botones y preguntas de seguimiento sugeridas. Una aclaración puede acompañar a una respuesta (no
  bloquea) cuando el mismo dato existe en varias áreas.
- El chat atiende a una persona de negocio: saluda, responde qué es y qué puede hacer el asistente con textos fijos (la lista de bases
  de datos que menciona es solo la que su login ve), entiende seguimientos ("¿y en leasing?") con el historial y rechaza las órdenes de
  modificar datos.
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
| RF-40 | Generar, validar y ejecutar T-SQL de solo lectura con los permisos del usuario. **Primer corte construido** (decisión 17): solo agregados de plantilla fija sobre una tabla, apagado por defecto; falta el SQL generado por un modelo | P2 | F4–F10 |
| RF-41 | Usar métricas certificadas y consultas verificadas | P2 | F21 |
| RF-42 | Análisis comparativo, de causa raíz y exploratorio | P2 | F20 |

**Primer corte de cifras agregadas (decisión 17, 2026-11-23).** Se activa con `features.ask_flow: true` en `config/settings.yaml` del
catálogo o con `DISCOVERY_DATA_AGENT_ASK_FLOW=1` en la API; sin eso, una pregunta de cifras se responde como descubrimiento (qué información
usar). En la CLI, `discovery-data-agent discover "<pregunta>" --root <dir> --figures config/databases.local.yaml` lo activa solo para desarrollo.
Reglas, todas verificadas en el código (`src/discovery_data_agent/discovery/figures.py`, nodo `compute` del DiscoverFlow):
- Solo `COUNT`, `COUNT DISTINCT`, `SUM` y `AVG` sobre **una** tabla, con desglose opcional por una columna de categoría (se comprueba antes que
  tenga como máximo 25 valores distintos). Si la categoría pedida ("por segmento", "por tipo de crédito", "por marca") no está en esa tabla, se
  busca en una tabla a la que apunta una llave foránea de una sola columna, visible para el usuario y de la misma base, servidor y ambiente
  (`figures._related_category`): una sola unión por esa llave, con las mismas reglas.
- Un total o un grupo calculado sobre menos de 10 registros no se muestra, con supresión complementaria; cada consulta se audita antes de ejecutarse
  (`figure_query`) y, si la auditoría falla, no se ejecuta.
- El SQL sale de una plantilla fija con identificadores del catálogo entre corchetes: ningún texto del usuario ni de un modelo llega al SQL.
- Se ejecuta con la credencial de la sesión del usuario, en solo lectura y con un tope de 15 s (`api/discovery_data_agent_api/runtime.py::figure_executor`).
  SQL Server decide si puede leer la tabla.
- Nunca usa columnas marcadas `pii`. El número no pasa por el LLM: el texto es determinista. El sobre lleva `flow: "ask"` y `figure`.
- Es conservador y lo dice: no calcula si la pregunta pide un periodo, combina varias tablas o sistemas, la medida no es numérica, hay un filtro por valor, una condición que combina tablas, un cruce entre bases o sistemas, una unión de más de un salto, hay empate
  entre datos de tablas distintas o no identifica qué contar. Un adjetivo de estado ("activos", "vigentes") no se filtra: se muestra el
  desglose por estado.

Sigue siendo fase 1b: SQL generado por un LLM, filtros de fecha y de valor, condiciones que combinan tablas, cruces entre bases o sistemas, uniones de más de un salto, la capa semántica (F21), el motor de
análisis (F20), la ruta `/ask` y `sqlglot`.

### 6.5 Interfaces y medición
| ID | Requisito | Prioridad | Spec |
|---|---|---|---|
| RF-50 | Chat web con tarjetas de candidatos y botones de confirmación | P0 | F12 |
| RF-51 | API REST (`/discover`, `/assets`, `/curation`, `/admin/metrics`) | P0 | F12 |
| RF-52 | Servidor MCP para otros agentes (`discover`, `get_asset`, `get_lineage`…) | P1 | F12 |
| RF-53 | Auditoría completa de preguntas, candidatos y confirmaciones | P0 | F11 |
| RF-54 | Reporte de métricas de negocio, adopción y calidad | P0 | F25 |
| RF-55 | Set de evaluación automatizado con alerta de regresión y compuerta de calidad (`discovery-data-agent eval gate`) | P0 | F25, [calidad bancaria](calidad-bancaria.md) |

## 7. Requisitos no funcionales
| Área | Requisito | Spec |
|---|---|---|
| **Permisos** | Cada usuario solo descubre y consulta lo que su login SQL puede leer, incluidos metadatos, relaciones, reglas y documentos. Si nada visible responde, no se revela la existencia de otros objetos | F14 |
| **Residencia de datos** | Ningún dato de cliente se persiste fuera de la red del banco; el catálogo no contiene valores; los documentos se indexan con PII redactada | F17, F23 |
| **Seguridad** | Credenciales cifradas fuera del alcance del LLM; TLS en todas las conexiones; login de metadatos de solo lectura; sin SQL libre en las herramientas de metadatos; en qa y prod la API no arranca con ajustes inseguros | F14, F18, [calidad bancaria](calidad-bancaria.md) |
| **Rendimiento** | Descubrimiento p50 < 5 s, p95 < 10 s. Consulta de datos (fase 1b) p50 < 12 s, p95 < 30 s en producción (el MVP admite p95 < 40 s) | F22, OP-01 |
| **Calidad** | Hit@3 ≥ 85 %, Hit@1 ≥ 65 %; candidatos con confianza ≥ 0.8 correctos ≥ 85 %; 0 fugas de permisos y 0 objetos inventados. Ningún cambio se acepta si la compuerta `discovery-data-agent eval gate` baja de su línea base | F25, [calidad bancaria](calidad-bancaria.md) |
| **Trazabilidad** | Toda respuesta auditada; logs sin contenido | F11 |
| **Operación** | Despliegue on-premise en el stack Microsoft (Windows Server, IIS, SQL Server 2016 o posterior, Programador de tareas); camino a un despliegue mínimo en AWS sin cambiar la lógica | OP-01, CN-01 |
| **IA** | Amazon Bedrock, un modelo en el piloto, sin logging de invocaciones; modelos configurables por rol sin cambios de código. Con el rol `fast` el modelo redacta la respuesta para una persona de negocio, reformula la búsqueda cuando cubre poco y orienta cuando no hay candidatos; con `planner` entiende la intención y ordena. Al reformular y orientar no recibe los literales de la pregunta ni del historial. El ranking sigue siendo determinista. El número de una cifra nunca pasa por el modelo. El descubrimiento funciona también sin LLM (modo determinista) | F16 |
| **Licencias** | Componentes propios bajo Apache-2.0; sin dependencias AGPL | F18 |
| **Idioma** | Español | — |

## 8. Arquitectura (resumen)
Arquitectura simplificada el 2026-11-16 (§13, decisiones 9–16). Lo construido y lo pendiente están en el [plan de desarrollo](PLAN-desarrollo.md).

- **Orquestación**: el DiscoverFlow (descubrimiento) es un grafo de **LangGraph** con pasos fijos, servido por **FastAPI**: `intent → retrieve ⇄ grade → rerank → expand ⇄ review → [compute] → respond → finalize`. El nodo `compute` (cifras agregadas, decisión 17) solo corre con `features.ask_flow` activo y una pregunta de cifras. El resto del AskFlow (consulta) es de la fase 1b.
- **LLM**: Amazon Bedrock con un solo modelo, declarado como rol `planner` (intención y orden) o `fast` (narrativa, reformulación de la búsqueda y orientación cuando no hay candidatos). Sin embeddings ni juez en la fase 1a. Sin LLM, el flujo responde en modo determinista. En el build del catálogo, cuando hay modelo configurado, el enriquecimiento con IA viene activado por defecto (rol `planner` o, si no está, `fast`; marcado "sugerido por IA, sin revisar").
- **Búsqueda**: índice léxico (BM25) en la memoria de `DiscoveryDataAgent-API`, cargado al arrancar y filtrado por los permisos del usuario antes de ordenar. El grafo del patrimonio (FKs, misma entidad, linaje) también vive en memoria.
- **Persistencia**: BD `DiscoveryDataAgent` en SQL Server 2016 o posterior, con tablas normales y tablas temporales para el historial (esquemas `catalog`, `knowledge`, `golden`, `curation` y `audit`). Sin tipo `VECTOR`, Full-Text ni tablas de grafo.
- **Metadatos**: `discovery-data-agent-discovery`, biblioteca de solo lectura con consultas fijas a `sys.*` que usa el Builder (el login de metadatos solo existe ahí).
- **Ingesta**: el Builder es un comando (`discovery-data-agent catalog build`) que corre y termina; lo lanza cada noche el Programador de tareas de Windows y, bajo demanda, un `data_admin` desde Administración.
- **Interfaces**: web **Next.js** (chat, Curación, Catálogo, Métricas, Administración) y `DiscoveryDataAgent-API` detrás de IIS; MCP en `/mcp`.
- **Despliegue del piloto**: un Windows Server con dos procesos detrás de IIS (web y API) y la BD `DiscoveryDataAgent`; Bedrock es el único servicio externo.

Detalle en los diagramas de `docs/architecture/`, en [capas del backend](architecture/capas-backend.md) y en las specs OP-01 a OP-09 / CN-01 a CN-06.

### Stack tecnológico (decidido el 2026-10-15, revisado el 2026-11-16)
| Capa | Tecnología | Uso |
|---|---|---|
| API | **FastAPI** + **Pydantic v2** | `/auth/login`, `/discover` (y `/discover/stream` con SSE), `/discover/feedback`, `/assets`, `/catalog`, `/curation`, `/admin`; `/ask` en la fase 1b |
| Web | **Next.js** (`web/`) | Chat con tarjetas de candidatos y botones ✔/✖, pasos en vivo, Curación, Catálogo, Métricas y Administración; reenvía `/api/*` a la API |
| Orquestación | **LangGraph** | DiscoverFlow como grafo con pasos fijos, ciclos acotados y aristas condicionales (incluye el nodo `compute` de las cifras agregadas, apagado por defecto); el resto del AskFlow, en la fase 1b |
| LLM | **Amazon Bedrock** vía **`langchain-aws`** (`ChatBedrockConverse`) | Un modelo por rol (`planner`, `fast`) para intención, orden, narrativa, reformulación y orientación; salida estructurada con modelos Pydantic. En desarrollo: Ollama (solo local) o NVIDIA NIM con datos de prueba |
| Herramientas | SDK oficial de **MCP** (`discovery-data-agent-mcp`) | Las mismas herramientas de descubrimiento para la API, la web y los clientes MCP externos |
| Acceso a SQL Server | **pyodbc** + ODBC Driver 18 | Visibilidad con el login de cada usuario; metadatos con el login del Builder |
| Búsqueda | Índice léxico BM25 en memoria | Recuperación de tablas, columnas y conocimiento; el puerto `VectorStore` (F2) permite cambiarlo |
| Datos personales | Patrones locales (DUI, NIT, correo, teléfono, tarjeta) hoy; **Microsoft Presidio** para documentos (HU-26) | Rechazo de ediciones de curación con datos personales; redacción de documentos antes de indexar |
| Almacén de trabajo | BD `DiscoveryDataAgent` en **SQL Server 2016+** | Catálogo, conocimiento, curación y auditoría, on-premise en ambos despliegues |
| Alojamiento | IIS con HttpPlatformHandler on-premise · una tarea de **ECS Fargate** en AWS | El mismo código en ambos |
| Fase 1b | **sqlglot** (dialecto `tsql`) | Validación de SQL: AST, lista negra, inyección de `TOP` |

Reglas de uso de LangGraph:
- **El framework vive en una sola capa** (`discovery-data-agent/flows/`). Herramientas, `VectorStore`, prompts y modelos Pydantic son
  Python puro y no importan LangGraph, de modo que cambiar de orquestador no obliga a reescribir la lógica
  (`tests/test_architecture.py` lo comprueba).
- **Nodos con llamadas directas y salida estructurada**, no agentes autónomos: el orden de los pasos lo define el grafo, nunca el modelo.
- **Checkpointer solo en memoria** durante la petición (el estado contiene preguntas, clase D2 de F17). La trazabilidad
  persistente es la auditoría de F11; no se usa un checkpointer persistente fuera de la red del banco.
- El progreso de cada nodo (`stream_mode="updates"`) alimenta los eventos SSE de `/discover/stream` y los pasos en vivo de la web.

### 8.1 Principios de diseño
1. **Determinismo en la orquestación**: un grafo de LangGraph con pasos fijos. El LLM razona dentro de cada nodo, pero no decide el orden ni puede saltarse pasos.
2. **SQL Server es la barrera de seguridad**: cada consulta corre con el login del usuario. Los guardrails de la aplicación son defensa en profundidad.
3. **Nada se ejecuta sin validar**: validación estática, compilación (NOEXEC) y plan estimado (SHOWPLAN) antes de ejecutar.
4. **Toda respuesta es auditable**: SQL, tablas, supuestos, validaciones y confidence acompañan a cada dato.
5. **Memoria revisable por humanos**: el catálogo vive en tablas con historial (YAML versionable en desarrollo); el índice de búsqueda es derivado y se reconstruye al arrancar.
6. **Cero persistencia de datos fuera de la red del cliente**: la nube procesa y muestra; datos, preguntas, SQL y auditoría persisten solo on-premise (F17).
7. **Misma lógica, dos despliegues**: los grafos de LangGraph, las herramientas MCP y las dos imágenes (web y API) son idénticos en AWS y on-premise; solo cambia dónde corren los procesos y quién los programa.
8. **Descubrir antes que consultar**: ante la duda, el router elige el DiscoverFlow, que no toca datos (F3, F22).
9. **El conocimiento se captura con el uso**: cada confirmación de un usuario o respuesta de un responsable se convierte en conocimiento revisado y reutilizable (F24).
10. **Cada recomendación muestra su evidencia**: fuente de la descripción (humana, diccionario, documento o IA sin revisar) y por qué se recomienda.
11. **El éxito se mide contra una línea base**: las métricas de la propuesta se instrumentan desde el día uno (F25).
12. **La pieza más simple que cumple la medición**: un componente de infraestructura entra solo si mejora el set de evaluación o lo exige un requisito; por eso no hay vectores, tablas de grafo ni servicios aparte (§13, decisiones 9–12).

### 8.2 Despliegues
| Despliegue | Spec principal | Diagrama | Cuándo |
|---|---|---|---|
| **On-premise** | [OP-01](specs/on-premise/OP-01-despliegue-local.md) | `docs/architecture/onpremise-architecture.html` | Primero: piloto para validar la solución sin infraestructura cloud nueva (solo Bedrock) |
| **AWS (despliegue mínimo)** | [CN-01](specs/cloud-native/CN-01-despliegue-aws.md) | `docs/architecture/cloud-native-architecture.html` | Después del piloto, si se decide invertir en AWS: las mismas dos imágenes en una tarea de ECS Fargate, con la BD `DiscoveryDataAgent` todavía en el banco |

Los permisos heredados se explican en `docs/architecture/permisos-heredados.html` (F14) y aplican igual a los dos despliegues.

### 8.3 Contrato de respuesta: `AnswerEnvelope`
Lo devuelven `/discover` y la herramienta MCP `discover` (F12); en la fase 1b, también `/ask` y la herramienta `ask`.
```json
{
  "trace_id": "uuid",
  "flow": "discover | ask",
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
  "discovery": {"candidates": [], "alternatives": [], "related": [], "knowledge_gap": false, "suggested_questions": []},
  "timings_ms": {"total": 0, "llm": 0, "db": 0}
}
```
- `flow`: en `discover` se llena `discovery` (estructura completa en [F22](specs/comun/F22-discovery-flow.md)) y quedan vacíos `data`, `sql`,
  `validation` y `chart_spec`; en `ask` es al revés.
- Hoy, con las cifras agregadas activas (decisión 17), una respuesta con cifra lleva `flow: "ask"`, `discovery` con la información que la
  sustenta y `figure` (descripción, valor, grupos, notas y el SQL ejecutado); nunca `data` con filas. Una pregunta sobre el propio asistente
  lleva `status: ok` y `discovery: null` (intención `assistant` en la auditoría). `clarification` puede venir con `status: ok`: es una
  aclaración que no bloquea la respuesta. Los campos `validation`, `chart_spec` y `procedure` siguen siendo de la fase 1b.


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
| **0. Preparación** (semanas 0–1) | Línea base; acceso a fuentes; responsables del dominio piloto; servidor y BD `DiscoveryDataAgent` | Línea base firmada; compuerta `discovery-data-agent eval gate` aprobada con el catálogo del dominio piloto |
| **1a. Piloto de descubrimiento** (semanas 1–8) | RF P0 de §6.1–6.3 y 6.5 sobre el dominio **clientes / onboarding digital**, producción y QA; 10–15 usuarios | D1–D7 de OP-01 |
| **1b. Consulta de datos** | AskFlow, métricas certificadas y análisis (RF-40 a RF-42). **Adelantado (decisión 17, 2026-11-23)**: cifras agregadas sobre una tabla, apagadas por defecto. Pendiente: SQL generado por LLM, filtros de fecha y de valor, condiciones entre tablas, cruces, capa semántica, análisis y `/ask` | Criterios 1–7 de OP-01 |
| **2. Escalamiento** | Más dominios, RF P1, despliegue en AWS o alta disponibilidad on-premise | Decisión de la Gerencia de Datos |
| **Visión** | Linaje automatizado extremo a extremo, generación de glosarios, reglas de calidad, análisis de impacto, multiplataforma | — |

## 11. Dependencias y supuestos
- Logins SQL por usuario disponibles para los participantes del piloto en los servidores del piloto (producción y QA); Windows/AD con Kerberos es una evolución posterior.
- Roles `steward` y `data_admin` asignados por login SQL en el piloto; la asociación con cuentas de AD y la lectura de grupos por LDAP (F14) es una mejora posterior (HU-13).
- Login técnico de metadatos con `VIEW DEFINITION` y lectura de SSISDB y msdb.
- Acceso de solo lectura, con una cuenta técnica, a los diccionarios y a la documentación del dominio piloto (carpeta compartida o SharePoint).
- Cuenta de AWS con Bedrock habilitado (un modelo Claude para intención y orden) e IAM Roles Anywhere.
- Windows Server para la aplicación y una instancia SQL Server 2016 o posterior para la BD `DiscoveryDataAgent`.
- Un steward funcional y uno técnico asignados al dominio piloto con tiempo para curación (semanas 2–3).
- Aprobación de Seguridad de la Información para enviar metadatos y preguntas a Bedrock (sin almacenamiento).

## 12. Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Descripciones generadas por IA de baja calidad | Recomendaciones erróneas, pérdida de confianza | Fuente visible, tope de confianza 0.6 sin evidencia humana, curación inicial de los 100 activos más relevantes |
| Documentos con datos personales | Incumplimiento de residencia y privacidad | Redacción con Presidio y patrones locales; descarte de fragmentos con alta densidad de PII |
| El set de evaluación lo escribió el equipo de desarrollo | Los porcentajes no predicen el uso real | 50–80 preguntas reales validadas por un experto antes de declarar resultados (HU-33) |
| Las preguntas de reporte, tablero o estudio aciertan mucho menos que las de "¿dónde está X?" | Expectativas no cumplidas en el piloto. Medido el 2026-11-17 con 25 preguntas de reporte y un glosario de prueba, ambos escritos por el equipo: Hit@1 16 % solo con catálogo y 60 % con conocimiento (F23); muestra el sentido del efecto, no el acierto con documentos reales | Ingesta de diccionarios, documentos y reglas antes del piloto; medir con LLM real (HU-35) |
| Permisos heredados limitan la "democratización" | Usuarios sin acceso no descubren datos que existen | Escalamiento al responsable sin revelar nombres; revisar la política tras el piloto |
| Sin línea base | No se pueden demostrar los objetivos | Semana 0–1 dedicada a medirla |
| Baja adopción | No se capturan confirmaciones | Dominio piloto con dolor real, campeones por equipo, métricas semanales visibles |
| Stewards sin tiempo | Brechas sin cerrar | Asignación formal de la Gerencia de Datos; cola priorizada por demanda |
| Dependencia de un proveedor de LLM | Disponibilidad o coste | Modelos configurables por rol; NIM como alternativa con acuerdo de procesamiento |
| Las cifras agregadas (decisión 17) leen datos de negocio con el login del usuario | Un total mal elegido se toma por la respuesta, o el cambio de perfil de residencia no está aceptado por Seguridad | Apagadas por defecto; solo agregados de plantilla fija; no calculan ante la duda y dicen qué calcularon; nunca columnas `pii`; el número no pasa por el LLM; la revisión de seguridad independiente terminó el 2026-11-23 y sus bloqueantes se corrigieron (grupos pequeños no se muestran; auditoría antes de ejecutar); falta aceptarlo con Seguridad antes del piloto |

## 13. Decisiones y preguntas abiertas
### Decisiones tomadas
1. **Stack (decidido, 2026-10-15)**: FastAPI + LangGraph + Bedrock (`langchain-aws`) en lugar de CrewAI. Motivos: el PRD pide pasos fijos,
   ciclos (validador → planner) y trazabilidad, que son el modelo nativo de LangGraph; las abstracciones de agente de CrewAI añaden tokens
   y latencia sin aportar valor en un flujo de pasos fijos (objetivo p95 < 10 s). Detalle en la §8.
2. **Visibilidad (decidido, 2026-10-14)**: el usuario solo ve información a la que tiene acceso, también en el descubrimiento (metadatos,
   relaciones, reglas, documentos). Consecuencia: quien no tiene acceso a una BD no descubrirá que existe; el agente le ofrece escalar al
   responsable sin revelar nombres. Esto limita en parte la "democratización" de la propuesta a favor de la seguridad.
3. **Autenticación (decidido, 2026-10-14)**: logins SQL por usuario, que también calculan la visibilidad del descubrimiento (OP-03).
   Windows/AD con SSO y delegación restringida de Kerberos queda como evolución, sujeta a una prueba de concepto (OP-03).
4. **Nombre**: la propuesta usa "Enterprise Data Discovery Agent"; DiscoveryDataAgent es el nombre técnico del proyecto.
5. **Prioridad del planner (decidido, 2026-10-15)**: métrica certificada / consulta verificada → SP de la lista blanca → golden SQL → SQL nuevo
   (F6, F21). La capa semántica es revisable y se compila de forma determinista; una métrica puede delegar en un SP oficial.
6. **Catalog Builder separado (decidido, 2026-10-15; sustituida por la decisión 12)**: la ingesta corre fuera del camino interactivo y
   `discovery-data-agent-discovery` es una biblioteca dentro del Builder en ambos despliegues (F18). Lo que cambia con la decisión 12 es la forma:
   un comando programado en vez de un servicio de Windows.
7. **Credenciales por servidor y grupos (decidido, 2026-10-15)**: los logins SQL son por instancia, así que la sesión guarda una credencial por
   servidor. En el piloto los roles de curación se asignan por login SQL; los grupos de AD por LDAP (ACL de documentos, roles por grupo)
   llegan con HU-13 (F14).
8. **Un solo camino de escritura del conocimiento curado (decidido, 2026-10-15)**: feedback, curación y golden se escriben solo por
   `DiscoveryDataAgent-API` (`/discover/feedback`, `/curation/*`), con sesión, rol y auditoría previa; el MCP publicado a clientes externos solo
   tiene herramientas de lectura (F12).

9. **Búsqueda léxica en memoria, sin embeddings (decidido, 2026-11-16)**: la medición del 2026-10-29 (HU-34) dio Hit@1 93,1 % y
   Hit@3 93,1 % con el índice léxico sobre el catálogo crudo; los embeddings no cambiaron ningún caso y subieron el p95 de 73 ms a
   4,6 s. Se conserva el puerto `VectorStore` (F2). Se retiran `SqlServerVectorStore`, el tipo `VECTOR`, Full-Text y OpenSearch.
   Nota (2026-11-17): el canal semántico, que había quedado como experimento de desarrollo, se retiró del código; la medición de
   HU-34 queda como historia y ya no se puede repetir con este código.
10. **BD `DiscoveryDataAgent` en tablas normales (decidido, 2026-11-16)**: SQL Server 2016 o posterior, con tablas temporales para el historial.
    Sin tablas de grafo: entidades, FKs y linaje se guardan en tablas normales y el grafo del patrimonio (F19) se arma en memoria. El
    esquema `semantic` (F21) llega con la fase 1b. Ya no hace falta una instancia SQL Server 2025.
11. **Web en Next.js en lugar de Chainlit (decidido, 2026-11-16)**: la web cubre chat, Curación, Catálogo, Métricas y Administración, y
    reenvía `/api/*` a `DiscoveryDataAgent-API`, que no se publica directamente. IIS publica dos procesos: web y API (`/mcp`).
12. **Builder como comando programado (decidido, 2026-11-16)**: `discovery-data-agent catalog build` corre y termina, lanzado por el Programador
    de tareas de Windows o por un `data_admin` desde Administración. Sustituye a la decisión 6: no hay servicio `DiscoveryDataAgent-Builder`,
    job de SQL Server Agent ni API de administración en un proceso aparte.
13. **Un solo modelo de Bedrock en el piloto (decidido, 2026-11-16)**: para intención y orden de candidatos; sin embeddings ni juez en
    la fase 1a. Bedrock Guardrails deja de ser requisito de la fase 1a y pasa a ser una decisión de Seguridad de la Información; las
    guardas actuales están en el código ([calidad bancaria](calidad-bancaria.md) §3).
14. **AWS como despliegue mínimo posterior al piloto (decidido, 2026-11-16)**: ALB interno, una tarea de ECS Fargate con las imágenes de
    web y API, Builder lanzado por EventBridge Scheduler, Bedrock por VPC endpoint y la BD `DiscoveryDataAgent` todavía en el banco. Sin
    AgentCore, OpenSearch, Cognito, WAF, S3 ni Transit Gateway (CN-01).
15. **Rutas de la API (decidido, 2026-11-16)**: valen las del código (`/auth/login` con alias `/login`, `/discover`, `/discover/feedback`,
    `/assets/{asset_key}`, `/curation/*`, `/admin/*`); el navegador las ve bajo `/api/` porque la web las reenvía (F12, OP-04).
    Nota (2026-11-17): se añaden `GET /curation/history` (historial de una descripción, RF-34) y `GET`/`PUT /admin/stewards`
    (responsables de curación por login y dominio).
16. **Compuerta de calidad (decidido, 2026-11-15)**: `discovery-data-agent eval gate` (calidad, permisos, inyección, guardas, robustez,
    determinismo y auditoría) debe aprobar antes de aceptar un cambio y corre en la CI; los controles y lo que falta para operar en un
    banco están en [calidad bancaria](calidad-bancaria.md).
17. **Cifras agregadas: primer corte del AskFlow, adelantado de la fase 1b (decidido por el dueño del producto, 2026-11-23)**: se adelanta
    un subconjunto acotado para que el chat de negocio responda "¿cuántos…?" y "¿cuál es el saldo total…?" con el número, y no solo con la
    tabla donde está.
    - *Alcance*: `COUNT`, `COUNT DISTINCT`, `SUM` y `AVG` sobre una tabla, con desglose opcional por una columna de categoría de hasta 25
      valores distintos, de la tabla o de una tabla relacionada por una llave foránea de una sola columna, con una sola unión (§6.4). Verificado
      contra SQL Server local con datos ficticios: saldo de cartera por segmento del cliente, préstamos por tipo de crédito y tarjetas por marca
      coinciden con la consulta directa.
    - *Condiciones*: apagado por defecto (`features.ask_flow` o `DISCOVERY_DATA_AGENT_ASK_FLOW=1`); SQL de plantilla fija con identificadores del
      catálogo, sin texto del usuario ni de un modelo; con la credencial de la sesión del usuario, en solo lectura y con tope de 15 s; nunca
      columnas `pii`; totales y grupos de menos de 10 registros no se muestran; cada consulta se audita antes de ejecutarse y, si la auditoría falla, no se ejecuta; un servidor de producción exige `figures: true` en el inventario; el número no pasa por el LLM; el sobre lleva `flow: "ask"` y `figure`; ante la duda no calcula y lo dice.
    - *Sigue en la fase 1b*: SQL generado por un LLM, filtros de fecha y de valor, condiciones que combinan tablas ("clientes con préstamo y también tarjeta"), cruces entre bases o sistemas, uniones de más de un salto, capa semántica (F21), motor de
      análisis (F20), `/ask` y `sqlglot`. Las decisiones 9 a 16 no cambian.
    - *Qué contradice y se ajustó*: el no-objetivo de no ejecutar consultas (§3); el principio 3 de §8.1, que aquí cumple la plantilla
      fija en lugar de la validación estática, la compilación y el plan estimado (siguen siendo de la fase 1b); y el criterio "el
      DiscoverFlow no consulta tablas de datos" de F22 y la regla "nunca lee valores" de F17 y del manual (con la opción activa, el
      servicio lee agregados de las BDs de negocio con el login del usuario y no persiste valores). Antes de activarla en el piloto hay
      que aceptarlo con Seguridad de la Información y revisar los criterios D1–D7 de OP-01.
    - *Verificado*: contra el SQL Server local con datos ficticios (BancosSQL), los totales coinciden con la consulta directa
      ([plan §2](PLAN-desarrollo.md#2-resultados-medidos)). No se midió con preguntas de usuarios reales ni con Bedrock.
    - *Revisión de seguridad (2026-11-23)*: la revisión independiente terminó sin encontrar inyección SQL ni fugas de permisos (F14); dio dos
      bloqueantes, ambos corregidos el mismo día: los totales y grupos de menos de 10 registros no se muestran y cada consulta se audita antes de
      ejecutarse. Quedan abiertas DT-78, DT-79 y DT-80 ([wiki](wiki/deuda-tecnica.md)).

Las decisiones 9 a 15 formalizan la simplificación que ya mostraban los diagramas de `docs/architecture/`; donde contradicen a las
decisiones 1 a 8, valen las nuevas (la 6 queda sustituida por la 12; la 7 conserva las credenciales por servidor, con grupos de AD
aplazados a HU-13).

Notas del 2026-11-17 (precisan las decisiones anteriores; no añaden numeración):
- **Decisión 12, Builder**: la tarea programada entra a los servidores con autenticación de Windows (la cuenta del proceso) aunque el
  inventario diga login SQL, salvo que el servidor declare `metadata_user_env`. El inventario describe cómo entran los usuarios. La
  tarea solo va a los hosts de `DISCOVERY_DATA_AGENT_BUILDER_HOSTS`, obligatoria en qa y prod (OP-07).
- **Decisión 8, plantilla de las confirmaciones**: se quita toda palabra con algún dígito o con arroba, también los umbrales de
  negocio ("mora mayor a 90 días" y "a 30 días" son la misma confirmación), salvo el vocabulario conocido del banco: nombres del
  catálogo con dígitos y códigos del conocimiento con letras y dígitos ("NCB-022" se conserva solo si el glosario lo nombra). La
  regla por formatos se abandonó tras la revisión de seguridad, que reprodujo literales realistas que la pasaban. Se prefiere
  perder ese matiz a guardar un documento o una cuenta (F24, OP-02).
- **Decisión 9, cifra de la medición**: el 93,1 % es la medición histórica de HU-34, con el set de 31 casos de BancosSQL. La línea
  base vigente desde el 2026-11-17 es Hit@1 y Hit@3 98,0 % con 58 casos (BancosSQL) y 96,2 % con 31 (VBank), sin embeddings y con
  preguntas escritas por el equipo ([plan de desarrollo §2](PLAN-desarrollo.md#2-resultados-medidos)). La decisión no cambia.
- **Decisión 16, compuerta y CI**: la CI corre además un trabajo `web` (tipos, lint y build) y otro `cadena-de-suministro`
  (`pip-audit`, `npm audit` y SBOM), y el workflow corre también cada lunes; las dependencias de Python se instalan con versión y hash fijados y las imágenes base van por
  digest (OP-07, [calidad bancaria](calidad-bancaria.md)).
- **Decisión 10, versión del catálogo**: cada edición de curación y cada voto aprendido suben `catalog.catalog_version`. La versión
  significa "algo cambió", no "publicación".
- **Un solo proceso de API**: sesiones, trazas de respuestas, inventario y confirmaciones recientes viven en la memoria de
  `DiscoveryDataAgent-API`; el inventario se lee al arrancar. Más de un proceso exige rediseñar ese estado (OP-03, OP-07).

Notas del 2026-11-23 (precisan decisiones anteriores; la única decisión nueva es la 17):
- **Decisión 13, modelo único**: un solo modelo puede declararse como `planner` o como `fast`, o en ambos roles. Además de la narrativa,
  el rol `fast` atiende dos pasos nuevos: reformular la búsqueda cuando cubre poco (`LlmQueryExpander`, el patrón C de la medición) y,
  solo cuando no hay candidatos, reconocer una pregunta sobre el asistente entre temas fijos o proponer una aclaración en lenguaje de
  negocio (`LlmGuide`). Las opciones de esa aclaración pasan por las guardas de texto (`engine.looks_technical`,
  `engine.unsafe_generated_text`), y a esos dos pasos no llegan los literales de la pregunta ni del historial (`strip_literals`). El
  ranking sigue siendo determinista: declarar `planner` activa intención y orden con LLM, que la medición desaconseja por ahora. Con
  modelo configurado, el build del catálogo enriquece con IA por defecto (`BuildRequest.enrich` pasa a ser opcional); consume tokens.
- **Decisión 2 y F14, rechazo de escrituras**: la orden de modificar datos se evalúa solo sobre la pregunta actual, no sobre el
  historial que envía el cliente (`deterministic.is_write_request`).
- **Decisión 2, aclaraciones**: la guarda de las opciones de aclaración no consulta el catálogo; si no, delataría nombres de tablas
  ocultas.


### Preguntas abiertas
1. ¿Dónde viven los diccionarios y la documentación del dominio piloto (carpeta compartida, SharePoint on-premise u Online, Confluence), quién da
   acceso y son accesibles SSISDB y msdb con un login técnico?
2. ¿Qué gestor de requerimientos y canal de consultas se usan para la línea base?
3. ¿Qué servidores y ambientes entran en el piloto, y los participantes tienen el mismo login SQL en todos ellos?
4. ¿Qué canal de notificación prefieren los stewards (correo o Teams)?
5. ¿Se mantiene la política de permisos heredados también para metadatos después del piloto?
6. ¿Exige Seguridad de la Información Bedrock Guardrails en la fase 1a, además de las guardas del código?
7. ¿El responsable de un dominio ve en Curación activos que su login SQL no puede leer? Hoy sí en la cola de revisión y al editar
   descripciones de sus dominios; resuelto (2026-11-17) para el historial, que exige visibilidad, y fuera de sus dominios, donde lo
   que no ve responde igual que lo inexistente ([calidad bancaria](calidad-bancaria.md) §5).
8. ¿Qué lecturas se auditan además de las preguntas (fichas, catálogo, herramientas MCP distintas de `discover`)?
9. ¿Qué validación del login hace falta para dar un rol por su nombre (lista de administradores y responsables)? Hoy el código exige
   haberlo validado en un servidor con `environment: produccion`, cuando el inventario tiene alguno. ¿Vale esa regla o el banco
   prefiere un servidor de referencia designado? Queda superada cuando los roles salgan de grupos de AD (HU-13).

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
| Chat en lenguaje natural | ✅ | ✅ web Next.js | F12 |
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
| Búsqueda semántica | ✅ | ⚠️ léxica con sinónimos, expansión de vocabulario y LLM para intención y orden; el canal de embeddings se midió, no mejoró el acierto y se retiró (§13, decisión 9) | F2, F22 |
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
| Capacidad futura | Estado en DiscoveryDataAgent |
|---|---|
| Descubrimiento automatizado de linaje | Base en F23 (un salto, nivel de tabla) y F19 (relaciones entre BDs) |
| Recomendación y generación de SQL | Ya especificado: AskFlow F4–F10, capa semántica F21, motor de análisis F20 (fase 1b). Existe un primer corte de totales con plantilla fija, sin SQL generado por un modelo (decisión 17) |
| Generación de glosarios de negocio | Sugerencias de glosario y reglas con `reviewed: false` (F2, F23) |
| Recomendaciones de reglas de calidad | No cubierto (fase posterior) |
| Análisis de impacto | Parcial: linaje descendente de F23 + dependencias de F19 |
| Identificación de brechas de conocimiento | Cubierto en F24 (reporte de brechas) |
| Descubrimiento multiplataforma | Interfaz `MetadataConnector` (F23); conectores pendientes |

### 14.7 Cobertura por despliegue (revisión del 2026-10-14)
| Capacidad de la propuesta | Común | On-premise (Microsoft) | AWS (despliegue mínimo) |
|---|---|---|---|
| Flujo de descubrimiento y respuesta con candidatos | F3, F22 | OP-01 (fase 1a), OP-04 | CN-01, CN-04 |
| Ambientes y servidores | F1 | OP-02 (`catalog`) | CN-02 |
| Diccionarios, documentos, ETL y reglas | F23 | OP-02 (`knowledge`, Presidio, tarea programada) | CN-02 (tarea ECS programada; escribe en la BD `DiscoveryDataAgent` on-premise) |
| Responsables, escalamiento y curación | F24 | OP-02 (`curation`), OP-04 (webhook de Teams) | Igual: BD `DiscoveryDataAgent` on-premise, CN-04 |
| Auditoría y métricas | F11, F25 | OP-05 (esquema `audit`, evaluación programada) | CN-05 (el mismo esquema `audit` on-premise) |
| Residencia de documentos y preguntas escaladas | F17, F23 | OP-06 | CN-06 |
| Permisos heredados también en el descubrimiento | F14 | OP-03 | CN-03 |

Los diagramas de `docs/architecture/` reflejan el descubrimiento con la arquitectura simplificada del 2026-11-16: DiscoverFlow, fuentes
de conocimiento, BD `DiscoveryDataAgent`, permisos heredados también al descubrir y los controles de calidad bancaria.

## Anexo A. Catálogo de specs
```
docs/specs/
├─ comun/          Lógica de la solución, idéntica en ambos despliegues (F1–F25)
├─ on-premise/     Despliegue en la red corporativa; es el del piloto (OP-01 a OP-09; OP-07: instalación y operación; OP-08: interfaz web; OP-09: situaciones de desarrollo)
└─ cloud-native/   Despliegue mínimo en AWS, posterior al piloto (CN-01 a CN-06)
```

Fase: **1a** piloto de descubrimiento · **1b** consulta de datos (sin implementar salvo el primer corte de cifras agregadas, decisión 17, que toca F3, F6 y F8; el resto de sus specs se revisará contra §13 antes de empezar).

| ID | Feature | Fase | Spec | On-premise | AWS |
|---|---|---|---|---|---|
| F1 | Catalog Builder (ingesta y mapeo) | 1a | [F01](specs/comun/F01-catalog-builder.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) comando programado | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) tarea ECS programada |
| F2 | Memoria de búsqueda (`VectorStore`) | 1a | [F02](specs/comun/F02-semantic-memory.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) índice léxico en memoria | = |
| F3 | Intent & Router (el enrutado de cifras al AskFlow es parcial: decisión 17) | 1a | [F03](specs/comun/F03-intent-router.md) | = | = |
| F4 | Schema Linking | 1b | [F04](specs/comun/F04-schema-linking.md) | = | = |
| F5 | Value Resolution (en vivo) | 1b | [F05](specs/comun/F05-value-resolution.md) | = | = |
| F6 | Planner T-SQL / SP (solo la plantilla fija de agregados, decisión 17) | 1b | [F06](specs/comun/F06-planner.md) | = | = |
| F7 | Validator | 1b | [F07](specs/comun/F07-validator.md) | = | = |
| F8 | Executor (solo agregados con la credencial de la sesión, decisión 17) | 1b | [F08](specs/comun/F08-executor.md) | = | = |
| F9 | Result Verifier | 1b | [F09](specs/comun/F09-result-verifier.md) | = | = |
| F10 | Analyst | 1b | [F10](specs/comun/F10-analyst.md) | = | = |
| F11 | Auditoría | 1a | [F11](specs/comun/F11-audit.md) | [OP-05](specs/on-premise/OP-05-auditoria-observabilidad.md) esquema `audit` de la BD `DiscoveryDataAgent` | [CN-05](specs/cloud-native/CN-05-auditoria-observabilidad.md) el mismo esquema, on-premise |
| F12 | Interfaces (API, web, MCP) | 1a | [F12](specs/comun/F12-interfaces.md) | [OP-04](specs/on-premise/OP-04-interfaces.md) IIS | [CN-04](specs/cloud-native/CN-04-interfaces.md) ALB interno |
| F13 | Arquitectura documentada (Archify) | 1a | [F13](specs/comun/F13-architecture-docs.md) | = | = |
| F14 | Identidad y permisos heredados | 1a | [F14](specs/comun/F14-identity.md) | [OP-03](specs/on-premise/OP-03-identidad.md) SessionVault en memoria | [CN-03](specs/cloud-native/CN-03-identidad.md) igual; Secrets Manager solo para secretos de servicio |
| F16 | Proveedores LLM: Bedrock (Ollama y NIM en desarrollo) | 1a | [F16](specs/comun/F16-llm-providers.md) | = | = |
| F17 | Residencia de datos | 1a | [F17](specs/comun/F17-data-residency.md) | [OP-06](specs/on-premise/OP-06-residencia-datos.md) | [CN-06](specs/cloud-native/CN-06-residencia-datos.md) |
| F18 | `discovery-data-agent-discovery`: lectura de metadatos (Apache-2.0) | 1a | [F18](specs/comun/F18-discovery-mcp.md) | Biblioteca dentro del Builder | = |
| F19 | Descubrimiento entre múltiples BDs (grafo del patrimonio) | 1a | [F19](specs/comun/F19-multi-db-discovery.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) grafo en memoria; entidades y linaje en tablas normales | = |
| F20 | Motor de análisis | 1b | [F20](specs/comun/F20-analysis-engine.md) | Sin código libre | Se decidirá con la fase 1b |
| F21 | Capa semántica (métricas certificadas, consultas verificadas) | 1b | [F21](specs/comun/F21-semantic-layer.md) | Esquema `semantic` (fase 1b) | = |
| **F22** | **DiscoverFlow: candidatos con ubicación, descripción, reglas, relaciones y confianza** | 1a | [F22](specs/comun/F22-discovery-flow.md) | = | = |
| F23 | Fuentes de conocimiento: diccionarios, documentación, ETL y reglas de negocio | 1a | [F23](specs/comun/F23-knowledge-sources.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) |
| F24 | Curación y captura del conocimiento institucional | 1a | [F24](specs/comun/F24-knowledge-curation.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) esquema `curation`, [OP-04](specs/on-premise/OP-04-interfaces.md) | = |
| F25 | Métricas de éxito, línea base y piloto | 1a | [F25](specs/comun/F25-success-metrics.md) | = | = |

"=" significa que no hay diferencias frente a la spec común (o frente a on-premise, en la columna AWS).

## Anexo B. Glosario
- **Catálogo**: descripción de BDs, esquemas, tablas, columnas, FKs y SPs, **sin valores de datos** (esquema `catalog` de la BD `DiscoveryDataAgent`; YAML en desarrollo).
- **Cifra agregada**: total (`COUNT`, `COUNT DISTINCT`, `SUM` o `AVG`) sobre una tabla, con desglose opcional por una categoría (de la tabla o de una tabla relacionada, con una unión), calculado con el login del usuario y una plantilla de SQL fija. Primer corte del AskFlow, apagado por defecto (§13, decisión 17).
- **Compuerta de calidad**: `discovery-data-agent eval gate`, siete suites que deben aprobar antes de aceptar un cambio ([calidad bancaria](calidad-bancaria.md)).
- **Golden SQL**: pares pregunta→SQL validados por un humano. El original vive en la auditoría on-prem; en el índice solo su plantilla anonimizada.
- **Visibilidad**: conjunto de objetos que el login del usuario puede leer o ejecutar, según SQL Server.
- **Confidence**: puntuación de 0 a 1. En el AskFlow combina los chequeos deterministas con el veredicto del LLM-judge (F9); en el DiscoverFlow combina relevancia, evidencia, confirmaciones y acuerdo entre fuentes (F22).
- **`asset_key`**: identificador lógico de un objeto (`db.schema.objeto[.columna]`) que agrupa sus copias en todos los ambientes (F1).
- **Golden discovery**: pregunta de descubrimiento (plantilla sin literales: toda palabra con un dígito o una arroba que no sea vocabulario del banco; no detecta nombres de personas) confirmada por usuarios o por un responsable, ligada a los activos correctos (F24).
- **Steward / responsable**: grupo funcional o técnico dueño de un dominio de datos (`config/owners.yaml`, F24).
- **Brecha de conocimiento**: pregunta sin candidato con confianza suficiente, o activo muy consultado sin descripción revisada (F24).
