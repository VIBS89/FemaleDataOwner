# Capas del backend

> Creado: 2026-10-27. La regla de dependencias se verifica en cada ejecución de las pruebas: [`tests/test_architecture.py`](../../tests/test_architecture.py).
> Frontend (Next.js, `web/`) fuera de este documento.

## Regla
```
integración ──► aplicación ──► dominio ◄── infraestructura
```
Las dependencias apuntan hacia el dominio. El dominio define **puertos** (Protocols) y la infraestructura los implementa;
la integración es la única capa que conoce a todas y conecta adaptadores con casos de uso (raíz de composición).
El dominio y la aplicación no importan librerías de adaptadores (`pyodbc`, `langchain_*`, `fastapi`, `starlette`, `mcp`,
`httpx`, `boto3`); la aplicación sí usa LangGraph para orquestar.

| Capa | Qué contiene | Módulos |
|---|---|---|
| **Dominio** | Modelos (`AnswerEnvelope`, catálogo, conocimiento, identidad), reglas de negocio deterministas del descubrimiento (F22), grafo del patrimonio (F19), conversión de metadatos a catálogo (F1), visibilidad (F14), auditoría como puerto (F11) y puertos | `models`, `catalog`, `config`, `discovery`, `graph`, `builder`, `identity`, `audit`, `memory.base` y `memory.text`, `metadata.ports` |
| **Aplicación** | Casos de uso: flujos de LangGraph (DiscoverFlow, CatalogBuildFlow) y consultas de descubrimiento que comparten la API, el chat y el MCP | `flows`, `application` |
| **Infraestructura** | Adaptadores: SQL Server (`SqlServerMetadata`, `SqlServerAuditSink`, `SqlServerCatalogRepository`, migraciones), índice léxico en memoria, gateway de LLM (Bedrock, NIM, Ollama), logs y contadores | `memory.memory_store`, `metadata.sqlserver`, `audit.sqlserver`, `audit.chain`, `storage`, `llm`, `observability` |
| **Integración** | Entradas al sistema: MCP (`integration.mcp`), CLI, evaluación offline y la raíz de composición (`bootstrap`). La API FastAPI (`api/converdata_api`) es también integración | `integration`, `cli`, `bootstrap`, `evaluation`, `api/` |

## Capa de integración: API y MCP sobre el mismo caso de uso
```
Claude / IDE ──MCP──► integration.mcp ─┐
Next.js ──HTTP──────► api (FastAPI) ───┼──► application.discovery.DiscoveryTools ──► flows.discover (DiscoverFlow)
Terminal ───────────► cli ─────────────┘                                          └─► dominio (catálogo, grafo, reglas)
```
- `application.discovery.DiscoveryTools` es el único camino: `discover`, `get_asset`, `get_related`, `find_alternatives`,
  `list_business_rules`, `get_lineage`, `search_catalog`, `where_is`, `find_join_path`, `estate_overview` (F12).
- Cada herramienta recibe un `UserContext` que pone la integración a partir de la sesión autenticada. Ninguna acepta
  identidad como argumento (OP-03 CA5) y lo no visible responde igual que lo inexistente (F14).
- `integration.mcp.server.build_mcp_server` publica esas herramientas como MCP (SDK oficial `mcp` 2.x, `MCPServer`):
  - **HTTP** (`streamable_http_app` + `require_bearer`): para montar en `/mcp` de `ConverData-API`; sin `Bearer` válido, 401.
    La protección contra *DNS rebinding* del SDK exige declarar el nombre del servidor de IIS en `transport_security`.
  - **stdio** (`converdata mcp serve`): Claude Desktop o Claude Code en local, con identidad fija de desarrollo; se
    niega con `CONVERDATA_ENV=qa|prod`.
- Ejemplo de configuración para Claude: [`config/mcp.example.json`](../../config/mcp.example.json).

## Pruebas por capa
| Capa | Pruebas |
|---|---|
| Arquitectura | `tests/test_architecture.py`: cada módulo tiene capa, las dependencias apuntan hacia dentro, sin librerías de adaptadores en dominio y aplicación |
| Dominio | `tests/test_core.py`, `tests/test_graph_rag.py`, `tests/test_catalog_build.py`, `tests/test_llm_guards.py`, `tests/test_prompt_injection.py` |
| Aplicación | `tests/test_application_discovery.py` (permisos de cada herramienta), `tests/test_discover_flow_e2e.py` |
| Infraestructura | `tests/test_storage_migrations.py`, `tests/test_catalog_repository.py`, `tests/test_audit_sqlserver.py` (con `CONVERDATA_TEST_DB`, contra un SQL Server real), `tests/test_llm_gateway.py`, `tests/test_observability.py` |
| Integración | `tests/test_mcp_server.py` (HTTP con el cliente MCP oficial: 401, identidad del token, sesión revocada), `tests/test_mcp_stdio.py` (incluye lanzar `converdata mcp serve` como proceso) y `api/tests/` (`test_audit_db.py` y `test_catalog_db.py` con la BD `ConverData` real) |

## Deuda conocida
- `catalog.store` mezcla el modelo del catálogo (`Catalog`, `CatalogSnapshot`, el puerto `CatalogRepository`) con su carga desde YAML
  (`load_snapshot`), y `builder.catalog_builder.write_snapshot` escribe YAML desde el dominio. Son el formato de desarrollo y el área de
  trabajo del Builder; si crecen, pasan a un adaptador de archivos en infraestructura.
- `identity.visibility.PyodbcObjectLister` vive en el dominio porque recibe la conexión inyectada; si crece, pasa a infraestructura.
- La API (`api/converdata_api`) todavía llama directamente al DiscoverFlow; debe pasar por `DiscoveryTools` (HU-14, HU-16).
  El MCP montado en `/mcp` ya lo hace.
- Con `CONVERDATA_DB`, la API trabaja sobre una **copia de trabajo en disco** (`data_root`) que trae de la BD y publica entera tras cada
  edición (`runtime.commit`). Es correcto (la BD es la fuente de verdad, con bloqueo y versión esperada) pero costoso en catálogos
  grandes: cada voto compara todo el catálogo. El siguiente paso es que `CurationStore` escriba filas concretas.
- `CurationStore` (`api/converdata_api/curation.py`) guarda en archivos los responsables, las solicitudes escaladas y los votos, y
  `runtime` el inventario de servidores: falta llevarlos a la BD (migración `002`).
- La política de sincronización con la BD (`_pull`, `refresh`, `editing`, `commit` en `api/converdata_api/runtime.py`) y el caso de uso
  "traer de la BD → build → publicar" son lógica de aplicación que hoy vive en la API y, repetida, en `cli.py`. Deben pasar a un caso de
  uso en `converdata.application`, y la construcción de los adaptadores de SQL Server (hoy en `cli.py`, `runtime.py`, `audit.py` y
  `bootstrap.py`) a dos fábricas en `bootstrap.py`.
- `flows.catalog_build` lee el linaje anterior directamente del directorio de salida (`load_knowledge`) cuando un servidor no responde.
- El puerto `CatalogRepository` no incluye `description_history`, que solo existe en el adaptador de SQL Server y aún no tiene interfaz.
- El canal de embeddings de `memory.memory_store` no se despliega (PRD §13, decisión 9); se conserva para repetir la medición.
