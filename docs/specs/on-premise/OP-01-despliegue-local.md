# OP-01 — Despliegue on-premise sobre stack Microsoft (Windows Server + SQL Server)

> Diagrama: `docs/architecture/onpremise-architecture.html` · Specs relacionadas: [OP-02](OP-02-catalogo-memoria.md) catálogo y memoria · [OP-03](OP-03-identidad.md) identidad · [OP-04](OP-04-interfaces.md) interfaces · [OP-05](OP-05-auditoria-observabilidad.md) auditoría · [OP-06](OP-06-residencia-datos.md) residencia de datos
>
> Este despliegue sirve como **MVP** para validar la solución antes de invertir en la nube, y como opción on-premise.

## Objetivo
Probar **la hipótesis central**: que unos grafos de LangGraph con Bedrock, sobre un catálogo extraído de SQL Server, encuentra los datos y
responde preguntas en lenguaje natural de forma **correcta, validada y con los permisos del usuario**. Todo corre en la red
corporativa sobre **piezas Microsoft que el equipo ya opera** (Windows Server, IIS, SQL Server, SQL Server Agent), y de AWS solo se
usa **Amazon Bedrock** (LLM y embeddings). Si el MVP valida la hipótesis, se migra a la arquitectura cloud native (CN-01) sin rehacer
la lógica.

## Decisiones (2026-10-14)
| Tema | Decisión |
|---|---|
| Servidor de aplicación | **Windows Server sin Docker**: Python como servicios de Windows detrás de IIS |
| BD de trabajo de ConverData | **SQL Server 2025** (BD `ConverData`). Las BDs de datos pueden seguir en sus versiones actuales |
| Identidad | **Logins SQL por usuario** (OP-03). Windows/AD con Kerberos queda como evolución |
| Código Python libre (F20) | **No en la v1**: solo la biblioteca de análisis determinista |

## Componentes
| Pieza | Cloud native (CN) | On-premise Microsoft (OP) |
|---|---|---|
| Entrada web | ALB + WAF + Cognito | **IIS** en el Windows Server (443, certificado de la PKI corporativa), como proxy inverso con HttpPlatformHandler |
| Chat y API | ECS Fargate | **Chainlit + FastAPI** como servicios de Windows (`ConverData-UI`, `ConverData-API`) |
| Orquestación | DiscoverFlow y AskFlow (LangGraph) en AgentCore Runtime | **Los mismos grafos de LangGraph** dentro del servicio `ConverData-API` (FastAPI) |
| Herramientas MCP | converdata-mcp en Runtime + AgentCore Gateway | **El mismo `converdata-mcp`** en `/mcp` del servicio `ConverData-API`, publicado por IIS |
| Descubrimiento (F18) | `converdata-discovery` en la tarea ECS | **`converdata-discovery`** como servicio de Windows escuchando solo en `localhost` |
| Ingesta y refresco | EventBridge + ECS task | **Job de SQL Server Agent** con un paso PowerShell que llama a `POST /api/admin/catalog/refresh` en el servidor de aplicación (o Programador de tareas de Windows en ese servidor) |
| Memoria semántica | OpenSearch Serverless | **BD `ConverData` en SQL Server 2025**: tipo `VECTOR` + Full-Text Search (OP-02) |
| Grafo entre BDs (F19) | YAML en S3 + memoria | **Tablas de grafo de SQL Server** (`NODE`/`EDGE`, consultas `MATCH`) en la BD `ConverData` |
| Catálogo fuente | S3 versionado | **Tablas de la BD `ConverData` con *system-versioned temporal tables*** (historial de cada cambio); export a YAML para revisión en git |
| Auditoría + golden SQL | ConverData_Audit on-prem | **Esquema `audit` de la BD `ConverData`** (mismo modelo de F11) |
| LLM y embeddings | Bedrock por rol + Guardrails + NIM fallback | **Bedrock por rol** por HTTPS a través del proxy corporativo; NIM solo con datos de prueba |
| Credenciales SQL de usuarios | Secrets Manager + KMS | **SessionVault en memoria** del servicio `ConverData-API` (OP-03) |
| Secretos de servicio (login de metadatos, acceso a Bedrock) | Secrets Manager | **DPAPI** (ámbito de la cuenta de servicio) o Windows Credential Manager; Bedrock con **IAM Roles Anywhere** y un certificado de la PKI corporativa, sin claves de larga duración |
| Cuentas de servicio | Roles IAM | **gMSA** (cuentas de servicio administradas por grupo), sin contraseñas que rotar a mano |
| Sandbox de análisis (F20) | AgentCore Code Interpreter | **No en la v1** (solo biblioteca determinista); después, contenedor aislado con Hyper-V |
| Consultas de usuarios | Transit GW + VPN/DX | **Directas** por TDS 1433; contra la **secundaria legible de Always On** (`ApplicationIntent=ReadOnly`) cuando exista |
| Observabilidad | AgentCore Observability → CloudWatch | Logs JSON rotados + **Visor de eventos de Windows**; vistas SQL de métricas en la BD `ConverData` |

## Alcance funcional del MVP
El MVP sigue el orden de valor de la propuesta: **primero descubrimiento, después consulta**.

