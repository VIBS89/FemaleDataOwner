# ConverData — Enterprise Data Discovery Agent

Asistente de IA para la **Gerencia de Datos de Banco Atlántida El Salvador** que responde, en lenguaje natural, *dónde está un dato,
qué significa, qué reglas aplican, con qué se relaciona y cuánta confianza merece la recomendación*. Su objetivo es reducir la dependencia
del conocimiento tribal y convertir la experiencia de los expertos en conocimiento reutilizable por toda la organización.

> **Estado:** especificación y arquitectura terminadas; fase 1a on-premise en desarrollo (DiscoverFlow, agente de esquemas, GraphRAG y gateway de LLM). Estado y siguiente paso: **[plan de desarrollo](docs/PLAN-desarrollo.md)**.
> Todo el detalle está en el **[PRD](docs/PRD.md)**.

## Desarrollo
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev,ollama,nim,bedrock,sqlserver]"
.venv/Scripts/python -m pytest -q

# 1. El agente de esquemas descubre las BDs con su acceso (sin catálogo previo) y escribe el catálogo
.venv/Scripts/python -m converdata.cli catalog build --config config/databases.local.yaml --out data/catalog_bancos
#    con descripciones y sinónimos generados por el LLM (marcados "sugeridos por IA, sin revisar")
.venv/Scripts/python -m converdata.cli catalog build --out data/catalog_bancos_enriched --models config/models.yaml

# 2. Preguntar (GraphRAG híbrido: léxico + vectorial + grafo del patrimonio)
.venv/Scripts/python -m converdata.cli discover "¿Dónde está el DUI del cliente?" --root data/catalog_bancos
.venv/Scripts/python -m converdata.cli discover "<pregunta>" --root data/catalog_bancos_enriched --models config/models.embed.yaml --embeddings-only

# 3. Medir: set de evaluación por tipo de pregunta y ablación de patrones
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos --patterns query_expansion,grade,review,cascade  # sin grafo

# Gateway de LLM
cp config/models.local.example.yaml config/models.yaml  # Ollama local (o models.example.yaml para NVIDIA NIM)
.venv/Scripts/python -m converdata.cli llm smoke
```
| Capa | Paquete | Contenido |
|---|---|---|
| Orquestación (única con LangGraph) | `converdata.flows` | **CatalogBuildFlow** `extract → enrich → relate → write` y **DiscoverFlow** `intent → retrieve ⇄ grade → rerank → expand ⇄ review → respond → finalize`, ciclos acotados, sin checkpointer persistente |
| Metadatos | `converdata.metadata` | `converdata-discovery` (F18): consultas fijas de solo lectura sobre `sys.*` |
| Catálogo | `converdata.builder`, `converdata.catalog` | Conversión a F1, PII, entidades entre BDs (F19), linaje de vistas, refresco incremental que respeta ediciones humanas |
| Grafo del patrimonio | `converdata.graph` | Entidades y copias canónicas, caminos de unión entre tablas y BDs filtrados por permisos |
| LLM (única con LangChain) | `converdata.llm` | Gateway: Ollama (solo local), NVIDIA NIM, Bedrock por configuración; respaldo, circuit breaker y guarda de residencia |
| Lógica determinista | `converdata.discovery` | Expansión y descomposición de la consulta, calificación, revisor, cascada, confianza de F22, guardas |
| Memoria | `converdata.memory` | `VectorStore` híbrido (BM25 + embeddings, RRF); `InMemoryVectorStore` y `SqlServerVectorStore` (OP-02, pendiente de validar en SQL Server 2025) |
| Evaluación | `converdata.evaluation` | Hit@k por tipo (A–G), calibración, caminos, duplicados, fugas, inventados, latencia |
| Identidad y auditoría | `converdata.identity`, `converdata.audit` | `visible_ids` con el login del usuario (F14); auditoría fail-closed (F11) |
| BD `ConverData` | `db/converdata/001_esquemas.sql` | Esquemas `catalog`, `knowledge`, `golden`, `curation`, `audit` con `VECTOR`, Full-Text y tablas temporales |

Fixtures: `tests/fixtures/vbank` (ejemplo de la propuesta) y `tests/fixtures/bancos` (catálogo que el agente descubrió de BancosSQL, solo metadatos).

## Ejemplo
> *"Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital."*

```
1. ClientCode                                                  Confianza: 92 %
   Base de datos: VBank_ING · Tabla: dbo.Users · Ambiente: Producción · Servidor: SQL Producción Canales
   Descripción: Código que identifica a los clientes digitales registrados.  [revisada por Banca Digital]
   Regla: BR-ONB-004 · Se asigna al completar la verificación de identidad.
   Relacionadas: UserDevices (FK UserId) · DWH.dim.Cliente (ETL ONB_CargaUsuarios)
   [✔ Es este]  [✖ No es]  [Ver ficha]  [Ver relacionadas]

