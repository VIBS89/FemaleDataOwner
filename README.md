# ConverData — Enterprise Data Discovery Agent

Asistente de IA para la **Gerencia de Datos de Banco Atlántida El Salvador** que responde, en lenguaje natural, *dónde está un dato,
qué significa, qué reglas aplican, con qué se relaciona y cuánta confianza merece la recomendación*. Su objetivo es reducir la dependencia
del conocimiento tribal y convertir la experiencia de los expertos en conocimiento reutilizable por toda la organización.

> **Estado:** fase 1a on-premise en desarrollo. Agente, API, web y MCP construidos y medidos; catálogo, conocimiento, curación, inventario y auditoría en la BD `ConverData` (SQL Server). Faltan Bedrock, la instalación en el servidor del piloto y el trabajo con el banco. Estado y siguiente paso: **[plan de desarrollo](docs/PLAN-desarrollo.md)**.
> Todo el detalle está en el **[PRD](docs/PRD.md)**.

## Desarrollo
```bash
# Dependencias con versión y hash fijados (requirements/README.md); `pip install -e ".[api,mcp,dev,sqlserver]"` también vale en desarrollo
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes --only-binary :all: -r requirements/build.lock -r requirements/dev.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation --no-index -e .
.venv/Scripts/python -m pytest -q

# 1. El agente de esquemas descubre las BDs con su acceso (sin catálogo previo) y escribe el catálogo
.venv/Scripts/python -m converdata.cli catalog build --config config/databases.local.yaml --out data/catalog_bancos
#    con descripciones y sinónimos generados por el LLM (marcados "sugeridos por IA, sin revisar")
.venv/Scripts/python -m converdata.cli catalog build --out data/catalog_bancos_enriched --models config/models.yaml

# 2. Preguntar (búsqueda léxica + grafo del patrimonio; con --models, el LLM entiende la intención y ordena)
.venv/Scripts/python -m converdata.cli discover "¿Dónde está el DUI del cliente?" --root data/catalog_bancos

# 3. Medir: set de evaluación por tipo de pregunta y ablación de patrones
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos --patterns query_expansion,grade,review,cascade  # sin grafo
#    cuánto aportan las fuentes de conocimiento: 25 preguntas de reporte, con el catálogo solo y con un glosario de prueba
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos --cases tests/fixtures/bancos/eval/reportes.yaml
.venv/Scripts/python -m converdata.cli eval discovery --root tests/fixtures/bancos --cases tests/fixtures/bancos/eval/reportes.yaml --knowledge tests/fixtures/bancos/eval/conocimiento

# Gateway de LLM
cp config/models.local.example.yaml config/models.yaml  # Ollama local (o models.example.yaml para NVIDIA NIM)
.venv/Scripts/python -m converdata.cli llm smoke
```
### BD `ConverData` (SQL Server 2016 o posterior)
Con `CONVERDATA_DB` definida (cadena ODBC; obligatoria en qa y prod), todo el estado vive en SQL Server: catálogo, conocimiento,
curación (responsables, dudas escaladas, votos), inventario de servidores y auditoría. El servidor de aplicación no guarda archivos de
estado. Sin ella, todo va a archivos bajo `data/` (solo desarrollo y modo demo).
```bash
sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "CREATE DATABASE ConverData"
export CONVERDATA_DB='SERVER=localhost\SQLEXPRESS;DATABASE=ConverData;Trusted_Connection=yes;TrustServerCertificate=yes'
.venv/Scripts/python -m converdata.cli db migrate                                   # aplica db/converdata/*.sql (una transacción por script)
.venv/Scripts/python -m converdata.cli catalog publish --root tests/fixtures/bancos # importa un catálogo en archivos
.venv/Scripts/python -m converdata.cli catalog build --config config/databases.local.yaml --db  # refresco: parte de la BD y publica en ella
.venv/Scripts/python -m converdata.cli catalog build --db                           # lo mismo con el inventario guardado en la BD (tarea programada)
.venv/Scripts/python -m converdata.cli discover "¿Dónde está el DUI del cliente?" --db
.venv/Scripts/python -m converdata.cli eval gate --db --root tests/fixtures/bancos  # la compuerta, con el catálogo de la BD
.venv/Scripts/python -m converdata.cli catalog export --out data/export             # YAML para revisar en git
.venv/Scripts/python -m converdata.cli audit purge                                  # retención de 180 días: auditoría, dudas escaladas y originales (rol converdata_maintenance)

# Pruebas contra un SQL Server real (crean y eliminan su propia BD); sin la variable se omiten
CONVERDATA_TEST_DB='SERVER=localhost\SQLEXPRESS;Trusted_Connection=yes;TrustServerCertificate=yes' .venv/Scripts/python -m pytest -q
```
### Web (Next.js + shadcn) y ConverData-API (FastAPI)
`web/` es el chat y el explorador del catálogo; `api/` expone el agente (`/discover`, `/discover/feedback`, `/assets/{asset_key}`,
`/catalog/*`, `/auth/login`, `/admin/*`). El login es el **usuario de base de datos** de cada persona (OP-03): la API calcula con él lo que
puede ver (F14) y guarda la contraseña cifrada solo en memoria. **Primer arranque**: sin inventario ni catálogo, el primer login (con
`VIEW ANY DEFINITION` o `sysadmin`) registra el servidor y, desde *Administración → Descubrir esquemas*, el agente extrae los esquemas
con ese acceso. Los responsables de datos se asignan en *Administración → Responsables* y el historial de cada descripción se ve en *Curación* y en la
ficha del activo. Sin `CONVERDATA_DB`, la auditoría queda en `data/audit/*.jsonl` y las confirmaciones "Es este" en `knowledge/golden`
(F24); con ella, en la BD `ConverData`.
```bash
docker compose up --build                    # http://localhost:3000
CONVERDATA_DEMO=1 docker compose up --build  # servidor simulado: usuarios demo (admin) / analista, contraseña demo

# Sin Docker
.venv/Scripts/python -m pip install -e ".[api,dev]"
.venv/Scripts/python -m uvicorn converdata_api.main:app --app-dir api --port 8000   # CONVERDATA_DEMO=1 para el modo demo
npm --prefix web install && npm --prefix web run dev                                  # API_URL=http://localhost:8000 por defecto
```

