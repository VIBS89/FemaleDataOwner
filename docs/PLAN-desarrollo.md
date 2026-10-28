# Plan de desarrollo — estado y cómo retomar

> Última actualización: 2026-10-25. Documento vivo: se actualiza al cerrar cada sesión de trabajo.
> Specs: [PRD](PRD.md), [comun/](specs/comun/), [on-premise/](specs/on-premise/). Uso diario: [README](../README.md#desarrollo).
> Backlog para terminar la versión on-premise (objetivos SMART e historias): [backlog/on-premise.md](backlog/on-premise.md).

## 1. Dónde estamos
Fase 1a on-premise (descubrimiento), núcleo implementado y medido. **262 tests en verde y 7 omitidos con motivo (SD-2 a SD-5)** (2026-10-27, `python -m pytest -q`; el conteo de 81 era anterior). Todo el código está **sin commit**
en `main` (ver §6).

| Pieza | Estado | Dónde |
|---|---|---|
| DiscoverFlow (F22) en LangGraph: `intent → retrieve ⇄ grade → rerank → expand ⇄ review → respond → finalize` | ✅ | `src/converdata/flows/discover.py` |
| Lógica determinista (recuperación, confianza F22, guardas, respaldos sin LLM) | ✅ | `src/converdata/discovery/` |
| Patrones de agentes medidos: expansión (D), descomposición, calificación/CRAG (C), revisor (B), cascada (E), grafo | ✅ | `discovery/expansion.py`, `discovery/engine.py`, `config.py: Patterns` |
| Agente de esquemas: CatalogBuildFlow `extract → enrich → relate → write` (F1, F18, F19) | ✅ probado contra SQL Server real | `flows/catalog_build.py`, `builder/`, `metadata/sqlserver.py` |
| Grafo del patrimonio (entidades, copias canónicas, caminos de unión con permisos) | ✅ en memoria | `src/converdata/graph/estate.py` |
| Gateway de LLM: Ollama (solo `environment: local`), NVIDIA NIM, Bedrock; respaldo, circuit breaker, guarda de residencia | ✅ Ollama probado; NIM y Bedrock sin probar con credenciales | `src/converdata/llm/` |
| Evaluación offline por tipo de pregunta (A–G) y ablación de patrones | ✅ | `src/converdata/evaluation/`, `tests/fixtures/*/eval/` |
| Auditoría fail-closed (F11), visibilidad por login (F14) | ✅ en memoria / lógica | `audit/`, `identity/` |
| DDL BD `ConverData` y `SqlServerVectorStore` | ⚠️ escrito, **sin validar** contra SQL Server 2025 | `db/converdata/001_esquemas.sql`, `memory/sqlserver_store.py` |

## 2. Resultados medidos
`converdata eval discovery` — Hit@1 sobre preguntas con respuesta.

| Catálogo | Hit@1 | Hit@3 | A directa | B vocabulario | C varios saltos (caminos) | D entidad | E exploración | G brechas |
|---|---|---|---|---|---|---|---|---|
| Fixture VBank (propuesta), 25 casos | 100 % | 100 % | — | — | — | — | — | 100 % |
| BancosSQL crudo, sin patrones/grafo (línea base) | 44,8 % | 69 % | 87,5 % | 25 % | 20 % (40 %) | 0 % | 75 % | 100 % |
| **BancosSQL crudo, todos los patrones + grafo** | **72,4 %** | **82,8 %** | 100 % | 25 % | 80 % (100 %) | 100 % | 75 % | 100 % |
| BancosSQL enriquecido por Qwen local, léxico | 72,4 % | 82,8 % | 100 % | 37,5 % | 60 % (100 %) | 100 % | 75 % | 100 % |

Siempre 0 fugas de permisos y 0 objetos inventados. Latencia determinista 20–45 ms por pregunta.

Lecciones que guían lo que sigue:
- El grafo resolvió D (copias de Clientes en 4 BDs) y C (caminos de unión); la **descomposición** de preguntas compuestas fue clave para C.
- Las descripciones generadas por LLM **empeoraban** la búsqueda léxica (62 %) hasta tratarlas como evidencia débil (×0.5).
  Su lugar natural es el **canal semántico (embeddings)**, que aún no se ha medido.
- Lo que falla hoy es casi todo **vocabulario**: "billetera" ↔ `Wallets`, "TC" = tarjeta de crédito, "tokenización" ↔ `Tokens`,
  "tasa de interés" ↔ `TasaAnual`.

## 3. Próximos pasos (en orden)
Orden por historias del backlog para el agente y su MCP: [§7](#7-orden-de-desarrollo-del-agente-y-su-mcp).

1. **Medir embeddings** (paso pendiente de esta sesión). Requiere `bge-m3` en Ollama (`ollama pull bge-m3`; la descarga
   quedó en curso, verificar con `ollama list`). Medir 4 combinaciones y quedarse con la mejor:
   ```bash
   # crudo / enriquecido × léxico / +embeddings
   converdata eval discovery --root tests/fixtures/bancos
   converdata eval discovery --root tests/fixtures/bancos --models config/models.embed.yaml --embeddings-only
   converdata eval discovery --root data/catalog_bancos_enriched --cases tests/fixtures/bancos/eval/discovery.yaml
   converdata eval discovery --root data/catalog_bancos_enriched --cases tests/fixtures/bancos/eval/discovery.yaml --models config/models.embed.yaml --embeddings-only
   ```
   Objetivo: subir B (vocabulario) sin bajar A/C/D/G. Si los embeddings suben B, ajustar el peso del canal semántico en RRF.
2. **Cobertura semántica**: hoy la cobertura (que decide la relevancia determinista) es solo léxica; con embeddings,
   agregar similitud concepto↔activo para que el ranking también se beneficie (no solo la recuperación).
3. **Explorador agéntico acotado (Agentic GraphRAG)**: solo si tras 1–2 el tipo E sigue < 85 %. Nodo con herramientas
   `vecinos`, `camino_entre`, `entidad`, `columnas_de`, máx. 3–4 pasos, filtrado por permisos, auditado (ver §5).
4. **Set de evaluación ampliado**: hoy 31 casos sobre BancosSQL armados por el equipo de desarrollo (sesgo de ajuste).
   Escribir 50–80 preguntas reales con usuarios del piloto (F25, OP-01 D1) antes de declarar resultados.
5. **Persistencia on-premise**: validar el DDL y `SqlServerVectorStore` en SQL Server 2025; mover el grafo a tablas de grafo
   (`NODE`/`EDGE`); escribir el catálogo en la BD `ConverData` además de YAML (OP-02).
6. **Interfaces**: API FastAPI (`/discover`, `/login` con SessionVault, `/assets`, `/discover/feedback`), Chainlit, MCP (F12, OP-03, OP-04).
7. **Curación y aprendizaje (F24)**: ✔/✖ → golden discovery, "Preguntar al responsable", vista Curación.
8. **Conectores de conocimiento (F23)**: diccionarios Excel/CSV, documentos con Presidio, SSIS/SQL Agent.

## 4. Cómo retomar (checklist)
```bash
cd converdata
.venv/Scripts/python -m pytest -q                       # debe dar 81 passed
ollama list                                              # ¿está bge-m3? si no: ollama pull bge-m3
sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "SELECT name FROM sys.databases WHERE database_id>4"   # 5 BDs Banca*
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos   # 72,4 % / 82,8 %
```
Luego seguir con el paso 1 de §3.

## 5. Decisiones de arquitectura vigentes
- **GraphRAG híbrido local orquestado como workflow** (no agente autónomo): búsqueda léxica + vectorial encuentra semillas,
  el grafo del patrimonio expande (FK, misma entidad, linaje) y une sub-preguntas; el LLM opina dentro de nodos y nunca
  decide el orden (PRD §8.1). Ciclos acotados: reformular (máx. 1), corregir (máx. 1).
- **Tres almacenes**: catálogo estructurado (fuente de verdad, historial), índice vectorial + Full-Text (fichas por columna con
  contexto de tabla; nunca DDL crudo ni valores), grafo (de metadatos, determinista; el LLM solo propone inferencias a revisar).
- **Texto generado por IA = evidencia débil** (cobertura ×0.5, confianza máx. 0.6 sin otra evidencia) hasta curación humana.
- **Una sola respuesta por dato replicado**: la copia canónica (más referenciada) con las demás en `copies`.
- **Ollama solo en local** (regla de código + `CONVERDATA_ENV`); NIM alojado solo con datos de prueba; Bedrock para datos reales.
- **Todo cambio de lógica se acepta solo si mejora el set de evaluación** sin bajar otros tipos ni crear fugas.

## 6. Estado del entorno local (no está en git)
| Elemento | Detalle |
|---|---|
| Código | Sin commit: `src/`, `tests/`, `config/` (salvo `models.yaml`), `db/`, `pyproject.toml`, `README.md`, `.gitignore`, este archivo |
| `.venv/` | Python 3.12 con langgraph, langchain-core/aws/ollama/nvidia, pyodbc, pytest |
| SQL Server Express local | `localhost\SQLEXPRESS` con 5 BDs de prueba cargadas desde `BancosSQL.zip` (BancaTarjetasCredito, BancaCuentasDebito, BancaTokenizacion, BancaLeasing, BancaPrestamos). Se eliminan con `DROP DATABASE` si hace falta |
| `data/` (ignorado) | `bancos_sql/` (scripts extraídos), `catalog_bancos/` (catálogo crudo), `catalog_bancos_enriched/` (enriquecido por Qwen, 8,6 min) |
| `config/models.yaml` (ignorado) | Ollama `qwen3.6:35b-a3b` para planner/fast/judge |
| `config/models.embed.yaml` | Solo embeddings `bge-m3` en Ollama |
| Ollama | `qwen3.6:35b-a3b` instalado; `bge-m3` en descarga |
| `BancosSQL.zip` (13 MB) | Versionado en git desde `main`; conviene sacarlo del repo o usar Git LFS |

## 7. Orden de desarrollo del agente y su MCP
> Añadido el 2026-10-27. Ordena las historias del [backlog on-premise](backlog/on-premise.md) para construir el DiscoverFlow y
> `converdata-mcp` (F12) sobre la misma capa de herramientas. Cada paso se apoya en el anterior.

**Antes de empezar:** en `api/converdata_api/` ya hay una API en desarrollo (login, vault, auditoría, `/discover`, `/feedback`, admin)
con rutas `/auth/login`, `/discover` y `/feedback`, mientras que [OP-04](specs/on-premise/OP-04-interfaces.md) pide `POST /login`,
`/api/discover` y `/api/discover/feedback`. Hay que acordar cuáles quedan antes del paso 5, porque el MCP y Chainlit dependen de ellas.

| Paso | Qué | Historias | Por qué en este orden |
|---|---|---|---|
| 1 | Afinar el agente: medir embeddings (las 4 combinaciones de §3) y probar los roles de Bedrock con latencia y coste reales | [HU-34](backlog/on-premise.md#hu-34--medir-y-ajustar-el-canal-semántico), [HU-35](backlog/on-premise.md#hu-35--bedrock-probado-de-punta-a-punta) | El MCP se construye sobre un agente con calidad ya medida |
| 2 | Persistencia en la BD `ConverData`: DDL con `estate` y `semantic`, validar `SqlServerVectorStore` en SQL Server 2025, escribir el catálogo y arrancar el agente desde la BD (YAML solo en desarrollo) | [HU-04](backlog/on-premise.md#hu-04--completar-el-ddl-de-la-bd-converdata), [HU-05](backlog/on-premise.md#hu-05--validar-el-ddl-y-sqlservervectorstore-en-sql-server-2025), [HU-06](backlog/on-premise.md#hu-06--escribir-el-catálogo-en-la-bd-converdata-con-historial), [HU-09](backlog/on-premise.md#hu-09--ensamblar-el-discoverflow-desde-la-bd-converdata) | Requiere una instancia SQL Server 2025 |
| 3 | Identidad: SessionVault, `ConnectionFactory.for_session` y login por servidor | [HU-11](backlog/on-premise.md#hu-11--custodia-de-credenciales-en-sessionvault), [HU-12](backlog/on-premise.md#hu-12--conexiones-con-la-credencial-del-usuario), [HU-10](backlog/on-premise.md#hu-10--iniciar-sesión-con-login-sql-por-servidor) | Cada herramienta toma la identidad de la sesión, nunca de un argumento (F14). Revisar `api/converdata_api/vault.py` contra OP-03 |
| 4 | Auditoría fail-closed en SQL Server | [HU-20](backlog/on-premise.md#hu-20--auditoría-fail-closed-en-sql-server) | Ninguna interfaz, ni la API ni el MCP, responde sin auditar (F11). Revisar `api/converdata_api/audit.py` |
| 5 | Capa de herramientas compartida (ver abajo) | [HU-16](backlog/on-premise.md#hu-16--herramientas-mcp-con-la-identidad-de-la-sesión) | La API, el chat y el MCP llaman al mismo código: un único camino de escritura (F12) |
| 6 | API y MCP publicados: las rutas llaman a las herramientas del paso 5; FastMCP en `/mcp` de `ConverData-API` con el mismo `Bearer` de `/login`; solo se publican las herramientas externas | [HU-14](backlog/on-premise.md#hu-14--api-rest-de-descubrimiento), [HU-15](backlog/on-premise.md#hu-15--confirmar-o-rechazar-un-candidato), [HU-16](backlog/on-premise.md#hu-16--herramientas-mcp-con-la-identidad-de-la-sesión) | Aceptación: Claude Code con `.mcp.json` apuntando a `/mcp` recibe un `AnswerEnvelope` con `flow=discover` (OP-04 CA3) |
| 7 | Lo que consume las herramientas: chat, curación con las herramientas internas `curation_*` e ingesta de conocimiento | [HU-17](backlog/on-premise.md#hu-17--chat-chainlit-con-tarjetas-de-candidatos), [HU-29](backlog/on-premise.md#hu-29--golden-discovery-desde-las-confirmaciones), [HU-30](backlog/on-premise.md#hu-30--preguntar-al-responsable), [HU-31](backlog/on-premise.md#hu-31--vista-curación-para-stewards), [HU-25](backlog/on-premise.md#hu-25--ingesta-de-diccionarios-de-datos), [HU-26](backlog/on-premise.md#hu-26--ingesta-de-documentos-con-redacción-de-pii), [HU-28](backlog/on-premise.md#hu-28--reglas-de-negocio-gestionadas) | Todo escribe por las herramientas internas |
| 8 | Operación y piloto: logs, alertas, instalación en IIS y piloto | [HU-21](backlog/on-premise.md#hu-21--logs-json-sin-contenido-y-visor-de-eventos), [HU-22](backlog/on-premise.md#hu-22--contadores-en-healthmetrics), [HU-37](backlog/on-premise.md#hu-37--scripts-de-instalación-en-windows-server), [HU-38](backlog/on-premise.md#hu-38--secretos-de-servicio-sin-contraseñas-en-claro), [HU-40](backlog/on-premise.md#hu-40--línea-base-firmada), [HU-41](backlog/on-premise.md#hu-41--ejecución-del-piloto-e-informe-de-decisión) | Cierra la versión on-premise |

### Paso 5 en detalle: herramientas de `converdata-mcp`
Funciones Python que reciben el contexto de sesión (usuario, grupos, `visible_ids`), antes de añadir FastMCP:

| Orden | Herramientas | Tipo |
|---|---|---|
| 5a | `discover`, `get_asset` | Externas: lo mínimo para un cliente MCP en la fase 1a |
| 5b | `get_related`, `find_alternatives`, `list_business_rules`, `get_lineage` | Externas: detalle de un candidato |
| 5c | `record_discovery_feedback` | Interna: solo la usa la API |
| 5d | `where_is`, `estate_overview`, `find_join_path`, `search_catalog`, `describe_table` | Externas, opcionales en la fase 1a (grafo F19 y catálogo) |

Los tests de permisos deben pasar ya en este paso: el usuario A no ve nada de B, ningún argumento cambia la identidad (OP-03 CA5) y hay
0 fugas en el set de evaluación.

- El MCP de metadatos (`converdata-discovery`, F18) **no se publica** on-premise: sigue como biblioteca dentro de `ConverData-Builder`
  (`src/converdata/metadata/sqlserver.py`).
- **Fuera de la fase 1a:** `ask`, `validate_sql`, `run_select`, `exec_procedure`, `list_metrics` y `analyze` (AskFlow, fase 1b); se añaden
  después sobre la misma capa de herramientas.
