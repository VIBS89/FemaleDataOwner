# CN-01 — Despliegue cloud native en AWS (Bedrock AgentCore)

> Diagrama: `docs/architecture/cloud-native-architecture.html` · Specs relacionadas: [CN-02](CN-02-catalogo-memoria.md) catálogo y memoria · [CN-03](CN-03-identidad.md) identidad · [CN-04](CN-04-interfaces.md) interfaces · [CN-05](CN-05-auditoria-observabilidad.md) auditoría · [CN-06](CN-06-residencia-datos.md) residencia de datos

## Objetivo
Llevar ConverData a AWS como servicio gestionado y seguro:
- los agentes CrewAI corren en **Amazon Bedrock AgentCore Runtime**;
- las herramientas se publican como MCP mediante **AgentCore Gateway**;
- el LLM principal es **Amazon Bedrock** (ver [F16](../comun/F16-llm-providers.md));
- la memoria semántica vive en **OpenSearch Serverless**;
- **SQL Server permanece on-premise**, accesible por Site-to-Site VPN o Direct Connect.

## Decisiones
| Tema | Decisión | Motivo |
|---|---|---|
| Runtime de agentes | AgentCore Runtime (contenedor ARM64 en ECR con el **DiscoverFlow (F22)** y el AskFlow de CrewAI) | Aislamiento por sesión en microVM, sesiones largas, escalado gestionado, soporte para cualquier framework |
| Servidor MCP propio | `converdata-mcp` desplegado como **MCP server en AgentCore Runtime** y registrado como target de **AgentCore Gateway** | Un único endpoint MCP, con autenticación OAuth, para los agentes internos y los clientes externos |
| `converdata-discovery` (F18, propio, Apache-2.0) | Dentro de la tarea ECS del Catalog Builder (como biblioteca) o como servicio ECS privado | Solo ingesta y descubrimiento (F1, F19); usa el login de metadatos |
| Sandbox de análisis (F20) | **AgentCore Code Interpreter** | Ejecución aislada por sesión de código Python de último recurso |
| Catalog Builder | Tarea ECS Fargate lanzada por **EventBridge Scheduler** (nocturna) y bajo demanda mediante Step Functions | Proceso batch largo, fuera del camino interactivo |
| Catálogo fuente (YAML) | **S3** versionado (`s3://converdata-catalog/`), **solo metadatos estructurales, sin `sample_values`** | Revisión humana, historial y fuente para reindexar |
| Memoria semántica | **OpenSearch Serverless** (colección *vector search*, endpoint VPC) | k-NN + BM25 híbrido con filtros por metadatos (`visible_ids`) |
| Memoria conversacional | **Solo en la memoria de la sesión** de AgentCore Runtime (microVM); **no se usa AgentCore Memory** | Residencia de datos (F17): el historial contiene datos |
| Auditoría y golden SQL (F11) | **BD `ConverData_Audit` en SQL Server on-prem** (vía VPN/DX) | Residencia de datos (F17): preguntas y SQL con literales no se guardan en AWS |
| Conocimiento y curación (F23, F24) | Ingesta de documentos, diccionarios y ETL en la tarea ECS del Catalog Builder, con redacción de PII **antes** de salir de la red del banco; reglas, anotaciones y `golden_discovery` (plantillas) en S3 + OpenSearch; solicitudes de curación (contienen la pregunta) en `ConverData_Audit` on-prem | Residencia de datos (F17) y conocimiento revisable |
| UI y API REST | **Chainlit + FastAPI BFF** en ECS Fargate detrás de **ALB** con autenticación Cognito (OIDC) y **AWS WAF** | Sesiones WebSocket/SSE de Chainlit; el BFF invoca `InvokeAgentRuntime` |
| Usuarios | **Amazon Cognito** (federable con el IdP corporativo, por ejemplo Entra ID o Google) | JWT de entrada para el ALB, AgentCore Runtime y Gateway |
| Credenciales SQL por usuario | Secrets Manager + KMS (CN-03) | Herencia de permisos (F14) |
| Red | VPC con subredes privadas, **Transit Gateway** hacia VPN o Direct Connect on-prem, VPC endpoints (Bedrock, S3, Secrets Manager, OpenSearch, ECR, CloudWatch, KMS), NAT solo para el fallback a NIM | Sin tráfico de datos por internet |
| Observabilidad | **AgentCore Observability** (OTel) → CloudWatch / X-Ray, más dashboards de CloudWatch | Trazas por paso del flow, tokens y latencias |
| Seguridad del LLM | **Bedrock Guardrails** (prompt-attack, PII, temas denegados) en las entradas y salidas del usuario | Defensa contra inyección de prompt sobre datos |
| IaC | AWS CDK (Python) o Terraform; un stack por entorno (dev/stg/prod) | Reproducible |

