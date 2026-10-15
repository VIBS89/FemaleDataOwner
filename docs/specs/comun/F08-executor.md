# F8 — Executor

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
