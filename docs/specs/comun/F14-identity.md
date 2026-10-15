# F14 — Identidad y permisos heredados · común

> Dónde vive la credencial por entorno: **cloud native** → Cognito + Secrets Manager/KMS ([CN-03](../cloud-native/CN-03-identidad.md)) · **on-premise** → SessionVault en memoria ([OP-03](../on-premise/OP-03-identidad.md))
> Diagrama: `docs/architecture/permisos-heredados.html`

## Historia de usuario
Como **usuario**, quiero ver y consultar solo los datos a los que mi login de SQL Server tiene acceso,
sin que la aplicación amplíe mis permisos.

## Principio
**ConverData nunca amplía permisos.** Cada consulta de datos se ejecuta con el **login SQL del propio usuario**, así que SQL Server
aplica sus permisos reales (GRANT, DENY, roles, esquemas, seguridad a nivel de fila). Lo que el usuario no ve en SSMS, tampoco
lo ve en ConverData.

## Flujo (igual en ambos entornos)
1. **Validación del login**: se abre una conexión de prueba con el login SQL del usuario (`SELECT SUSER_SNAME(), ORIGINAL_LOGIN()`). Si falla, no hay sesión.
2. **Custodia de la credencial**: se guarda cifrada fuera del alcance del LLM; el mecanismo depende del entorno (CN-03 / OP-03).
3. **Visibilidad**: se calcula con la conexión del usuario y se cachea 15 min por sesión:
   ```sql
   -- por cada BD configurada a la que el login tiene acceso (HAS_DBACCESS(name)=1)
   SELECT o.object_id, s.name AS [schema], o.name, o.type
   FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
   WHERE o.type IN ('U','V','P')
     AND (HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name),'OBJECT',
          CASE o.type WHEN 'P' THEN 'EXECUTE' ELSE 'SELECT' END) = 1);
   ```
   El resultado se mapea a los `id` del catálogo y forma `visible_ids`. Los `DENY` a nivel de columna se detectan con `HAS_PERMS_BY_NAME(..., 'COLUMN')` solo en las tablas que pasan el schema linking.
4. **Ejecución**: toda consulta (F5, F7 compilación, F8) usa una conexión abierta con la credencial del usuario.

## Tres capas de defensa
| Capa | Dónde | Qué hace |
|---|---|---|
| 1. Catálogo filtrado | F2, F4 | El agente ni siquiera conoce la existencia de tablas ajenas |
| 2. Validador | F7 | Rechaza objetos fuera de `visible_ids` antes de llegar a SQL Server |
| 3. SQL Server | F8 | Aplica los permisos reales; un acceso indebido devuelve el error 229 |

## Reglas
- **El LLM nunca ve credenciales**: las herramientas reciben la identidad desde el contexto autenticado (`state.user`), no como argumento.
- **No se revela lo que no se puede ver**: si una pregunta solo podría responderse con objetos fuera de la visibilidad, la respuesta es "no encontré datos disponibles para ti sobre …", sin confirmar que esas tablas existen.
- **Login de metadatos**: solo lo usa el Catalog Builder (F1); nunca se usa para responder preguntas de usuarios.
- TLS en todas las conexiones (`Encrypt=yes; TrustServerCertificate=no` en producción).
- Bloqueo tras 5 logins fallidos en 10 min por login.
- Las contraseñas se excluyen de logs, trazas, auditoría y mensajes de error.

## Criterios de aceptación
1. El usuario A (solo esquema `Ventas`) no obtiene tablas de `RRHH` en `/catalog/search` ni en el contexto del planner.
2. Si el usuario A pregunta por salarios de RRHH, recibe "no encontré datos disponibles" sin mención a tablas de RRHH.
3. Si el usuario A fuerza `run_select` sobre `RRHH.Empleado` vía MCP, el validador lo rechaza y, sin el validador, SQL Server devuelve el error 229.
4. Al cerrar la sesión, la credencial deja de ser utilizable (401).
5. Ningún log ni traza contiene la contraseña (test de logs).
