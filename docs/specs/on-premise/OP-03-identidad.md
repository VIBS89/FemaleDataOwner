# OP-03 — Identidad y custodia de credenciales · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Implementa en on-premise Microsoft: [F14](../comun/F14-identity.md). El principio y el flujo de herencia de permisos son los de F14.
> Controles implementados y su prueba: [calidad bancaria §3 y §4](../../calidad-bancaria.md).

## Decisión (2026-10-14): logins SQL por usuario
No hay IdP: la pantalla de login de la web (o `POST /auth/login`, alias `/login`) recibe `{login, password, auth, servers[]}` (una sola credencial; `servers` lista los servidores donde se usa, y en el primer arranque `host`, `alias`, `environment`, `setup_token`; modelo `LoginRequest` en `api/discovery_data_agent_api/main.py`),
y valida la credencial en cada servidor marcado abriendo una conexión de prueba (F14). El login
es a la vez la identidad de aplicación y la de datos, y también calcula los `visible_ids` del **descubrimiento** (F22): el usuario solo
ve metadatos de lo que su login puede consultar en cada servidor.

Controles del login y de la sesión, ya construidos (detalle y pruebas en [calidad bancaria §3](../../calidad-bancaria.md)):
- **Bloqueo del login**: 5 fallos en 10 min por usuario y 30 por origen.
- **Visibilidad releída** de SQL Server cada 15 min, para que una revocación de permisos surta efecto sin cerrar la sesión.
- **Código de instalación** (`DISCOVERY_DATA_AGENT_SETUP_TOKEN`) para registrar el primer servidor cuando el inventario está vacío.
- **`data_admin` por lista explícita** (`DISCOVERY_DATA_AGENT_ADMINS_ONLY`, `DISCOVERY_DATA_AGENT_ADMINS`); la autenticación de Windows con la cuenta del proceso está apagada.
- **Roles por nombre solo con el login validado en producción** (`identity_trusted`): la lista de administradores y los responsables solo dan rol si la sesión validó ese login en un servidor con `environment: produccion`, cuando el inventario tiene alguno. Política por confirmar con el banco (PRD §13, pregunta abierta 9).
- Con `DISCOVERY_DATA_AGENT_ENV=qa` o `prod`, la API **se niega a arrancar** con ajustes inseguros ([calidad bancaria §4](../../calidad-bancaria.md)).

**Grupos** (F14): `curation.user_directory` asocia el login SQL con la cuenta de AD de la persona (lo mantiene `data_admin`). Al iniciar
sesión, `DiscoveryDataAgent-API` consulta por LDAP (solo lectura, con su gMSA) los grupos de esa cuenta; sin asociación, `groups = []`.
**Pendiente (HU-13)**: hoy no hay consulta LDAP; los roles salen de la lista de administradores y de la lista de responsables de curación por login
(`curation.steward`, administrada desde Administración).

## Custodia: `SessionVault` en memoria del proceso `DiscoveryDataAgent-API`
- `session_id → {user_id, groups[], credentials: {server → {login, password_enc}}, created_at, last_seen}`.
- `password_enc` se cifra con **Fernet** y una clave efímera generada al arrancar el proceso. **Nunca se escribe a disco**, ni en logs, ni en el Visor de eventos.
- Caducidad: **8 h de inactividad** (deslizante) y **12 h de vida total**; como máximo **5 sesiones por usuario** (al superarlo se cierra la más antigua). Se borra en `/auth/logout`, al revocarla un administrador (`DELETE /admin/sessions/{user_id}`) o al reiniciar el proceso (el usuario vuelve a iniciar sesión).
- `session_id`: token opaco aleatorio de 256 bits. El navegador lo lleva en la cookie `cd_session` (`HttpOnly`, `SameSite=Lax`, `Secure` con HTTPS); los clientes API y MCP lo envían como `Authorization: Bearer`.
- `ConnectionFactory.for_session(session_id, database)` construye la cadena ODBC con `Encrypt=yes` y `ApplicationName=DiscoveryDataAgent`; la contraseña solo vive descifrada durante `pyodbc.connect`. El login y el host no pueden añadir atributos a la cadena.
- La API corre **en un solo proceso** (un worker de uvicorn bajo HttpPlatformHandler) para que todas las peticiones vean el mismo SessionVault.
- El grupo de aplicaciones de `DiscoveryDataAgent-API` tiene el **reciclaje superpuesto desactivado**, para que nunca haya dos procesos con dos SessionVault (OP-07).
- La identidad del usuario sale **solo de la cookie de sesión o del `Bearer`**: ninguna herramienta MCP ni ruta de la API acepta `user_id`, `session_id` ni credenciales como argumento, así que ni el LLM ni un cliente pueden suplantar a otro usuario.
- **Sin volcados de memoria**: el SessionVault vive en RAM, así que Windows Error Reporting no genera volcados de los procesos de DiscoveryDataAgent, `SeDebugPrivilege` queda solo para administradores y el volcado de memoria del sistema se limita al del kernel (OP-06, OP-07). Pendiente: lo aplica el script de endurecimiento de HU-37.

