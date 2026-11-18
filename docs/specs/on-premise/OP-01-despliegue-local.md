# OP-01 — Despliegue on-premise sobre stack Microsoft (Windows Server + SQL Server)

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Diagrama: `docs/architecture/onpremise-architecture.html` · Specs relacionadas: [OP-02](OP-02-catalogo-memoria.md) catálogo y memoria · [OP-03](OP-03-identidad.md) identidad · [OP-04](OP-04-interfaces.md) interfaces · [OP-05](OP-05-auditoria-observabilidad.md) auditoría · [OP-06](OP-06-residencia-datos.md) residencia de datos · [OP-07](OP-07-instalacion-operacion.md) instalación, entornos y operación · [calidad bancaria](../../calidad-bancaria.md) controles y compuerta de calidad
>
> Este despliegue sirve como **MVP** para validar la solución antes de invertir en la nube, y como opción on-premise.

## Objetivo
Probar **la hipótesis central**: que un grafo de LangGraph con Bedrock, sobre un catálogo extraído de SQL Server, encuentra los datos
que el usuario describe en lenguaje natural de forma **correcta, validada y con los permisos del usuario**. Todo corre en la red
corporativa sobre **piezas Microsoft que el equipo ya opera** (Windows Server, IIS, SQL Server, Programador de tareas), y de AWS solo se
usa **Amazon Bedrock** (un modelo de lenguaje, sin embeddings). Si el MVP valida la hipótesis, el despliegue en AWS es un paso
posterior y mínimo (§Camino a producción) que no rehace la lógica.

## Decisiones
Las de 2026-10-14, con los cambios del 2026-11-16 (PRD §13, decisiones 9–16):

| Tema | Decisión |
|---|---|
| Servidor de aplicación | **Windows Server sin Docker**: dos procesos detrás de IIS con HttpPlatformHandler, la **web** (Next.js, Node) y **`ConverData-API`** (FastAPI, un solo proceso uvicorn). Sin servicios de Windows propios ([OP-07](OP-07-instalacion-operacion.md); PRD §13, decisión 11) |
| BD de trabajo de ConverData | BD `ConverData` en **tablas normales, SQL Server 2016 o posterior**. Las BDs de datos siguen en sus versiones actuales (PRD §13, decisión 10) |
| Búsqueda | **Léxica en memoria (BM25)** dentro de `ConverData-API`, como único canal de la fase 1a. Sin embeddings ni índices en SQL Server ([OP-02](OP-02-catalogo-memoria.md); PRD §13, decisión 9) |
| Identidad | **Logins SQL por usuario** (OP-03). Windows/AD con Kerberos queda como evolución |
| Código Python libre (F20) | **No en la v1**: solo la biblioteca de análisis determinista |
| Catalog Builder | **Comando `converdata catalog build` que corre y termina**, lanzado cada noche por el Programador de tareas de Windows y, bajo demanda, desde Administración (`POST /admin/catalog/build`, rol `data_admin`). No es un servicio de Windows ni tiene API propia (PRD §13, decisión 12) |
| LLM | **Un solo modelo de Bedrock** en el piloto, para los pasos `intent` y `rerank` del DiscoverFlow (la narrativa puede usar el mismo). Sin modelo de embeddings ni juez en la fase 1a (PRD §13, decisión 13) |

## Estado (2026-11-16)
| | |
|---|---|
| **Construido** | `ConverData-API` (rutas de OP-04, DiscoverFlow, `/mcp`, SessionVault, controles de [calidad bancaria §3](../../calidad-bancaria.md)); web Next.js (`web/`); `converdata catalog build`; índice léxico en memoria; compuerta `converdata eval gate`; **BD `ConverData`** por migraciones (`converdata db migrate`) con catálogo, conocimiento, auditoría y, desde el 2026-11-17, inventario de servidores, responsables, dudas escaladas y votos, probada contra SQL Server 2022 (OP-02, OP-05); con ella la API no guarda estado en disco. Desarrollo con `docker compose` y LLM local (Ollama) o NIM. Desde el 2026-11-17: dependencias de Python con versión y hash (`requirements/*.lock`), imágenes base por digest (el argumento de build `EXTRAS` pasó a `REQUIREMENTS`; para NIM u Ollama, `CONVERDATA_REQUIREMENTS=requirements/dev.lock`) y CI con tres trabajos: `backend`, `web` y `cadena-de-suministro` (`pip-audit`, `npm audit`, SBOM), detalle en [OP-07](OP-07-instalacion-operacion.md) |
| **Pendiente** | Construir la imagen con los bloqueos (no se pudo el 2026-11-17), fijar sus paquetes del sistema, firmarla y escanearla; Bedrock de punta a punta (HU-35); scripts de instalación en IIS y tareas programadas (HU-37, HU-24); documentos con redacción de PII (HU-26) y linaje SSIS (HU-27); grupos de AD (HU-13) |

