# ConverData — Catálogo de features

ConverData es la implementación del **Enterprise Data Discovery Agent** (propuesta de la Gerencia de Datos de Banco Atlántida;
trazabilidad en [propuesta-trazabilidad.md](propuesta-trazabilidad.md)): un agente de descubrimiento y conocimiento de datos
corporativos en lenguaje natural sobre Microsoft SQL Server. Tiene dos flujos:

1. **DiscoverFlow (F22), el caso de uso principal**: el usuario describe el dato que necesita y recibe una lista priorizada de campos y
   tablas candidatas, con base de datos, ambiente, servidor, descripción funcional, reglas de negocio, relaciones, responsables y nivel
   de confianza. Razona sobre metadatos, diccionarios, documentación, ETL y conocimiento capturado de expertos (F23, F24). No ejecuta SQL.
2. **AskFlow (F3–F10, F20, F21), la evolución**: genera y valida T-SQL (o elige un stored procedure de una lista blanca),
   lo ejecuta **con los permisos del usuario** y devuelve resultados procesados, verificados y trazables. Corresponde a la visión
   futura "Recomendación y generación de SQL" de la propuesta.

Los agentes CrewAI usan Amazon Bedrock como LLM.

## Principios de diseño
1. **Determinismo en la orquestación**: un CrewAI Flow con pasos fijos. Los agentes razonan dentro de cada paso, pero no deciden saltarse pasos.
2. **SQL Server es la barrera de seguridad**: cada consulta corre con el login del usuario. Los guardrails de la aplicación son defensa en profundidad.
3. **Nada se ejecuta sin validar**: validación estática, compilación (NOEXEC) y plan estimado (SHOWPLAN) antes de ejecutar.
4. **Toda respuesta es auditable**: SQL, tablas, supuestos, validaciones y confidence acompañan a cada dato.
5. **Memoria revisable por humanos**: el catálogo vive en YAML versionable; el índice vectorial es derivado.
6. **Cero persistencia de datos fuera de la red del cliente**: la nube procesa y muestra; datos, preguntas, SQL y auditoría persisten solo on-premise (F17).
7. **Misma lógica, dos despliegues**: los agentes, las herramientas MCP y el validador son idénticos en cloud native y on-premise; solo cambia la infraestructura.
8. **Descubrir antes que consultar**: ante la duda, el router elige el DiscoverFlow, que no toca datos (F3, F22).
9. **El conocimiento se captura con el uso**: cada confirmación de un usuario o respuesta de un responsable se convierte en conocimiento revisado y reutilizable (F24).
10. **Cada recomendación muestra su evidencia**: fuente de la descripción (humana, diccionario, documento o IA sin revisar) y por qué se recomienda.
11. **El éxito se mide contra una línea base**: las métricas de la propuesta se instrumentan desde el día uno (F25).

## Organización de las specs
```
docs/specs/
├─ comun/          Lógica de la solución, idéntica en ambos despliegues (F1–F25)
├─ cloud-native/   Despliegue en AWS con Bedrock AgentCore (CN-01 a CN-06)
└─ on-premise/     Despliegue local en la red corporativa; sirve también como MVP (OP-01 a OP-06)
```

## Specs comunes
| ID | Feature | Spec | Implementación cloud native | Implementación on-premise |
|---|---|---|---|---|
| F1 | Catalog Builder (ingesta y mapeo) | [F01](specs/comun/F01-catalog-builder.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) |
| F2 | Memoria semántica (`VectorStore`) | [F02](specs/comun/F02-semantic-memory.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) OpenSearch | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) Chroma |
| F3 | Intent & Router | [F03](specs/comun/F03-intent-router.md) | = | = |
| F4 | Schema Linking | [F04](specs/comun/F04-schema-linking.md) | = | = |
| F5 | Value Resolution (en vivo) | [F05](specs/comun/F05-value-resolution.md) | = | = |
| F6 | Planner T-SQL / SP | [F06](specs/comun/F06-planner.md) | = | = |
| F7 | Validator | [F07](specs/comun/F07-validator.md) | = | = |
| F8 | Executor | [F08](specs/comun/F08-executor.md) | = | = |
| F9 | Result Verifier | [F09](specs/comun/F09-result-verifier.md) | = | = |
| F10 | Analyst | [F10](specs/comun/F10-analyst.md) | = | = |
| F11 | Auditoría | [F11](specs/comun/F11-audit.md) | [CN-05](specs/cloud-native/CN-05-auditoria-observabilidad.md) `ConverData_Audit` on-prem | [OP-05](specs/on-premise/OP-05-auditoria-observabilidad.md) SQLite |
| F12 | Interfaces (API, chat, MCP) | [F12](specs/comun/F12-interfaces.md) | [CN-04](specs/cloud-native/CN-04-interfaces.md) | [OP-04](specs/on-premise/OP-04-interfaces.md) |
| F13 | Arquitectura documentada (Archify) | [F13](specs/comun/F13-architecture-docs.md) | = | = |
| F14 | Identidad y permisos heredados | [F14](specs/comun/F14-identity.md) | [CN-03](specs/cloud-native/CN-03-identidad.md) Cognito + Secrets Manager | [OP-03](specs/on-premise/OP-03-identidad.md) SessionVault |
| F16 | Proveedores LLM: Bedrock (+ NIM opcional) | [F16](specs/comun/F16-llm-providers.md) | = | = |
| F17 | Residencia de datos | [F17](specs/comun/F17-data-residency.md) | [CN-06](specs/cloud-native/CN-06-residencia-datos.md) | [OP-06](specs/on-premise/OP-06-residencia-datos.md) |
| F18 | `converdata-discovery`: MCP propio de metadatos (Apache-2.0, sustituye a sql-to-mcp) | [F18](specs/comun/F18-discovery-mcp.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) ECS privado | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) contenedor |
| F19 | Descubrimiento entre múltiples BDs (grafo del patrimonio, joins entre BDs, planes federados) | [F19](specs/comun/F19-multi-db-discovery.md) | = | = |
| F20 | Motor de análisis (compare, explain, explore, forecast, sandbox) | [F20](specs/comun/F20-analysis-engine.md) | = | = |
| F21 | Capa semántica (métricas certificadas, consultas verificadas) | [F21](specs/comun/F21-semantic-layer.md) | = | = |
| **F22** | **DiscoverFlow: candidatos con ubicación, descripción, reglas, relaciones y confianza** | [F22](specs/comun/F22-discovery-flow.md) | = | = |
| F23 | Fuentes de conocimiento: diccionarios, documentación, ETL (SSIS, SQL Agent) y reglas de negocio | [F23](specs/comun/F23-knowledge-sources.md) | [CN-02](specs/cloud-native/CN-02-catalogo-memoria.md) | [OP-02](specs/on-premise/OP-02-catalogo-memoria.md) |
| F24 | Curación y captura del conocimiento institucional (responsables, escalamiento, brechas) | [F24](specs/comun/F24-knowledge-curation.md) | = | = |
| F25 | Métricas de éxito, línea base y piloto | [F25](specs/comun/F25-success-metrics.md) | = | = |