Alternativas: LegalClientId (71 %) · UserId (64 %)
```

## Qué hace
| Flujo | Para qué | Specs |
|---|---|---|
| **DiscoverFlow** (caso principal) | Devuelve campos y tablas candidatas con base de datos, ambiente, servidor, descripción, reglas de negocio, relaciones, responsables y confianza. No ejecuta SQL sobre datos | [F22](docs/specs/comun/F22-discovery-flow.md) |
| **AskFlow** (fase 1b) | Genera, valida y ejecuta T-SQL de solo lectura con los permisos del usuario; métricas certificadas y análisis | F3–F10, [F20](docs/specs/comun/F20-analysis-engine.md), [F21](docs/specs/comun/F21-semantic-layer.md) |

Fuentes de conocimiento:
- **Metadatos de SQL Server** de todos los servidores y ambientes ([F1](docs/specs/comun/F01-catalog-builder.md), [F18](docs/specs/comun/F18-discovery-mcp.md), [F19](docs/specs/comun/F19-multi-db-discovery.md)).
- **Diccionarios de datos, documentación, ETL** (SSIS, SQL Agent, SPs) y **reglas de negocio**, con los datos personales redactados ([F23](docs/specs/comun/F23-knowledge-sources.md)).
- **Conocimiento de expertos**: confirmaciones de usuarios, dudas escaladas a responsables y vista de curación ([F24](docs/specs/comun/F24-knowledge-curation.md)).

## Principios clave
- **Nadie ve más de lo que ya puede ver**: cada usuario descubre y consulta solo lo que su login SQL puede leer, incluidos los metadatos ([F14](docs/specs/comun/F14-identity.md)).
- **Los datos de clientes no salen del banco**: el catálogo no guarda valores y la nube solo procesa ([F17](docs/specs/comun/F17-data-residency.md)).
- **Cada recomendación muestra su evidencia**: fuente de la descripción y por qué se recomienda.
- **El éxito se mide contra una línea base** ([F25](docs/specs/comun/F25-success-metrics.md)).

Los 11 principios completos están en la §8.1 del PRD.

## Metas (sujetas a validación en el piloto)
| Métrica | Objetivo |
|---|---|
| Tiempo de localización de fuentes de datos | −50 % |
| Consultas a expertos funcionales | −30 % |
| Tiempo de análisis de requerimientos | −20 % a −40 % |
| Reprocesos por selección incorrecta de fuentes | −20 % |

## Tecnología y despliegues
**FastAPI** + **LangGraph** + **Amazon Bedrock** (LLM y embeddings vía `langchain-aws`), MCPs propios bajo Apache-2.0 con FastMCP
(`converdata-mcp`, `converdata-discovery`), **Chainlit** para el chat y **SQL Server**. Stack completo en la §8 del PRD.
La lógica es la misma en los dos despliegues:

| Despliegue | Cuándo | Base | Spec · diagrama |
|---|---|---|---|
| **On-premise** (MVP) | Primero: piloto de descubrimiento de 8 semanas en el dominio clientes / onboarding digital | Windows Server + IIS, SQL Server 2025 (`VECTOR`, Full-Text, grafo), SQL Server Agent; Bedrock como único servicio externo | [OP-01](docs/specs/on-premise/OP-01-despliegue-local.md) · [diagrama](docs/architecture/onpremise-architecture.html) |
| **Cloud native** | Si se decide escalar en AWS | Bedrock AgentCore, OpenSearch Serverless, ECS, Cognito; datos y auditoría siguen on-prem | [CN-01](docs/specs/cloud-native/CN-01-despliegue-aws.md) · [diagrama](docs/architecture/cloud-native-architecture.html) |

Permisos heredados de SQL Server: [diagrama](docs/architecture/permisos-heredados.html).

## Documentación
| Documento | Contenido |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Producto, usuarios, requisitos, métricas, fases, riesgos, decisiones, contrato de respuesta (§8.3), trazabilidad con la propuesta (§14), catálogo de specs (anexo A) y glosario (anexo B) |
| [docs/specs/comun/](docs/specs/comun/) | F1–F25: lógica de la solución, idéntica en ambos despliegues |
| [docs/specs/on-premise/](docs/specs/on-premise/) | OP-01 a OP-07: despliegue sobre el stack Microsoft (OP-07: instalación, entornos y operación) |
| [docs/backlog/on-premise.md](docs/backlog/on-premise.md) | Objetivos SMART, épicas e historias de usuario para terminar la versión on-premise |
| [docs/specs/cloud-native/](docs/specs/cloud-native/) | CN-01 a CN-06: despliegue en AWS |
| [docs/architecture/](docs/architecture/) | Diagramas interactivos (HTML) y sus fuentes `*.archify.json` |

Los diagramas se regeneran con el fork de Archify incluido en `tools/archify` ([F13](docs/specs/comun/F13-architecture-docs.md)):
```bash
node tools/archify/bin/archify.mjs finalize <architecture|sequence> docs/architecture/<x>.archify.json docs/architecture/<x>.html --quality showcase --json
```

## Próximos pasos
1. Medir la línea base (semanas 0–1) y confirmar el acceso a diccionarios, documentación, SSISDB y msdb.
2. Implementar la fase 1a (descubrimiento) on-premise y correr el piloto con 10–15 usuarios.
3. Evaluar contra los criterios D1–D7 de OP-01 y decidir la fase 1b (consulta de datos).
