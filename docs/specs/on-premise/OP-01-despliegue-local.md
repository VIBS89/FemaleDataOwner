# OP-01 — Despliegue on-premise (local)

> Diagrama: `docs/architecture/onpremise-architecture.html` · Specs relacionadas: [OP-02](OP-02-catalogo-memoria.md) catálogo y memoria · [OP-03](OP-03-identidad.md) identidad · [OP-04](OP-04-interfaces.md) interfaces · [OP-05](OP-05-auditoria-observabilidad.md) auditoría · [OP-06](OP-06-residencia-datos.md) residencia de datos
>
> Este despliegue sirve como **MVP** para validar la solución antes de invertir en la nube, y como opción on-premise.

## Objetivo
Probar **la hipótesis central**: que un conjunto de agentes CrewAI, sobre un catálogo extraído de SQL Server, responde preguntas en
lenguaje natural de forma **correcta, validada y con los permisos del usuario**. Todo corre en local, y de AWS solo se usa
**Amazon Bedrock** (LLM y embeddings) con la cuenta actual. Si el MVP valida la hipótesis, se migra a la arquitectura cloud native (CN-01)
sin rehacer la lógica (ver `docs/specs/cloud-native/`).

## Qué se mantiene y qué se simplifica
| Pieza | Cloud native (CN) | On-premise (OP) |
|---|---|---|
| Orquestación | AskFlow en AgentCore Runtime | **El mismo AskFlow** (CrewAI Flow) dentro del proceso FastAPI |
| Herramientas MCP | converdata-mcp en Runtime + AgentCore Gateway | **El mismo `converdata-mcp`** (FastMCP) montado en `/mcp` del mismo proceso; los agentes lo llaman en proceso |
| LLM | Bedrock por rol + Guardrails + NIM fallback | **Bedrock por rol** (misma `config/models.yaml`); Guardrails opcional; NIM solo con datos de prueba |
| Embeddings | Bedrock Cohere multilingüe | Bedrock Cohere multilingüe (alternativa sin nube: `paraphrase-multilingual-MiniLM-L12-v2` local) |
| Memoria semántica | OpenSearch Serverless | **ChromaDB embebida** (volumen local `./.chroma`) |
| Catálogo fuente | S3 versionado | **Carpeta `catalog/`** en git |
| Ingesta | EventBridge + ECS task | **Comando manual** `converdata catalog build/refresh` |
| sql-to-mcp | Fargate privado | **Contenedor AnythingMCP** en el mismo `docker compose` |
| Identidad de app | Cognito SSO | **Login de Chainlit** que valida el propio login SQL (sin IdP) |
| Credenciales SQL | Secrets Manager + KMS | **SessionVault en memoria** (Fernet, clave efímera); se pierde al reiniciar |
| Auditoría + golden SQL | ConverData_Audit on-prem | **SQLite local** (`./data/audit.db`), on-prem; mismo modelo de tablas (F11) |
| Red hacia SQL Server | Transit GW + VPN/DX | **Directa**: el equipo está en la red corporativa |
| Observabilidad | AgentCore Observability → CloudWatch | Logs JSON (structlog) en consola y archivo; trazas opcionales con Langfuse local |
| Seguridad perimetral | WAF + ALB + TLS | `localhost` o red interna; acceso solo para el equipo piloto |

## Alcance funcional del MVP
**Incluye**:
- F1 Catalog Builder (muestras solo en memoria; el YAML nunca lleva valores).
- F2 memoria en Chroma (OP-02).
- F3 a F10 completos (intent, linking, values en vivo, planner, validator con bucle de corrección, executor, verifier con juez y analyst).
- F11 en SQLite (OP-05).
- F12 Chainlit + `/ask` + `/mcp` (OP-04).
- F14 con SessionVault (OP-03).

**Fuera del alcance on-premise**: multi-réplica, alta disponibilidad, SSO, `candidates: 2`, fallback automático a NIM con datos reales.

**Datos**: 1 o 2 bases de datos piloto (no las 300+ tablas de golpe). Primero **AdventureWorks** en un contenedor para validar el pipeline; después una BD real en **réplica o copia de solo lectura**.

## Topología
```
docker compose (equipo en red corporativa)
├─ converdata-app   : Chainlit UI + FastAPI (/ask, /login, /feedback) + AskFlow + converdata-mcp (/mcp)
│                      volúmenes: ./.chroma  ./data/audit.db  ./catalog
├─ anythingmcp      : sql-to-mcp, login de metadatos (solo para la ingesta)
└─ sqlserver-dev    : (opcional) SQL Server 2022 + AdventureWorks para pruebas
SQL Server corporativo ◄── TDS 1433 directo (login de cada usuario)
Amazon Bedrock      ◄── HTTPS (perfil AWS con permiso solo bedrock:InvokeModel*)
```

## Configuración AWS mínima (la cuenta actual)
- Un perfil o rol IAM con política de **mínimo privilegio**: `bedrock:InvokeModel` y `bedrock:InvokeModelWithResponseStream` sobre los modelos/inference profiles elegidos, y nada más.
- Acceso a los modelos habilitado en la consola de Bedrock (Claude Sonnet/Haiku, Nova o Llama para el juez, Cohere Embed).
- **Model invocation logging desactivado** (F17).
- Credenciales en `~/.aws` o en variables de entorno del host. Nunca en el repositorio.

## Residencia de datos en el MVP
Se cumple F17 de forma natural:
- Chroma, catálogo, auditoría y sesión viven en el equipo on-prem.
- Bedrock solo procesa (sin logging).
- El YAML del catálogo no lleva valores.

El único dato que sale de la red es el contexto enviado a Bedrock en cada llamada.

## Plan de validación (criterios de salida del MVP)
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
- `ChromaStore` pasa a `OpenSearchStore`, mediante la misma interfaz `VectorStore`.
- `SessionVault` pasa a Secrets Manager.
- SQLite pasa a ConverData_Audit on-prem.
- El proceso único se divide en AgentCore Runtime (AskFlow) y Runtime + Gateway (MCP).