**Calidad y seguridad** ([docs/calidad-bancaria.md](docs/calidad-bancaria.md)): qué controla la solución, qué prueba fija cada
control y qué falta para un banco.
```bash
.venv/Scripts/python -m pytest -q                                      # controles, capas y flujo de punta a punta
.venv/Scripts/python -m converdata.cli eval gate --out reports         # compuerta: calidad, permisos, inyección, guardas, robustez, determinismo, auditoría
.venv/Scripts/python -m converdata.cli audit verify --db               # la cuenta de la API no puede modificar la auditoría (--dir data/audit sin BD)
```
En qa y prod (`CONVERDATA_ENV`) la API no arranca con ajustes inseguros. La autenticación de Windows viene apagada: en
desarrollo local se activa con `CONVERDATA_ALLOW_WINDOWS_AUTH=1`.

| Capa | Paquete | Contenido |
|---|---|---|
| Orquestación (única con LangGraph) | `converdata.flows` | **CatalogBuildFlow** `extract → enrich → relate → write` y **DiscoverFlow** `intent → retrieve ⇄ grade → rerank → expand ⇄ review → respond → finalize`, ciclos acotados, sin checkpointer persistente |
| Metadatos | `converdata.metadata` | `converdata-discovery` (F18): consultas fijas de solo lectura sobre `sys.*` |
| Catálogo | `converdata.builder`, `converdata.catalog` | Conversión a F1, PII, entidades entre BDs (F19), linaje de vistas, refresco incremental que respeta ediciones humanas |
| Grafo del patrimonio | `converdata.graph` | Entidades y copias canónicas, caminos de unión entre tablas y BDs filtrados por permisos |
| LLM (única con LangChain) | `converdata.llm` | Gateway: Ollama (solo local), NVIDIA NIM, Bedrock por configuración; respaldo, circuit breaker y guarda de residencia |
| Lógica determinista | `converdata.discovery` | Expansión y descomposición de la consulta, calificación, revisor, cascada, confianza de F22, guardas |
| Memoria | `converdata.memory` | Puerto `VectorStore` e `InMemoryVectorStore`: índice léxico BM25 en memoria |
| Evaluación | `converdata.evaluation` | Hit@k por tipo (A–G), calibración, caminos, duplicados, fugas, inventados, latencia; compuerta de calidad `eval gate` con siete suites y línea base |
| Identidad y auditoría | `converdata.identity`, `converdata.audit` | `visible_ids` con el login del usuario (F14); auditoría fail-closed (F11) en SQL Server o, en desarrollo, en archivos con cadena de hashes |
| BD `ConverData` | `db/converdata/`, `converdata.storage` | Migraciones numeradas (esquemas `catalog`, `knowledge`, `golden`, `curation` y `audit` en tablas normales y temporales, SQL Server 2016+), repositorio del catálogo con historial y roles de mínimo privilegio |

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