## Componentes
| Pieza | Cloud native (CN), posterior al piloto | On-premise Microsoft (OP) |
|---|---|---|
| Entrada web | ALB interno, alcanzado por Site-to-Site VPN | **IIS** en el Windows Server (443, certificado de la PKI corporativa), como proxy inverso con HttpPlatformHandler: `/` a la web y `/mcp` a `ConverData-API` |
| Web y API | Una tarea ECS Fargate con dos contenedores (web y API) | **Web Next.js** (`web/`, proceso Node) y **`ConverData-API`** (FastAPI, un proceso uvicorn), lanzados y supervisados por HttpPlatformHandler. La web reenvía `/api/*` a la API, que no se publica directamente |
| Orquestación | El mismo DiscoverFlow en el contenedor de la API | **DiscoverFlow (LangGraph)** dentro de `ConverData-API`; AskFlow en la fase 1b |
| Herramientas MCP | El mismo `converdata-mcp` en `/mcp` del contenedor de la API | **`converdata-mcp`** montado en `/mcp` de `ConverData-API`, publicado por IIS |
| Descubrimiento (F18) | Biblioteca dentro de la tarea del Builder | Biblioteca dentro del comando del Builder |
| Ingesta y refresco | Builder como tarea lanzada por EventBridge Scheduler | **`converdata catalog build`** lanzado por el **Programador de tareas de Windows** cada noche, y `POST /admin/catalog/build` bajo demanda |
| Búsqueda | El mismo índice léxico en memoria de la API | **Índice léxico en memoria (BM25)** de `ConverData-API`, cargado al arrancar y filtrado por `visible_ids` (OP-02) |
| Grafo entre BDs (F19) | En memoria, igual | Entidades, FKs y aristas de linaje en **tablas normales**; el grafo se construye **en memoria** al cargar |
| Catálogo fuente | BD `ConverData`, que sigue on-premise | **Tablas de la BD `ConverData` con *system-versioned temporal tables*** (historial de cada cambio). Archivos YAML solo en desarrollo, sin `CONVERDATA_DB` |
| Auditoría + golden | BD `ConverData`, que sigue on-premise | **Esquemas `audit` y `golden` de la BD `ConverData`** (modelo de F11). Con `CONVERDATA_DB` va a `audit.*` (`src/converdata/audit/sqlserver.py`); sin ella (solo desarrollo), JSONL con cadena de hashes |
| LLM | Bedrock por VPC endpoint | **Bedrock, un modelo** por HTTPS a través del proxy corporativo; NIM y Ollama solo con datos de prueba. Bedrock Guardrails no es requisito de la fase 1a: lo decide Seguridad de la Información, y mientras tanto las guardas son las del código ([calidad bancaria §3](../../calidad-bancaria.md)) |
| Credenciales SQL de usuarios | SessionVault en memoria de la API, igual | **SessionVault en memoria** de `ConverData-API` (OP-03) |
| Secretos de servicio (login de metadatos, acceso a Bedrock, código de instalación) | Secrets Manager | **DPAPI** (ámbito de la cuenta de servicio) o Windows Credential Manager; Bedrock con **IAM Roles Anywhere** y un certificado de la PKI corporativa, sin claves de larga duración |
| Cuentas de servicio | Rol IAM de la tarea | **gMSA** (cuentas de servicio administradas por grupo), sin contraseñas que rotar a mano |
| Sandbox de análisis (F20) | No aplica (fase 1b) | **No en la v1** (solo biblioteca determinista) |
| Conexión a los SQL Server | Site-to-Site VPN | **Directa** por TDS 1433; contra la **secundaria legible de Always On** (`ApplicationIntent=ReadOnly`) cuando exista |
| Observabilidad | CloudWatch Logs sin contenido | Logs JSON rotados + **Visor de eventos de Windows** + alertas en el monitoreo existente (OP-05) |

El despliegue en AWS no usa AgentCore, OpenSearch, Cognito, WAF, S3 ni Transit Gateway (PRD §13, decisión 14).

## Alcance funcional del MVP
El MVP sigue el orden de valor de la propuesta: **primero descubrimiento, después consulta**.

