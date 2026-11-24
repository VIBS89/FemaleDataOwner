---
inclusion: always
---

# Tecnología

| Pieza | Tecnología |
|---|---|
| Orquestación del agente | LangGraph (solo en `discovery_data_agent.flows`) |
| LLM | Gateway propio sobre LangChain (solo en `discovery_data_agent.llm`): Amazon Bedrock, NVIDIA NIM u Ollama local, con respaldo, circuit breaker y guarda de residencia |
| API | FastAPI (`api/discovery_data_agent_api`) |
| Web | Next.js + shadcn (`web/`) |
| MCP | `discovery-data-agent-mcp` con el SDK oficial de MCP (stdio y `/mcp` con `Bearer`) |
| Persistencia | BD `DiscoveryDataAgent` en SQL Server 2016+ (catálogo, conocimiento, curación, inventario, auditoría) |
| Búsqueda | BM25 en memoria, sin embeddings (medido: no mejoran el acierto y suben la latencia) |
| Infraestructura AWS | Terraform en `deploy/aws/`: ECS Fargate, ALB, Bedrock por VPC endpoint, EventBridge Scheduler, ECR, Secrets Manager, CloudWatch, SNS, KMS, Site-to-Site VPN |

## Comandos
```bash
.venv/Scripts/python -m pytest -q                                              # pruebas
.venv/Scripts/python -m discovery_data_agent.cli eval gate --out reports       # compuerta de calidad (7 suites)
.venv/Scripts/python -m discovery_data_agent.cli eval discovery --root tests/fixtures/bancos   # Hit@1 / Hit@3
DISCOVERY_DATA_AGENT_DEMO=1 docker compose up --build                          # demo local en http://localhost:3000
bash deploy/aws/despliegue.sh deploy demo                                      # despliegue en AWS
```

## Reglas de código
- Dependencias con versión y hash fijados (`requirements/*.lock`); nada nuevo sin bloquearlo.
- El orden de los candidatos es determinista; el LLM reformula y redacta, no decide qué existe ni qué ve el usuario.
- Toda funcionalidad nueva entra con prueba primero (TDD) y no puede bajar la línea base de `eval gate`.