Los 12 principios completos están en la §8.1 del PRD.

## Metas (sujetas a validación en el piloto)
| Métrica | Objetivo |
|---|---|
| Tiempo de localización de fuentes de datos | −50 % |
| Consultas a expertos funcionales | −30 % |
| Tiempo de análisis de requerimientos | −20 % a −40 % |
| Reprocesos por selección incorrecta de fuentes | −20 % |

## Tecnología y despliegues
**FastAPI** + **LangGraph** + **Amazon Bedrock** (un modelo, vía `langchain-aws`), `converdata-mcp` bajo Apache-2.0 con el SDK oficial de MCP,
web en **Next.js** y **SQL Server**. Stack completo en la §8 del PRD y decisiones en su §13.
La lógica es la misma en los dos despliegues:

| Despliegue | Cuándo | Base | Spec · diagrama |
|---|---|---|---|
| **On-premise** (piloto) | Primero: piloto de descubrimiento de 8 semanas en el dominio clientes / onboarding digital | Windows Server + IIS con dos procesos (web y API), BD `ConverData` en SQL Server 2016+, Programador de tareas; Bedrock como único servicio externo | [OP-01](docs/specs/on-premise/OP-01-despliegue-local.md) · [diagrama](docs/architecture/onpremise-architecture.html) |
| **AWS (despliegue mínimo)** | Después del piloto, si se decide invertir en AWS | ALB interno, una tarea de ECS Fargate con las mismas dos imágenes, Bedrock por VPC endpoint; la BD `ConverData` y los datos siguen en el banco | [CN-01](docs/specs/cloud-native/CN-01-despliegue-aws.md) · [diagrama](docs/architecture/cloud-native-architecture.html) |

Permisos heredados de SQL Server: [diagrama](docs/architecture/permisos-heredados.html). Controles de una petición y compuerta de calidad: [diagrama](docs/architecture/controles-calidad-bancaria.html).

## Documentación
| Documento | Contenido |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Producto, usuarios, requisitos, métricas, fases, riesgos, decisiones, contrato de respuesta (§8.3), trazabilidad con la propuesta (§14), catálogo de specs (anexo A) y glosario (anexo B) |
| [docs/specs/comun/](docs/specs/comun/) | F1–F25: lógica de la solución, idéntica en ambos despliegues |
| [docs/specs/on-premise/](docs/specs/on-premise/) | OP-01 a OP-07: despliegue sobre el stack Microsoft (OP-07: instalación, entornos y operación) |
| [docs/backlog/on-premise.md](docs/backlog/on-premise.md) | Objetivos SMART, épicas e historias de usuario para terminar la versión on-premise |
| [docs/PLAN-desarrollo.md](docs/PLAN-desarrollo.md) | Estado, resultados medidos, próximos pasos y cómo retomar |
| [docs/calidad-bancaria.md](docs/calidad-bancaria.md) | Controles de seguridad, compuerta de calidad y lo que falta para operar en un banco |
| [docs/specs/cloud-native/](docs/specs/cloud-native/) | CN-01 a CN-06: despliegue mínimo en AWS, posterior al piloto |
| [docs/architecture/capas-backend.md](docs/architecture/capas-backend.md) | Capas del backend y regla de dependencias |
| [docs/architecture/](docs/architecture/) | Diagramas interactivos (HTML) y sus fuentes `*.archify.json` |

Los diagramas se regeneran con el fork de Archify incluido en `tools/archify` ([F13](docs/specs/comun/F13-architecture-docs.md)):
```bash
node tools/archify/bin/archify.mjs finalize <architecture|sequence> docs/architecture/<x>.archify.json docs/architecture/<x>.html --quality showcase --json
```

## Próximos pasos
El orden vigente está en el [plan de desarrollo §3](docs/PLAN-desarrollo.md#3-próximos-pasos-en-orden):
1. Terminar de llevar la curación a la BD `ConverData` (responsables, solicitudes, votos) y preparar la instalación en Windows Server.
2. Con el banco: probar Bedrock, reunir 50–80 preguntas reales, ingerir diccionarios y documentos del dominio y medir la línea base.
3. Correr el piloto con 10–15 usuarios, evaluar contra los criterios D1–D7 de OP-01 y decidir la fase 1b (consulta de datos).
