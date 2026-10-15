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
1. **Validación del login**: los logins SQL son por instancia, y el descubrimiento recorre varios servidores y ambientes (F1). El usuario
   entrega una credencial **por servidor**; la UI le ofrece usar la misma en todos los servidores que marque (alias de `config/databases.yaml`).
   En cada uno se abre una conexión de prueba (`SELECT SUSER_SNAME(), ORIGINAL_LOGIN()`). Si falla en todos, no hay sesión; los servidores
   donde falla quedan fuera de su visibilidad y no se reintentan solos (para no provocar bloqueos por intentos fallidos). Puede añadir
   credenciales de otros servidores más tarde.
2. **Custodia de la credencial**: se guarda cifrada fuera del alcance del LLM, una por servidor; el mecanismo depende del entorno (CN-03 / OP-03).
3. **Visibilidad**: se calcula con la conexión del usuario en cada servidor (en paralelo) y se cachea 15 min por sesión:
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

## Grupos y roles del usuario
Los fragmentos de documentos con ACL de origen (`allowed_groups`, F23), los roles `steward`/`data_admin` (F24) y el perfil de las
métricas (`user_group`, F25) necesitan saber a qué grupos corporativos pertenece el usuario:
| Entorno | Fuente de los grupos |
|---|---|
| Cloud native | Claim `cognito:groups` del JWT, sincronizado desde el IdP corporativo federado (CN-03) |
| On-premise | Tabla `curation.user_directory` (login SQL → cuenta de AD), mantenida por `data_admin`; al iniciar sesión, el servicio consulta AD por LDAP (solo lectura, con su gMSA) los grupos de esa cuenta (OP-03) |

Si no hay grupos resueltos (login sin cuenta de AD asociada o directorio no disponible), `groups = []`: el usuario no ve fragmentos con ACL
ni tiene roles de curación (fail-closed). Los grupos se cachean con la visibilidad.

## Visibilidad en el descubrimiento (F22–F24) — decisión tomada
**El descubrimiento hereda exactamente los mismos permisos que la consulta de datos.** No existe un modo de "catálogo abierto":
un usuario solo descubre los objetos que están en sus `visible_ids`, aunque se trate únicamente de metadatos.
- Aplica a todo lo que muestra el DiscoverFlow: candidatos, ubicaciones por ambiente, alternativas, relaciones, linaje, reglas de negocio,
  documentos vinculados e indicadores. Un elemento que mencione objetos fuera de `visible_ids` se descarta o se recorta
  (por ejemplo, una arista de linaje hacia una tabla no visible no se muestra).
- Las ubicaciones se filtran por ambiente: si el usuario puede leer `VBank_ING.dbo.Users` en QA pero no en producción, solo ve la de QA.
- Los fragmentos de documentos y reglas se muestran solo si **todos** sus `linked_assets` son visibles para el usuario y, además,
  pertenece a los `allowed_groups` de su origen (F23).
- Los golden discovery (F24) solo se sugieren si todos sus `asset_keys` son visibles.
- Si nada visible responde la pregunta, la respuesta es la de la regla general ("no encontré datos disponibles para ti sobre …") y se ofrece
  "Preguntar al responsable" (F24) **sin** revelar qué objetos existen; el responsable decide si concede acceso.
- Por tanto, **el descubrimiento también requiere el login SQL del usuario** (para calcular `visible_ids`).

## Tres capas de defensa
| Capa | Dónde | Qué hace |
|---|---|---|
| 1. Catálogo filtrado | F2, F4 | El agente ni siquiera conoce la existencia de tablas ajenas |
| 2. Validador | F7 | Rechaza objetos fuera de `visible_ids` antes de llegar a SQL Server |
| 3. SQL Server | F8 | Aplica los permisos reales; un acceso indebido devuelve el error 229 |

## Reglas
- **El LLM nunca ve credenciales**: las herramientas reciben la identidad desde el contexto autenticado (`state.user`), no como argumento.
- **No se revela lo que no se puede ver**: si una pregunta solo podría responderse con objetos fuera de la visibilidad, la respuesta es "no encontré datos disponibles para ti sobre …", sin confirmar que esas tablas existen.
- **Login de metadatos**: solo lo usan `converdata-discovery` (F18) y el Catalog Builder (F1); nunca se usa para responder preguntas de usuarios.
- **Consultas entre BDs y servidores** (F19): cada rama se ejecuta con el login del usuario en su servidor; si no tiene permisos en una de ellas, esa parte se omite y se indica.
- TLS en todas las conexiones (`Encrypt=yes; TrustServerCertificate=no` en producción).
- Bloqueo tras 5 logins fallidos en 10 min por login.
- Las contraseñas se excluyen de logs, trazas, auditoría y mensajes de error.

## Criterios de aceptación
1. El usuario A (solo esquema `Ventas`) no obtiene tablas de `RRHH` en `/catalog/search` ni en el contexto del planner.
2. Si el usuario A pregunta por salarios de RRHH, recibe "no encontré datos disponibles" sin mención a tablas de RRHH.
3. Si el usuario A fuerza `run_select` sobre `RRHH.Empleado` vía MCP, el validador lo rechaza y, sin el validador, SQL Server devuelve el error 229.
4. Al cerrar la sesión, la credencial deja de ser utilizable (401).
5. Ningún log ni traza contiene la contraseña (test de logs).
6. En el DiscoverFlow, el usuario A (solo `Ventas`) no recibe candidatos, alternativas, relaciones, linaje, reglas ni fragmentos de documentos
   que mencionen objetos de `RRHH` o de `VBank_ING`, ni ubicaciones en ambientes donde no tiene permiso.
