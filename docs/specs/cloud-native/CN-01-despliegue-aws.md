# CN-01 — Despliegue mínimo en AWS (posterior al piloto)

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Despliegue posterior al piloto on-premise; nada está desplegado.
>
> Diagrama: `docs/architecture/cloud-native-architecture.html` · Specs relacionadas: [CN-02](CN-02-catalogo-memoria.md) catálogo y memoria · [CN-03](CN-03-identidad.md) identidad · [CN-04](CN-04-interfaces.md) interfaces · [CN-05](CN-05-auditoria-observabilidad.md) auditoría · [CN-06](CN-06-residencia-datos.md) residencia de datos · equivalente on-premise: [OP-01](../on-premise/OP-01-despliegue-local.md)

## Objetivo
Ejecutar en AWS **el mismo código del piloto on-premise** (fase 1a, descubrimiento) cambiando solo dónde corren los procesos y quién
los programa: las dos imágenes que ya construye `docker compose` (`web/Dockerfile`, `api/Dockerfile`) en una tarea de ECS Fargate.
**Todo lo persistente se queda en el SQL Server del banco**; AWS procesa y muestra. Dimensionado para 10–15 usuarios.

## Decisiones
| Tema | Qué se usa | Motivo | PRD §13 |
|---|---|---|---|
| Cómputo | **Una tarea ECS Fargate** con dos contenedores: Web (Next.js, 3000) y `DiscoveryDataAgent-API` (FastAPI + DiscoverFlow de LangGraph + MCP en `/mcp`, 8000, un worker) | El flujo es un grafo de pasos fijos que cabe en un proceso. Una sola tarea porque el SessionVault vive en memoria | decisión 11 |
| Entrada | **ALB interno** con certificado de ACM; `/` → Web, `/mcp` → API | No se publica en internet. Equivale a IIS con la PKI corporativa | decisión 11 |
| Búsqueda | Índice léxico **BM25 en memoria** de la API, sin embeddings | HU-34: los embeddings no mejoran el acierto y suben la latencia | decisión 9 |
| Persistencia | **BD `DiscoveryDataAgent` en el SQL Server del banco** (catálogo con historial, conocimiento, curación, esquema `audit`; tablas normales, SQL Server 2016+) | AWS no persiste catálogo, preguntas ni auditoría; migrar entre despliegues es mover contenedores | decisión 10 |
| Builder | La imagen de la API ejecutando `discovery-data-agent catalog build`, lanzada por **EventBridge Scheduler** (`RunTask`); corre y termina | Equivale al Programador de tareas de Windows | decisión 12 |
| LLM | **Bedrock, un modelo** (intención y orden) por **VPC endpoint** con el rol de la tarea; invocation logging desactivado | Mismo uso que on-premise, sin claves ni salida a internet | decisión 13 |
| Identidad | El mismo login SQL por servidor y el SessionVault en memoria ([CN-03](CN-03-identidad.md)) | Los permisos los define SQL Server | decisión 11 |
| Secretos | **Secrets Manager**, solo secretos de servicio | Equivale a DPAPI | decisión 14 |
| Logs | **CloudWatch Logs**, JSON sin contenido | Equivale a logs rotados + Visor de eventos | decisión 14 |
| Red | Una VPC con subredes privadas y **Site-to-Site VPN** al banco; VPC endpoints (Bedrock, Secrets Manager, CloudWatch Logs, ECR); sin NAT | Sin tráfico por internet | decisión 11 |

### Qué se quitó frente a la versión anterior
| Se quitó | Motivo |
|---|---|
| AgentCore Runtime y Gateway | El DiscoverFlow y el servidor MCP ya viven en `DiscoveryDataAgent-API` (decisión 11) |
| AgentCore Code Interpreter | Era el sandbox de F20, que es de la fase 1b; se decidirá con la fase 1b (decisión 16) |
| OpenSearch Serverless | Búsqueda léxica en memoria (decisión 9) |
| S3 para catálogo y conocimiento, Lambda indexador | El catálogo se escribe en la BD `DiscoveryDataAgent` (decisión 10) |
| BD `DiscoveryDataAgent_Audit` separada | La auditoría es el esquema `audit` de la BD `DiscoveryDataAgent` (decisión 10) |
| Cognito | El inicio de sesión es el login SQL por servidor (decisión 11) |
| WAF | El ALB es interno; los límites los aplica la API ([CN-04](CN-04-interfaces.md)) |
| Transit Gateway | Una sola VPC con Site-to-Site VPN (decisión 11) |
| Step Functions | El Builder es un `RunTask` programado (decisión 12) |
| Chainlit + BFF, embeddings, juez, NIM de respaldo, Guardrails como requisito | Web Next.js y un solo modelo en la fase 1a (decisión 13); Guardrails queda por confirmar |

## Topología
```
Red corporativa ──Site-to-Site VPN──► VPC (subredes privadas, sin internet)
  Usuario (navegador) ─HTTPS─► ALB interno (ACM) ─ /    ─► Web (Next.js) ─ /api → localhost:8000 ─┐
  Cliente MCP (Bearer) ─────►                     └ /mcp ─────────────────────────────────────────► DiscoveryDataAgent-API
                                                          [ una tarea ECS Fargate: Web + DiscoveryDataAgent-API ]
  DiscoveryDataAgent-API ─► Bedrock (VPC endpoint) · Secrets Manager · CloudWatch Logs
  DiscoveryDataAgent-API ─► VPN ─ TDS 1433 ─► SQL Server de datos (visibilidad del usuario) y BD DiscoveryDataAgent (catálogo, auditoría)
  EventBridge Scheduler ─RunTask─► Builder ─► VPN ─► SQL Server (metadatos), fuentes de conocimiento, BD DiscoveryDataAgent
```
El firewall on-premise solo abre el 1433 a las subredes de la tarea.

