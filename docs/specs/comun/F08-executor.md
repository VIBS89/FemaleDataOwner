# F8 — Executor

> **Primer corte adelantado (2026-11-23, PRD §13, decisión 17).** Para las cifras agregadas (apagadas por defecto), `AgentRuntime.figure_executor`
> (`api/discovery_data_agent_api/runtime.py`) ejecuta el agregado con la credencial de la sesión (F14), con `SET LOCK_TIMEOUT 5000`, lectura sin bloqueos
> (`READ UNCOMMITTED`, no `READ COMMITTED` como abajo), `conn.timeout` de 15 s, como máximo 50 filas y una transacción que siempre se revierte; antes valida el SQL contra la plantilla (`figures.ALLOWED_SQL`, `check_sql`), `OPTION (MAXDOP 1)`, admite dos cifras a la vez como máximo y audita la consulta (`figure_query`) **antes** de ejecutarla: si la auditoría falla, no se ejecuta. Un servidor de producción exige `figures: true` en el inventario. Cierra
> la conexión también si falla. La consulta con una unión por una tabla relacionada (desglose) usa la misma plantilla y los mismos controles. SQL Server decide el permiso: si lo niega, se responde sin cifra y sin el mensaje de error. No tiene pool por usuario,
> reintento de 1222 y -2, `ApplicationIntent=ReadOnly`, `truncated`, `pandas` ni varios conjuntos de resultados, y no ejecuta procedimientos. El ejecutor
> de la CLI (`discovery-data-agent discover --figures`) usa el login de metadatos del inventario y no aplica el tope ni la reversión: es solo de desarrollo.
> Pruebas: `api/tests/test_cifras.py` (entre ellas `test_politica_de_cifras_por_servidor`). El resto de esta spec sigue siendo de la fase 1b.

## Historia de usuario
Como **usuario**, quiero que mis consultas se ejecuten con mis propios permisos, de forma rápida y sin bloquear el servidor.

## Comportamiento
- Obtiene la conexión con `ConnectionFactory.for_session(session_id, database)` (F14). Usa pyodbc con ODBC Driver 18, `Encrypt=yes`, y un pool por usuario y base de datos (máximo 2 conexiones, inactividad de 10 min).
- Prepara cada ejecución con:
  ```sql
  SET LOCK_TIMEOUT 5000;
  SET TRANSACTION ISOLATION LEVEL READ COMMITTED; -- o SNAPSHOT si la BD lo permite
  SET ARITHABORT ON; SET NOCOUNT ON;
  ```
  y `cursor.timeout = query_timeout_s`.
- Usa `ApplicationIntent=ReadOnly` cuando `databases.yaml` define una réplica de lectura.
- Ejecuta SQL parametrizado (`?` de pyodbc, mapeado desde `@pN`) o `EXEC [db].[schema].[sp] @p=?` para SPs.
- Lee como máximo `max_rows + 1` filas con `fetchmany` y marca `truncated` si hay más.
- Convierte a `pandas.DataFrame` con los tipos de `cursor.description` (Decimal → float solo en la capa de presentación).
- Si un SP devuelve varios result sets, se capturan todos (`nextset`), hasta 5.

## Errores
| Error SQL Server | Acción |
|---|---|
| 229/230 (permiso denegado) | `status=rejected`, con el mensaje "No tienes permiso sobre X" (no se reintenta) |
| 1222 (lock timeout), -2 (timeout) | Se reintenta una vez; después devuelve un error con una sugerencia (acotar el rango de fechas) |
| 207/208 (columna u objeto inválido) | Vuelve al bucle de F7 como feedback |
| 18456 (login fallido o expirado) | Se invalida la sesión y se pide reautenticación |

## Criterios de aceptación
1. Un usuario sin `SELECT` sobre `RRHH.Empleado` obtiene `rejected` por el error 229, aunque el validador lo dejara pasar (test con validación desactivada).
2. Una consulta de 50 000 filas con `max_rows = 10000` devuelve 10 000 filas y `truncated=true`.
3. Ninguna credencial aparece en logs ni trazas (test con grep sobre la salida de logs).
