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
| **Dominio** | Modelos (`AnswerEnvelope`, catálogo, conocimiento, identidad), reglas de negocio deterministas del descubrimiento (F22), texto común (`memory.text`: `tokenize` y, desde el 2026-11-17, `strip_literals(question, known)` y `has_literals`, que quitan de una pregunta toda palabra con algún dígito o con arroba que no esté en el vocabulario `known`; el vocabulario lo dan `Catalog.names_with_digits` y `KnowledgeBase.codes` (`catalog.store`) y lo pasa quien llama; los usan `discovery.expansion` para no contarlos como conceptos y `curation` para la plantilla anónima), reglas de la curación (F24: plantilla anónima, regla de votos, ediciones de descripciones y diccionarios) con sus puertos `KnowledgeWriter` y `CurationRepository`, los puertos del catálogo (`CatalogRepository`, con `description_history`, e `InventoryStore`), grafo del patrimonio (F19), conversión de metadatos a catálogo (F1), lectura de objetos visibles (F14), auditoría como puerto (F11) y puertos | `models`, `catalog`, `config`, `discovery`, `curation`, `graph`, `builder`, `identity`, `audit`, `memory.base` y `memory.text`, `metadata.ports` |
| **Aplicación** | Casos de uso: flujos de LangGraph (DiscoverFlow, CatalogBuildFlow), consultas de descubrimiento que comparten la API, el chat y el MCP (`application.discovery`) y el refresco del catálogo que comparten la CLI y la API (`application.catalog_refresh.refresh_catalog`) | `flows`, `application` |
| **Infraestructura** | Adaptadores: SQL Server (`SqlServerMetadata`, `SqlServerAuditSink`, `SqlServerCatalogRepository`, `SqlServerCurationRepository`, migraciones), los mismos puertos de curación sobre archivos para desarrollo y demo (`storage.files`: `FileKnowledgeWriter`, `FileCurationRepository`, `FileInventoryStore`), índice léxico en memoria, gateway de LLM (Bedrock, NIM, Ollama), logs y contadores | `memory.memory_store`, `metadata.sqlserver`, `audit.sqlserver`, `audit.chain`, `storage`, `llm`, `observability` |
| **Integración** | Entradas al sistema: MCP (`integration.mcp`), CLI, evaluación offline y la raíz de composición (`bootstrap`: `build_service*` ensambla el DiscoverFlow, desde YAML (`build_service`), desde la BD (`build_service_from_db`) o desde YAML más un directorio de fuentes de conocimiento que se añaden sin tocar el catálogo (`build_service_with_knowledge`, para `discovery-data-agent eval discovery --knowledge`), y `open_stores` devuelve los almacenes `Stores` del catálogo, de la curación y del inventario, SQL Server con la cadena de la BD y archivos sin ella; con la BD comprueba antes que no falten migraciones, `require_current`). La API FastAPI (`api/discovery_data_agent_api`) es también integración | `integration`, `cli`, `bootstrap`, `evaluation`, `api/` |

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
  - **HTTP** (`streamable_http_app` + `require_bearer`): para montar en `/mcp` de `DiscoveryDataAgent-API`; sin `Bearer` válido, 401.
    La protección contra *DNS rebinding* del SDK exige declarar el nombre del servidor de IIS en `transport_security`.
  - **stdio** (`discovery-data-agent mcp serve`): Claude Desktop o Claude Code en local, con identidad fija de desarrollo; se
    niega con `DISCOVERY_DATA_AGENT_ENV=qa|prod`.
- Ejemplo de configuración para Claude: [`config/mcp.example.json`](../../config/mcp.example.json).

