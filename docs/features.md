# ConverData — Catálogo de features

ConverData es un agente de descubrimiento de datos en lenguaje natural sobre Microsoft SQL Server.
Un conjunto de agentes CrewAI, con el LLM servido por Amazon Bedrock, entiende la estructura de varias bases de datos,
decide de dónde tomar los datos, genera y valida T-SQL (o elige un stored procedure de una lista blanca),
lo ejecuta **con los permisos del usuario** y devuelve resultados procesados, verificados y trazables.

## Principios de diseño
1. **Determinismo en la orquestación**: un CrewAI Flow con pasos fijos. Los agentes razonan dentro de cada paso, pero no deciden saltarse pasos.
2. **SQL Server es la barrera de seguridad**: cada consulta corre con el login del usuario. Los guardrails de la aplicación son defensa en profundidad.
3. **Nada se ejecuta sin validar**: validación estática, compilación (NOEXEC) y plan estimado (SHOWPLAN) antes de ejecutar.
4. **Toda respuesta es auditable**: SQL, tablas, supuestos, validaciones y confidence acompañan a cada dato.
5. **Memoria revisable por humanos**: el catálogo vive en YAML versionable; el índice vectorial es derivado.
6. **Cero persistencia de datos fuera de la red del cliente**: la nube procesa y muestra; datos, preguntas, SQL y auditoría persisten solo on-premise (F17).
7. **Misma lógica, dos despliegues**: los agentes, las herramientas MCP y el validador son idénticos en cloud native y on-premise; solo cambia la infraestructura.

## Organización de las specs
```
docs/specs/
├─ comun/          Lógica de la solución, idéntica en ambos despliegues (F1–F17)
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
  "timings_ms": {"total": 0, "llm": 0, "db": 0}
}
```

## Glosario
- **Catálogo**: descripción de BDs, esquemas, tablas, columnas, FKs y SPs, **sin valores de datos** (`**/*.yaml`).
- **Golden SQL**: pares pregunta→SQL validados por un humano. El original vive en la auditoría on-prem; en el índice solo su plantilla anonimizada.
- **Visibilidad**: conjunto de objetos que el login del usuario puede leer o ejecutar, según SQL Server.
- **Confidence**: puntuación de 0 a 1 que combina los chequeos deterministas con el veredicto del LLM-judge.
