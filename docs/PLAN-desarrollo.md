# Plan de desarrollo — estado y cómo retomar

> Última actualización: 2026-10-25. Documento vivo: se actualiza al cerrar cada sesión de trabajo.
> Specs: [PRD](PRD.md), [comun/](specs/comun/), [on-premise/](specs/on-premise/). Uso diario: [README](../README.md#desarrollo).
> Backlog para terminar la versión on-premise (objetivos SMART e historias): [backlog/on-premise.md](backlog/on-premise.md).

## 1. Dónde estamos
Fase 1a on-premise (descubrimiento), núcleo implementado y medido. **81 tests en verde.** Todo el código está **sin commit**
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