"=" significa que no hay diferencias entre entornos.

## Despliegues
| Despliegue | Spec principal | Diagrama | Cuándo |
|---|---|---|---|
| **On-premise** | [OP-01](specs/on-premise/OP-01-despliegue-local.md) | `architecture/onpremise-architecture.html` | Primero: MVP para validar la solución sin infraestructura cloud nueva (solo Bedrock) |
| **Cloud native** | [CN-01](specs/cloud-native/CN-01-despliegue-aws.md) | `architecture/cloud-native-architecture.html` | Después del MVP, si se decide invertir en AWS |

Los permisos heredados se explican en `architecture/permisos-heredados.html` (F14) y aplican igual a los dos despliegues.

## Contrato de respuesta: `AnswerEnvelope`

```json
{
  "trace_id": "uuid",
  "status": "ok | needs_clarification | rejected | error",
  "answer_text": "Resumen en español",
  "clarification": {"question": "...", "options": ["..."]},
  "data": {"columns": [{"name": "...", "type": "..."}], "rows": [[...]], "row_count": 0, "truncated": false},
  "sql": "SELECT TOP (1000) ...",
  "procedure": {"name": "dbo.usp_x", "params": {}},
  "databases": ["Ventas"],
  "tables_used": ["Ventas.dbo.Pedido"],
  "assumptions": ["'último trimestre' = 2026-Q3"],
  "validation": {
    "static": "pass",
    "compile": "pass",
    "plan": {"estimated_cost": 0.42, "estimated_rows": 1200},
    "checks": [{"name": "fan_out", "status": "pass", "detail": "..."}]
  },
  "confidence": 0.87,
  "chart_spec": {"type": "bar", "x": "...", "y": "..."},
  "discovery": {"candidates": [], "alternatives": [], "related": [], "knowledge_gap": false},
  "timings_ms": {"total": 0, "llm": 0, "db": 0}
}
```
- `flow`: `discover` | `ask` (campo adicional). En `discover` se llena `discovery` (estructura completa en [F22](specs/comun/F22-discovery-flow.md))
  y quedan vacíos `data`, `sql`, `validation` y `chart_spec`; en `ask` es al revés.

## Glosario
- **Catálogo**: descripción de BDs, esquemas, tablas, columnas, FKs y SPs, **sin valores de datos** (`**/*.yaml`).
- **Golden SQL**: pares pregunta→SQL validados por un humano. El original vive en la auditoría on-prem; en el índice solo su plantilla anonimizada.
- **Visibilidad**: conjunto de objetos que el login del usuario puede leer o ejecutar, según SQL Server.
- **Confidence**: puntuación de 0 a 1. En el AskFlow combina los chequeos deterministas con el veredicto del LLM-judge (F9); en el DiscoverFlow combina relevancia, evidencia, confirmaciones y acuerdo entre fuentes (F22).
- **`asset_key`**: identificador lógico de un objeto (`db.schema.objeto[.columna]`) que agrupa sus copias en todos los ambientes (F1).
- **Golden discovery**: pregunta de descubrimiento (plantilla anonimizada) confirmada por usuarios o por un responsable, ligada a los activos correctos (F24).
- **Steward / responsable**: grupo funcional o técnico dueño de un dominio de datos (`config/owners.yaml`, F24).
- **Brecha de conocimiento**: pregunta sin candidato con confianza suficiente, o activo muy consultado sin descripción revisada (F24).