**Fase 1a, piloto de descubrimiento (semanas 1–8 de F25, tras la preparación de las semanas 0–1)**, con `features.ask_flow: false`:
- F1 + F18 (catálogo con ambientes y servidores), F2 (canal léxico), F3 (intent `discovery`), F19 (entidades entre BDs).
- F22 DiscoverFlow, F23 fuentes de conocimiento (diccionarios, documentos, SSIS y jobs de SQL Server, reglas), F24 curación y escalamiento.
- F11, F12 (`/discover`, tarjetas de candidatos, Curación, Métricas), F14: el descubrimiento hereda los permisos del login del usuario (también para metadatos).
- F25: línea base y métricas desde el primer día; compuerta `converdata eval gate` antes de cada despliegue ([calidad bancaria §2](../../calidad-bancaria.md)).
- Dominio piloto: **clientes / onboarding digital** (el ejemplo de la propuesta), en producción y QA.

**Fase 1b, consulta de datos** (si 1a cumple sus criterios de salida). **Incluye**:
- F3 a F10 completos (intent, linking, values en vivo, planner, validator con bucle de corrección, executor, verifier con juez y analyst).
- F20 con la biblioteca de análisis determinista (sin código libre) y F21 capa semántica (esquema `semantic` de la BD `ConverData`).
- `/ask` en la API, en la web y en `/mcp` (OP-04).

La infraestructura que citan las specs de la fase 1b se revisa contra PRD §13 (decisiones 9–15) antes de implementarla.

**Fuera del alcance on-premise**: alta disponibilidad del servidor de aplicación, SSO, `candidates: 2`, código Python libre, fallback automático a NIM con datos reales.

**Datos**:
- Validación técnica del pipeline (antes del piloto): **AdventureWorks** restaurada en una instancia de desarrollo.
- Fase 1a: metadatos y conocimiento del dominio **clientes / onboarding digital** (p. ej. `VBank_ING`, `Onboarding`) en producción y QA;
  no se leen datos salvo muestras en memoria contra la réplica (F1).
- Fase 1b: 1 o 2 BDs del dominio (no las 300+ tablas de golpe), consultadas en **réplica o copia de solo lectura**.

Entornos (dev, qa, piloto), requisitos no funcionales, instalación con scripts, respaldo y actualización: [OP-07](OP-07-instalacion-operacion.md).

## Topología
```
Windows Server 2022/2025 — servidor de aplicación (red corporativa)
├─ IIS :443 (TLS PKI corporativa) ── proxy inverso (HttpPlatformHandler)
│   ├─ /      → web Next.js (proceso Node); su ruta /api/[...path] reenvía a ConverData-API en 127.0.0.1
│   └─ /mcp   → ConverData-API (FastAPI + DiscoverFlow + converdata-mcp + SessionVault + índice léxico; un solo proceso)
├─ Programador de tareas ── cada noche ──► converdata catalog build (corre y termina) ──► evaluación de regresión
│                        ── cada día   ──► purga de auditoría (180 días)
└─ Python 3.12 (entorno gestionado con uv) y Node.js LTS; procesos con cuentas gMSA

SQL Server 2016+ — BD ConverData (esquemas catalog, knowledge, golden, curation, audit; semantic en la fase 1b)
SQL Server de datos (versiones actuales) ◄── TDS 1433 con el login de cada usuario: visibilidad (réplica legible si existe)
                                         ◄── login de metadatos desde el Builder (sys.*, Query Store, SSISDB, msdb)
Carpeta compartida / SharePoint ◄── Builder (cuenta técnica de solo lectura)
Amazon Bedrock ◄── HTTPS vía proxy corporativo (IAM Roles Anywhere), desde ConverData-API y el Builder
```
La API escucha solo en `127.0.0.1`: IIS le envía `/mcp` y la web le reenvía `/api/*`.

## Dimensionamiento orientativo del servidor de aplicación
4 vCPU, 16 GB de RAM y 100 GB de disco para el piloto (3–20 usuarios). El LLM lo ejecuta Bedrock; la búsqueda la hace la API en
memoria (p95 de 73 ms en la medición HU-34), así que el catálogo y el conocimiento del dominio piloto deben caber en RAM.