## Entornos
| Entorno | Dónde | Diferencias |
|---|---|---|
| dev | `docker compose` local u on-premise | `DISCOVERY_DATA_AGENT_ENV=dev`; admite modo demo |
| qa | AWS | `DISCOVERY_DATA_AGENT_ENV=qa`; contra SQL Server de QA |
| prod | AWS | `DISCOVERY_DATA_AGENT_ENV=prod`; alarmas activas ([CN-05](CN-05-auditoria-observabilidad.md)) |

Con `qa` o `prod` la API no arranca si falta algo de `docs/calidad-bancaria.md` §4 (`DISCOVERY_DATA_AGENT_COOKIE_SECURE=1`, CORS y
`DISCOVERY_DATA_AGENT_PUBLIC_URL` con la URL `https://` del ALB, `DISCOVERY_DATA_AGENT_MCP_HOSTS`, `DISCOVERY_DATA_AGENT_ADMINS_ONLY=1` + `DISCOVERY_DATA_AGENT_ADMINS`,
`DISCOVERY_DATA_AGENT_SETUP_TOKEN`, `DISCOVERY_DATA_AGENT_LOG_DIR`, `data_mode: real`, sin modo demo ni `trust_server_certificate`).

## Requisitos no funcionales
- **Latencia** del descubrimiento: p50 < 5 s y p95 < 10 s (F22), incluida la VPN.
- **Disponibilidad**: una sola tarea, sin alta disponibilidad. Si se reinicia, los usuarios vuelven a iniciar sesión y se pierden los contadores de ritmo y de tokens. Depende de la VPN y del SQL Server on-premise. Escalar a varias tareas exigiría sesiones compartidas.
- **Tamaño de la tarea**: por confirmar (referencia on-premise: 4 vCPU, 16 GB).
- **Coste**: etiquetas `app=discovery-data-agent` y `env`; tope diario de tokens por usuario en la API.

## Dependencias del código (pendientes)
1. ~~Persistir catálogo, curación y auditoría en la BD `DiscoveryDataAgent`~~ Hecho (HU-04, HU-06, HU-09, HU-20; 2026-11-17): con `DISCOVERY_DATA_AGENT_DB` la API no guarda estado en disco, que es lo que Fargate necesita. Falta probarlo en una tarea real.
2. Logs JSON a la salida estándar: hoy se escriben en un archivo rotado (`DISCOVERY_DATA_AGENT_LOG_DIR`) y en el Visor de eventos.
3. ~~Recarga del catálogo cuando el Builder corre en otra tarea, e inventario de servidores~~ Hecho: la API comprueba la versión publicada como mucho cada 15 s, y el inventario vive en la BD (`catalog.inventory_server`). Por confirmar: con qué identidad entra el Builder a los SQL Server desde AWS (`catalog build --db` usa la cuenta del proceso salvo `metadata_user_env`).
4. Probar el gateway de LLM con Bedrock (HU-35).

## IaC
**Nada está desplegado todavía.** El IaC existe desde el 2026-11-22 en `deploy/aws/` (Terraform, una pila por entorno; guía y
comandos en [`deploy/aws/README.md`](../../../deploy/aws/README.md)): VPC y endpoints, VPN, ALB + ACM, repositorios ECR, definición
de tarea y servicio ECS (1 tarea), definición de tarea del Builder + EventBridge Scheduler, secretos, grupos de logs y alarmas, roles
IAM (`bedrock:InvokeModel` sobre el modelo elegido y lectura de sus secretos). Solo está comprobado con `terraform validate` y planes
de prueba con el proveedor simulado; no se ha aplicado en ninguna cuenta. Además de qa y prod define un entorno `demo` (servidores
simulados, ALB público restringido por IP) para probar el despliegue sin la VPN del banco.

## Por confirmar con Seguridad de la Información
- **Guardrails** de Bedrock en la fase 1a: decisión pendiente, no es requisito (decisión 13).
- Si la **VPN** puede llevar tráfico de usuarios hacia el ALB, además del tráfico hacia SQL Server.

## Criterios de aceptación
1. El IaC crea el entorno qa completo sin pasos manuales, salvo la VPN y las reglas del firewall on-premise.
2. Ningún recurso tiene IP pública ni ruta a internet; el ALB es interno.
3. Un usuario de la red corporativa inicia sesión con su login SQL y recibe candidatos de `/discover` filtrados por sus permisos.
4. Con `DISCOVERY_DATA_AGENT_ENV=qa`, la tarea no arranca si falta alguna variable obligatoria.
5. Tras detener la tarea, no queda en AWS ningún catálogo, pregunta ni registro de auditoría ([CN-06](CN-06-residencia-datos.md)).
6. El set de evaluación de descubrimiento da en qa los mismos resultados que on-premise (`discovery-data-agent eval gate`).
