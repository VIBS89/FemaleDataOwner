# F7 — Validator (pre-ejecución) y autocorrección

## Historia de usuario
Como **responsable de seguridad y DBA**, quiero que ninguna consulta llegue a ejecutarse sin pasar validaciones
estáticas, de compilación y de costo, para proteger los datos y el rendimiento del servidor.

## Etapas (cada una corta el proceso si falla)
| # | Etapa | Implementación | Rechaza |
|---|---|---|---|
| 1 | Parseo | `sqlglot.parse(sql, dialect="tsql")` | errores de sintaxis; más de una sentencia; `GO` |
| 2 | Tipo de sentencia | AST | todo lo que no sea `SELECT`/`WITH … SELECT` (los SPs van por otra vía) |
| 3 | Lista negra | recorrido del AST y regex de respaldo | `INSERT/UPDATE/DELETE/MERGE/TRUNCATE/DROP/ALTER/CREATE/GRANT/EXEC`, `SELECT … INTO`, `OPENROWSET`, `OPENQUERY`, `OPENDATASOURCE`, `xp_*`, `sp_*` (salvo lista blanca), `WAITFOR`, `DBCC`, hints `NOLOCK` sobre tablas sensibles, `BULK`, `SHUTDOWN` |
| 4 | Objetos | AST → tablas y columnas, comparadas con el catálogo y con `visible_ids` | objetos inexistentes o no visibles (con un mensaje que sugiere el nombre correcto más cercano) |
| 5 | Normalización | AST | inyecta `TOP (max_rows+1)` si falta y cualifica nombres; usa `max_rows+1` para detectar truncado |
| 6 | Compilación | conexión del usuario: `SET NOEXEC ON; <sql>; SET NOEXEC OFF` | errores de binding, tipos y permisos |
| 7 | Plan estimado | `SET SHOWPLAN_XML ON` y parseo de `StatementSubTreeCost` y `EstimateRows` | costo mayor que `guardrails.max_plan_cost` (por defecto 50) o filas estimadas mayores que `guardrails.max_est_rows` (por defecto 5M); avisa de *table scans* sobre tablas con más de 10M filas |

Para **stored procedures**:
- `name` debe estar en `procedures.yaml`.
- Los parámetros se validan con un modelo Pydantic generado desde la configuración.
- El usuario debe tener `HAS_PERMS_BY_NAME(name,'OBJECT','EXECUTE') = 1`.
- Si `side_effects: true`, se requiere `confirmed=true`.

## Bucle de autocorrección
```
planner → validator ──fail──► feedback {stage, error, sugerencias} → planner (máx. 3 intentos)
                     └─pass──► executor
```
- El feedback incluye el error de SQL Server (número y mensaje), las columnas o tablas válidas más cercanas (rapidfuzz) y el fragmento de DDL relevante.
- Tras 3 fallos, se devuelve `status=rejected` con la explicación y el último SQL (no ejecutado).

## Configuración `config/guardrails.yaml`
```yaml
max_rows: 10000
max_plan_cost: 50
max_est_rows: 5000000
query_timeout_s: 60
lock_timeout_ms: 5000
blocked_functions: [OPENROWSET, OPENQUERY, OPENDATASOURCE]
sensitive_tables: []          # requieren rol adicional, aunque SQL Server lo permita
```

## Criterios de aceptación (tests unitarios en `tests/unit/test_validator.py`)
1. Rechaza: `DELETE FROM x`, `SELECT 1; DROP TABLE x`, `SELECT * INTO t FROM x`, `SELECT * FROM OPENROWSET(...)`, `EXEC xp_cmdshell 'dir'`, `WAITFOR DELAY '00:01'`.
2. Acepta `WITH c AS (SELECT …) SELECT …` y le inyecta `TOP`.
3. Las referencias a tablas no visibles se rechazan antes de llegar a SQL Server.
4. Los errores de compilación se transforman en feedback útil; en el set de evaluación, al menos el 60 % de los fallos se corrigen en el primer reintento.