**Fase 1a, piloto de descubrimiento (semanas 0–8 de F25)**, con `features.ask_flow: false`:
- F1 + F18 (catálogo con ambientes y servidores), F2, F3 (intent `discovery`), F19 (entidades entre BDs).
- F22 DiscoverFlow, F23 fuentes de conocimiento (diccionarios, documentos, SSIS/SQL Agent, reglas), F24 curación y escalamiento.
- F11, F12 (`/discover`, tarjetas de candidatos, Curación, Métricas), F14: el descubrimiento hereda los permisos del login del usuario (también para metadatos).
- F25: línea base y métricas desde el primer día.
- Dominio piloto: **clientes / onboarding digital** (el ejemplo de la propuesta), en producción y QA.

**Fase 1b, consulta de datos** (si 1a cumple sus criterios de salida). **Incluye**:
- F1 Catalog Builder (muestras solo en memoria; el catálogo nunca lleva valores).
- F2 memoria en la BD `ConverData` (OP-02).
- F3 a F10 completos (intent, linking, values en vivo, planner, validator con bucle de corrección, executor, verifier con juez y analyst).
- F20 con la biblioteca de análisis determinista (sin código libre) y F21 capa semántica.
- F11 en el esquema `audit` (OP-05).
- F12 Chainlit + `/ask` + `/mcp` (OP-04).
- F14 con SessionVault (OP-03).

**Fuera del alcance on-premise**: alta disponibilidad del servidor de aplicación, SSO, `candidates: 2`, código Python libre, fallback automático a NIM con datos reales.

**Datos**: 1 o 2 bases de datos piloto (no las 300+ tablas de golpe). Primero **AdventureWorks** restaurada en una instancia de desarrollo para validar el pipeline; después una BD real en **réplica o copia de solo lectura**.

## Topología
```
Windows Server 2022/2025 — servidor de aplicación (red corporativa)
├─ IIS :443 (TLS PKI corporativa) ── proxy inverso (HttpPlatformHandler)
│   ├─ /            → servicio ConverData-UI   (Chainlit)
│   └─ /api  /mcp   → servicio ConverData-API  (FastAPI + AskFlow + converdata-mcp + SessionVault)
├─ servicio ConverData-Discovery (converdata-discovery, solo localhost)
└─ Python 3.12 en un entorno gestionado con uv; servicios con cuentas gMSA

SQL Server 2025 — BD ConverData (esquemas catalog, estate, semantic, golden, audit)
SQL Server de datos (versiones actuales) ◄── TDS 1433 con el login de cada usuario (réplica legible si existe)
SQL Server Agent ── job nocturno (PowerShell) ──► POST /api/admin/catalog/refresh ──► Catalog Builder en el servidor de aplicación
Amazon Bedrock ◄── HTTPS vía proxy corporativo (IAM Roles Anywhere)
```

## Dimensionamiento orientativo del servidor de aplicación
4 vCPU, 16 GB de RAM y 100 GB de disco para el piloto (3–20 usuarios). El cómputo pesado (LLM y embeddings) lo hace Bedrock; las
búsquedas vectoriales las hace SQL Server.

## Configuración AWS mínima
- **IAM Roles Anywhere** con el certificado del servidor emitido por la PKI corporativa (alternativa: usuario IAM con clave guardada con DPAPI).
- Política de **mínimo privilegio**: `bedrock:InvokeModel` y `bedrock:InvokeModelWithResponseStream` sobre los modelos o inference profiles elegidos, y nada más.
- Acceso a los modelos habilitado en Bedrock (Claude Sonnet/Haiku, Nova o Llama para el juez, Cohere Embed).
- **Model invocation logging desactivado** (F17).

## Residencia de datos en el MVP
Se cumple F17 de forma natural:
- Catálogo, vectores, grafo, auditoría y sesiones viven en la red corporativa (BD `ConverData` y memoria del servicio).
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

**Fase 1b, consulta de datos**:
| # | Prueba | Umbral |
|---|---|---|
| 1 | Set de evaluación de 30–50 preguntas reales con SQL de referencia (AdventureWorks, después la BD piloto) | Precisión de ejecución ≥ 80 % |
| 2 | Calibración: las respuestas con `confidence < 0.6` son las incorrectas | ≥ 70 % de las incorrectas quedan marcadas |
| 3 | Guardrails: batería de SQL maliciosos y de inyección de prompt | 0 ejecuciones indebidas |
| 4 | Permisos: dos usuarios con permisos distintos hacen la misma pregunta | Cada uno ve solo lo suyo; error 229 manejado |
| 5 | Latencia p50 / p95 | < 15 s / < 40 s |
| 6 | Coste Bedrock por pregunta | Medido y reportado (decide los modelos de prod) |
| 7 | Feedback de 3–5 usuarios piloto durante 2 semanas | ≥ 70 % 👍 |

## Camino a producción
Cada pieza on-premise tiene su equivalente directo en cloud native (CN-01 a CN-06), y la lógica (AskFlow, converdata-mcp, validator, prompts) no cambia:
- `SqlServerVectorStore` pasa a `OpenSearchStore`, mediante la misma interfaz `VectorStore`.
- `SessionVault` pasa a Secrets Manager.
- El esquema `audit` pasa a `ConverData_Audit` (on-prem en ambos casos).
- Los servicios de Windows pasan a AgentCore Runtime (AskFlow) y Runtime + Gateway (MCP).

Alternativamente, el despliegue on-premise puede quedarse como producción si la organización prefiere no usar la nube: entonces se añaden un segundo servidor de aplicación detrás de un balanceador y el grupo de disponibilidad de SQL Server para la BD `ConverData`.
