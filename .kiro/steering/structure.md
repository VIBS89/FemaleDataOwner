---
inclusion: always
---

# Estructura del repositorio

| Ruta | Contenido |
|---|---|
| `src/discovery_data_agent/flows/` | CatalogBuildFlow y DiscoverFlow (LangGraph) |
| `src/discovery_data_agent/discovery/` | Lógica determinista: expansión, calificación, revisor, confianza, guardas, asistente, cifras |
| `src/discovery_data_agent/llm/` | Gateway de LLM y nodos que usan el modelo |
| `src/discovery_data_agent/graph/` | Grafo del patrimonio: entidades, copias canónicas, caminos de unión |
| `src/discovery_data_agent/identity/`, `audit/` | Visibilidad por login SQL y auditoría fail-closed |
| `src/discovery_data_agent/integration/mcp/` | Servidor MCP (10 herramientas de solo lectura) |
| `src/discovery_data_agent/storage/`, `db/discovery_data_agent/` | Repositorios y migraciones de la BD `DiscoveryDataAgent` |
| `api/discovery_data_agent_api/` | DiscoveryDataAgent-API (FastAPI) |
| `web/` | Chat, catálogo, curación, métricas y administración |
| `deploy/aws/` | Terraform y `despliegue.sh` |
| `tests/`, `api/tests/` | Pruebas y fixtures (`bancos`, `vbank`) con sus sets de evaluación |
| `docs/specs/` | Specs detalladas F01–F25, OP-01–OP-09, CN-01–CN-06 |
| `.kiro/specs/` | Specs de Kiro (requisitos, diseño, tareas) de cada funcionalidad |

## Capas
Dominio → aplicación → infraestructura → integración ([docs/architecture/capas-backend.md](../../docs/architecture/capas-backend.md)).
Una capa interna nunca importa una externa; `tests/test_architecture.py` lo comprueba.