## Topología de red
```
Usuarios ──HTTPS──► CloudFront? (opcional) ─► WAF ─► ALB (Cognito auth)
                                                     └─► ECS Fargate: Chainlit + FastAPI BFF
                                                            └─► AgentCore Runtime: AskFlow (CrewAI)
                                                                   ├─► Bedrock (VPC endpoint)
                                                                   └─► AgentCore Gateway (MCP)
Clientes MCP (Claude, IDE) ──OAuth──────────────────────────────────────┘    └─► converdata-mcp (AgentCore Runtime, modo VPC)
                                                                                    ├─► OpenSearch Serverless (VPC endpoint)
                                                                                    ├─► Secrets Manager (credenciales por usuario)
                                                                                    └─► Transit GW ─► VPN/DX ─► SQL Server on-prem (datos + ConverData_Audit)
EventBridge Scheduler ─► ECS task Catalog Builder + converdata-discovery ─► SQL Server on-prem (metadatos, Query Store)
                                         └─► S3 catálogo ─► OpenSearch (indexación)
```

## Requisitos no funcionales
- **Latencia**: descubrimiento (F22) p50 < 5 s y p95 < 10 s; consulta de datos p50 menor de 12 s y p95 menor de 30 s, con streaming de pasos al UI.
- **Disponibilidad**: 99,5 %; ECS en 2 AZ. AgentCore y Bedrock son servicios gestionados. La disponibilidad también depende de la VPN/DX y del SQL Server on-prem (datos y auditoría).
- **Coste**: se etiqueta todo con `app=converdata` y `env`; presupuesto con AWS Budgets y alertas; límite de tokens por usuario y día en el BFF.
- **Cumplimiento**: **cero persistencia de datos de clientes en AWS** (ver [F17](../comun/F17-data-residency.md) y CN-06). Model invocation logging de Bedrock **desactivado**. Cifrado KMS en reposo en todo lo que sí persiste (metadatos, plantillas y credenciales).
- **Red on-prem**: el firewall solo abre el puerto 1433 hacia los CIDR de las subredes de AgentCore (modo VPC) y del Catalog Builder.

## Entornos
| Entorno | Diferencias |
|---|---|
| dev | Despliegue on-premise (ver `docs/specs/on-premise/`) |
| stg | Stack completo de AWS, contra una copia o réplica de SQL Server |
| prod | Stack completo; WAF con rate limiting; alarmas en PagerDuty o correo; fallback a NIM desactivado (F17) |

La capa `VectorStore` (F2) tiene dos implementaciones (`OpenSearchStore` aquí, `SqlServerVectorStore` on-premise) y se elige por configuración.

## Criterios de aceptación
1. `cdk deploy` (o `terraform apply`) crea el entorno stg completo sin pasos manuales, salvo la VPN o DX y el alta de la app en el IdP.
2. Ningún componente con datos tiene IP pública; la prueba de Security Hub o Config no muestra hallazgos críticos.
3. Desde AgentCore Runtime (modo VPC) se completa una consulta a SQL Server on-prem con el login del usuario.
4. Un cliente MCP externo autenticado con Cognito invoca `ask` a través de AgentCore Gateway.
5. Las trazas de una pregunta se ven de punta a punta en CloudWatch (BFF → Runtime → Gateway → MCP → SQL).
6. Los criterios de aceptación de F22–F25 se cumplen en stg con el mismo set de evaluación de descubrimiento que on-premise.