## Configuración AWS mínima
- **IAM Roles Anywhere** con el certificado del servidor emitido por la PKI corporativa (alternativa: usuario IAM con clave guardada con DPAPI).
- Política de **mínimo privilegio**: `bedrock:InvokeModel` y `bedrock:InvokeModelWithResponseStream` sobre el modelo o inference profile elegido; nada más. `bedrock:ApplyGuardrail` solo se añade si Seguridad de la Información decide usar Guardrails.
- Acceso habilitado en Bedrock a **un modelo** de lenguaje. Sin modelo de embeddings ni juez en la fase 1a.
- **Model invocation logging desactivado** (F17).

Estado: el gateway de LLM soporta Bedrock, pero no se ha probado de punta a punta (HU-35); hoy se desarrolla con Ollama o NIM.

## Residencia de datos en el MVP
Se cumple F17 de forma natural:
- Catálogo, conocimiento, auditoría y sesiones viven en la red corporativa (BD `ConverData` y memoria de la API; archivos solo en desarrollo, sin `CONVERDATA_DB`).
- Bedrock solo procesa (sin logging).
- El catálogo no lleva valores.

El único dato que sale de la red es el contexto enviado a Bedrock en cada llamada.

## Plan de validación (criterios de salida del MVP)
**Fase 1a, descubrimiento** (detalle en [F25](../comun/F25-success-metrics.md)):
| # | Prueba | Umbral |
|---|---|---|
| D1 | Set de evaluación de descubrimiento (50–80 preguntas reales con los activos correctos) | Hit@3 ≥ 85 % · Hit@1 ≥ 65 % |
| D2 | Calibración: candidatos con confianza ≥ 0.8 que son correctos | ≥ 85 % |
| D3 | Tiempo de localización de fuentes frente a la línea base | −50 % |
| D4 | Consultas a expertos frente a la línea base | −30 % |
| D5 | Latencia p50 / p95 | < 5 s / < 10 s |
| D6 | Permisos y PII: ningún objeto fuera de la visibilidad del usuario ni valor de cliente aparece en respuestas o índice | 0 |
| D7 | Adopción: usuarios piloto activos al menos 2 semanas de 4 | ≥ 70 % |

D1, D2, D5 y D6 los comprueba de forma automática `converdata eval gate` (suites `calidad` y `permisos`, [calidad bancaria §2](../../calidad-bancaria.md)).
Hoy la compuerta aprueba sobre dos catálogos de prueba con preguntas del equipo; el set de preguntas reales del piloto está pendiente.

**Fase 1b, consulta de datos**:
| # | Prueba | Umbral |
|---|---|---|
| 1 | Set de evaluación de 30–50 preguntas reales con SQL de referencia (AdventureWorks, después la BD piloto) | Precisión de ejecución ≥ 80 % |
| 2 | Calibración: las respuestas con `confidence < 0.6` son las incorrectas | ≥ 70 % de las incorrectas quedan marcadas |
| 3 | Guardas del validator: batería de SQL maliciosos y de inyección de prompt | 0 ejecuciones indebidas |
| 4 | Permisos: dos usuarios con permisos distintos hacen la misma pregunta | Cada uno ve solo lo suyo; error 229 manejado |
| 5 | Latencia p50 / p95 (umbral del MVP; objetivo de producción < 12 s / < 30 s, F22) | < 15 s / < 40 s |
| 6 | Coste Bedrock por pregunta | Medido y reportado (decide los modelos de prod) |
| 7 | Feedback de 3–5 usuarios piloto durante 2 semanas | ≥ 70 % 👍 |

## Camino a producción
El despliegue en AWS es **mínimo y posterior al piloto** (PRD §13, decisión 14). La lógica (DiscoverFlow, `converdata-mcp`, prompts,
guardas) y el modelo de procesos no cambian; solo cambia dónde corren:
- La web y `ConverData-API` pasan a **una tarea ECS Fargate** con dos contenedores, detrás de un **ALB interno**.
- El Builder pasa a una tarea lanzada por **EventBridge Scheduler**.
- Bedrock se alcanza por **VPC endpoint** en lugar del proxy corporativo.
- Los secretos de servicio pasan de DPAPI a **Secrets Manager**; los logs, sin contenido, a **CloudWatch Logs**.
- La BD `ConverData` y los SQL Server de datos **siguen on-premise**, alcanzados por **Site-to-Site VPN**.
- El índice léxico, el SessionVault y el grafo siguen en la memoria de la API.

Alternativamente, el despliegue on-premise puede quedarse como producción si la organización prefiere no usar la nube: entonces se añaden un segundo servidor de aplicación detrás de un balanceador (lo que exige sacar el SessionVault de la memoria de un proceso, OP-03) y el grupo de disponibilidad de SQL Server para la BD `ConverData`.
