# OP-03 — Identidad y custodia de credenciales · on-premise

> Implementa en on-premise Microsoft: [F14](../comun/F14-identity.md). El principio y el flujo de herencia de permisos son los de F14.

## Decisión (2026-10-14): logins SQL por usuario
No hay IdP: la pantalla de login de Chainlit (o `POST /login`) recibe `{credentials: [{server, login, password}]}`, con la opción
"usar la misma credencial en los servidores marcados", y valida cada una abriendo una conexión de prueba (F14). El login es a la vez la
identidad de aplicación y la de datos, y también calcula los `visible_ids` del **descubrimiento** (F22): el usuario solo ve metadatos de lo
que su login puede consultar en cada servidor.

**Grupos** (F14): `curation.user_directory` asocia el login SQL con la cuenta de AD de la persona (lo mantiene `data_admin`). Al iniciar
sesión, `ConverData-API` consulta por LDAP (solo lectura, con su gMSA) los grupos de esa cuenta; sin asociación, `groups = []`.

## Custodia: `SessionVault` en memoria del servicio `ConverData-API`
- `session_id → {user_id, groups[], credentials: {server → {login, password_enc}}, created_at, last_seen}`.
- `password_enc` se cifra con **Fernet** y una clave efímera generada al arrancar el servicio. **Nunca se escribe a disco**, ni en logs, ni en el Visor de eventos.
- TTL de 8 h con expiración deslizante; se borra en `/logout` o al reiniciar el servicio (el usuario vuelve a iniciar sesión).
- `session_id`: token opaco aleatorio de 256 bits, enviado como `Authorization: Bearer` (API y MCP) o en la sesión de Chainlit.
- `ConnectionFactory.for_session(session_id, database)` construye la cadena ODBC con `Encrypt=yes` y `ApplicationName=ConverData`; la contraseña solo vive descifrada durante `pyodbc.connect`.
- El servicio corre **en un solo proceso** (un worker de uvicorn bajo HttpPlatformHandler) para que todas las peticiones vean el mismo SessionVault.
- El grupo de aplicaciones de `ConverData-API` tiene el **reciclaje superpuesto desactivado**, para que nunca haya dos procesos con dos SessionVault (OP-07).
- La identidad del usuario sale **solo del `Bearer`** o de la sesión de Chainlit: ninguna herramienta MCP ni ruta de la API acepta `user_id`, `session_id` ni credenciales como argumento, así que ni el LLM ni un cliente pueden suplantar a otro usuario.
- **Sin volcados de memoria**: el SessionVault vive en RAM, así que Windows Error Reporting no genera volcados de los procesos de ConverData, `SeDebugPrivilege` queda solo para administradores y el volcado de memoria del sistema se limita al del kernel (OP-06, OP-07).

## Cuentas técnicas (no son de usuarios)
| Cuenta | Tipo | Permisos | Dónde se guarda |
|---|---|---|---|
| Procesos de ConverData (grupos de aplicaciones de IIS de `ConverData-UI` y `-API`, servicio de Windows `ConverData-Builder`) | **gMSA** | Lectura/escritura solo en la BD `ConverData`, con los permisos de escritor de auditoría de F11 (en `audit` solo `INSERT`); lectura de AD por LDAP | Gestionada por AD (sin contraseña) |
| Login de metadatos (F18) | Login SQL o gMSA de `ConverData-Builder` | Los de F18: `VIEW DEFINITION`, `VIEW DATABASE STATE`, `SELECT` solo en la réplica, lectura de SSISDB y msdb | Si es login SQL, **DPAPI** con ámbito de la cuenta de servicio |
| Lectura de documentos (F23) | gMSA de `ConverData-Builder` o cuenta técnica | Solo lectura en la carpeta compartida o en los sitios de SharePoint del dominio piloto | Gestionada por AD |
| Acceso a Bedrock | IAM Roles Anywhere (certificado de la PKI corporativa) | Solo `bedrock:InvokeModel*` y `bedrock:ApplyGuardrail` | Almacén de certificados de Windows, clave privada no exportable |

## Evolución: Windows / Active Directory
Si más adelante los usuarios se autentican con AD, IIS puede hacer SSO con autenticación Windows y **delegación restringida de Kerberos**
hasta SQL Server, de modo que no se guarde ninguna contraseña. Requiere SPNs, delegación configurada en la cuenta del servicio y que
Python suplante el token de IIS (pywin32) antes de conectar; hay que validarlo con una prueba de concepto que verifique `SUSER_SNAME()`.

## Criterios de aceptación
1. Los criterios de F14 se cumplen con dos logins SQL de prueba con permisos distintos, tanto en consulta como en descubrimiento, y en dos servidores (producción y QA).
2. Tras reiniciar el servicio `ConverData-API`, ningún `session_id` anterior es válido.
3. Ni los logs, ni el Visor de eventos, ni la BD `ConverData` contienen contraseñas (test).
4. En SQL Server, las sesiones de ConverData se identifican por `program_name = 'ConverData'` y por el login del usuario.
5. El usuario A no obtiene la credencial, los `visible_ids` ni los resultados del usuario B aunque manipule los argumentos de las herramientas MCP o el cuerpo de las peticiones (test).
6. Si el proceso de `ConverData-API` se termina de forma abrupta, no queda ningún volcado de memoria en el servidor (test con WER).