## Cuentas técnicas (no son de usuarios)
| Cuenta | Tipo | Permisos | Dónde se guarda |
|---|---|---|---|
| Procesos de DiscoveryDataAgent (grupos de aplicaciones de IIS de la web y de `DiscoveryDataAgent-API`, y la tarea programada del Builder) | **gMSA** | Lectura/escritura solo en la BD `DiscoveryDataAgent`, con los permisos de escritor de auditoría de F11 (en `audit` solo `INSERT`); lectura de AD por LDAP. La web no tiene permisos sobre ninguna BD | Gestionada por AD (sin contraseña) |
| Login de metadatos (F18) | Login SQL o gMSA de la tarea del Builder | Los de F18: `VIEW DEFINITION`, `VIEW DATABASE STATE`, `SELECT` solo en la réplica, lectura de SSISDB y msdb | Si es login SQL, **DPAPI** con ámbito de la cuenta de servicio |
| Lectura de documentos (F23) | gMSA de la tarea del Builder o cuenta técnica | Solo lectura en la carpeta compartida o en los sitios de SharePoint del dominio piloto | Gestionada por AD |
| Acceso a Bedrock | IAM Roles Anywhere (certificado de la PKI corporativa) | Solo `bedrock:InvokeModel*` sobre el modelo del piloto | Almacén de certificados de Windows, clave privada no exportable |

Estado: las gMSA, DPAPI y el certificado de Bedrock son parte de la instalación (HU-37, HU-35); en desarrollo los secretos llegan por
variables de entorno.

## Evolución: Windows / Active Directory
Si más adelante los usuarios se autentican con AD, IIS puede hacer SSO con autenticación Windows y **delegación restringida de Kerberos**
hasta SQL Server, de modo que no se guarde ninguna contraseña. Requiere SPNs, delegación configurada en la cuenta del servicio y que
Python suplante el token de IIS (pywin32) antes de conectar; hay que validarlo con una prueba de concepto que verifique `SUSER_SNAME()`.

## Criterios de aceptación
1. Los criterios de F14 se cumplen con dos logins SQL de prueba con permisos distintos, tanto en consulta como en descubrimiento, y en dos servidores (producción y QA).
2. Tras reiniciar el proceso `DiscoveryDataAgent-API`, ningún `session_id` anterior es válido.
3. Ni los logs, ni el Visor de eventos, ni la BD `DiscoveryDataAgent` (ni los archivos de catálogo, curación y auditoría mientras existan) contienen contraseñas (test).
4. En SQL Server, las sesiones de DiscoveryDataAgent se identifican por `program_name = 'DiscoveryDataAgent'` y por el login del usuario.
5. El usuario A no obtiene la credencial, los `visible_ids` ni los resultados del usuario B aunque manipule los argumentos de las herramientas MCP o el cuerpo de las peticiones (test).
6. Si el proceso de `DiscoveryDataAgent-API` se termina de forma abrupta, no queda ningún volcado de memoria en el servidor (test con WER).
7. Tras 5 fallos de login en 10 min el login queda bloqueado; una sesión caduca a las 8 h de inactividad o a las 12 h de vida; un sexto inicio de sesión del mismo usuario cierra el más antiguo (tests de [calidad bancaria §3](../../calidad-bancaria.md)).
8. Con `DISCOVERY_DATA_AGENT_ENV=qa` o `prod` y un ajuste inseguro, la API no arranca ([calidad bancaria §4](../../calidad-bancaria.md)).