## Pruebas por capa
| Capa | Pruebas |
|---|---|
| Arquitectura | `tests/test_architecture.py`: cada módulo tiene capa, las dependencias apuntan hacia dentro, sin librerías de adaptadores en dominio y aplicación |
| Dominio | `tests/test_core.py`, `tests/test_graph_rag.py` (incluye las preguntas por una entidad, de cruce y los calificativos desconocidos, y la medición con y sin fuentes de conocimiento), `tests/test_catalog_build.py`, `tests/test_llm_guards.py`, `tests/test_prompt_injection.py`, `tests/test_curation.py` (plantilla anónima, regla de votos, ediciones; también los adaptadores de archivos) |
| Aplicación | `tests/test_application_discovery.py` (permisos de cada herramienta), `tests/test_discover_flow_e2e.py`, `tests/test_catalog_refresh.py` (`refresh_catalog`, y la CLI contra la BD con `DISCOVERY_DATA_AGENT_TEST_DB`) |
| Infraestructura | `tests/test_storage_migrations.py`, `tests/test_catalog_repository.py`, `tests/test_audit_sqlserver.py` (con `DISCOVERY_DATA_AGENT_TEST_DB`, contra un SQL Server real), `tests/test_llm_gateway.py`, `tests/test_observability.py` |
| Integración | `tests/test_mcp_server.py` (HTTP con el cliente MCP oficial: 401, identidad del token, sesión revocada), `tests/test_mcp_stdio.py` (incluye lanzar `discovery-data-agent mcp serve` como proceso) y `api/tests/` (`test_audit_db.py` y `test_catalog_db.py` con la BD `DiscoveryDataAgent` real; `test_marked_literals.py`, la prueba de literales marcados de punta a punta, en archivos y en la BD real) |
| Cadena de suministro | `tests/test_supply_chain.py`: dependencias con versión y hash (también las herramientas de la CI, `tools.lock`), cada `pip install` con hashes y `--only-binary`, imágenes por digest, acciones por commit ([`requirements/README.md`](../../requirements/README.md)) |

## Deuda conocida
- `catalog.store` mezcla el modelo del catálogo (`Catalog`, `CatalogSnapshot`, el puerto `CatalogRepository`) con su carga desde YAML
  (`load_snapshot`), y `builder.catalog_builder.write_snapshot` escribe YAML desde el dominio. Son el formato de desarrollo y el área de
  trabajo del Builder; si crecen, pasan a un adaptador de archivos en infraestructura.
- `identity.visibility.PyodbcObjectLister` vive en el dominio porque recibe la conexión inyectada; si crece, pasa a infraestructura.
- La API (`api/discovery_data_agent_api`) todavía llama directamente al DiscoverFlow; debe pasar por `DiscoveryTools` (HU-14, HU-16).
  El MCP montado en `/mcp` ya lo hace.
- Cada escritura de curación escribe solo sus filas, pero después la API vuelve a cargar el catálogo completo de la BD y reconstruye
  el índice (`runtime._written`; tras el voto de un usuario, en segundo plano). En catálogos grandes convendrá actualizar solo lo
  que cambió.
- La política de sincronización con la BD (`_pull`, `refresh`, `editing`, `_written` en `api/discovery_data_agent_api/runtime.py`) es lógica de
  aplicación que sigue en la API. Lo mismo la orquestación de votos (`record_feedback`, `steward_golden` en `runtime.py`): debería
  ser un caso de uso de `discovery_data_agent.application`.
- `open_stores` solo lo usa la API. `cli.py` todavía construye `SqlServerCatalogRepository` y `SqlServerAuditSink` por su cuenta, y la
  auditoría de la API se abre en `api/discovery_data_agent_api/audit.py`.
- `flows.catalog_build` lee el linaje anterior directamente del directorio de salida (`load_knowledge`) cuando un servidor no responde.
- `tests/test_architecture.py` no analiza `api/discovery_data_agent_api`: la regla de dependencias solo se verifica en `src/discovery_data_agent`.
- La API se asume de un solo proceso: sesiones, trazas, inventario y confirmaciones recientes viven en memoria (el inventario se
  lee al arrancar).

Resuelto el 2026-11-17 (bloque C2): la copia de trabajo del catálogo en disco y la publicación completa tras cada edición; la curación
y el inventario en archivos del servidor con `DISCOVERY_DATA_AGENT_DB`; el caso de uso "traer de la BD → build → publicar" repetido en la CLI y
en la API. Se retiraron el canal de embeddings de `memory.memory_store` (la medición de HU-34 ya no se puede repetir con este código)
y `identity.VisibilityResolver`: la visibilidad por sesión la calcula `AgentRuntime.visible_ids` con `ObjectLister`. El inventario y
`description_history` ya están en puertos (`InventoryStore`, `CatalogRepository`), y `runtime.py` ya no lee ni escribe YAML.

Segunda tanda del 2026-11-17: `strip_literals` y `has_literals` pasaron de `curation` a `memory.text` (`curation` los reexporta), para
que `discovery.expansion` los use sin que el descubrimiento dependa de la curación. `memory.text` no conoce el catálogo: recibe el
vocabulario como argumento. El descubrimiento le pasa los nombres con dígitos de lo que el usuario ve
(`names_with_digits(visible_ids)`, en `flows.discover` y `engine`); la API, el catálogo entero más los códigos del conocimiento
(`AgentRuntime._vocabulary`, en `api/discovery_data_agent_api/runtime.py`). `engine.entity_kind_hint` consulta el catálogo
visible y lo llama el nodo `intent` de `flows.discover` (aplicación → dominio).
