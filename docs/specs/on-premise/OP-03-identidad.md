# OP-03 — Identidad y custodia de credenciales · on-premise

> Implementa en on-premise Microsoft: [F14](../comun/F14-identity.md). El principio y el flujo de herencia de permisos son los de F14.

## Decisión (2026-10-14): logins SQL por usuario
No hay IdP: la pantalla de login de Chainlit (o `POST /login`) recibe `{server, login, password}` y lo valida abriendo una conexión
de prueba. Ese login es a la vez la identidad de aplicación y la de datos, y también calcula los `visible_ids` del **descubrimiento**
(F22): el usuario solo ve metadatos de lo que su login puede consultar.

## Custodia: `SessionVault` en memoria del servicio `ConverData-API`
- `session_id → {server, login, password_enc, created_at, last_seen}`.
- `password_enc` se cifra con **Fernet** y una clave efímera generada al arrancar el servicio. **Nunca se escribe a disco**, ni en logs, ni en el Visor de eventos.
- TTL de 8 h con expiración deslizante; se borra en `/logout` o al reiniciar el servicio (el usuario vuelve a iniciar sesión).
- `session_id`: token opaco aleatorio de 256 bits, enviado como `Authorization: Bearer` (API y MCP) o en la sesión de Chainlit.
- `ConnectionFactory.for_session(session_id, database)` construye la cadena ODBC con `Encrypt=yes` y `ApplicationName=ConverData`; la contraseña solo vive descifrada durante `pyodbc.connect`.
- El servicio corre **en un solo proceso** (un worker de uvicorn bajo HttpPlatformHandler) para que todas las peticiones vean el mismo SessionVault.
- El servidor de aplicación no permite *dumps* de memoria del servicio a usuarios no administradores (protección del proceso).

## Cuentas técnicas (no son de usuarios)
| Cuenta | Tipo | Permisos | Dónde se guarda |
|---|---|---|---|
| Servicios de Windows (`ConverData-*`) | **gMSA** | Lectura/escritura solo en la BD `ConverData` | Gestionada por AD (sin contraseña) |
| Login de metadatos (F18) | Login SQL o gMSA | `VIEW DEFINITION`, `VIEW DATABASE STATE`, `SELECT` solo en la réplica para sketches | Si es login SQL, **DPAPI** con ámbito de la cuenta de servicio |
| Acceso a Bedrock | IAM Roles Anywhere (certificado de la PKI corporativa) | Solo `bedrock:InvokeModel*` | Almacén de certificados de Windows, clave privada no exportable |

## Evolución: Windows / Active Directory
Si más adelante los usuarios se autentican con AD, IIS puede hacer SSO con autenticación Windows y **delegación restringida de Kerberos**
hasta SQL Server, de modo que no se guarde ninguna contraseña. Requiere SPNs, delegación configurada en la cuenta del servicio y que
Python suplante el token de IIS (pywin32) antes de conectar; hay que validarlo con una prueba de concepto que verifique `SUSER_SNAME()`.

## Criterios de aceptación
1. Los criterios de F14 se cumplen con dos logins SQL de prueba con permisos distintos, tanto en consulta como en descubrimiento.
2. Tras reiniciar el servicio `ConverData-API`, ningún `session_id` anterior es válido.
3. Ni los logs, ni el Visor de eventos, ni la BD `ConverData` contienen contraseñas (test).
4. En SQL Server, las sesiones de ConverData se identifican por `program_name = 'ConverData'` y por el login del usuario.
