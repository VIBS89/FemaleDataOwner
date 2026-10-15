# OP-03 — Identidad y custodia de credenciales · on-premise

> Implementa en local: [F14](../comun/F14-identity.md). El principio y el flujo de herencia de permisos son los de F14.

## Una sola identidad: el login SQL
No hay IdP: la pantalla de login de Chainlit (o `POST /login`) recibe `{server, login, password}` y lo valida abriendo una conexión
de prueba. Ese login es a la vez la identidad de aplicación y la de datos.

## Custodia: `SessionVault` en memoria
- `session_id → {server, login, password_enc, created_at, last_seen}`.
- `password_enc` se cifra con **Fernet** y una clave efímera generada al arrancar el proceso. **Nunca se escribe a disco** ni en logs.
- TTL de 8 h con expiración deslizante; se borra en `/logout` o al reiniciar el proceso (el usuario vuelve a iniciar sesión).
- `session_id`: token opaco aleatorio de 256 bits, enviado como `Authorization: Bearer` (API y MCP) o en la sesión de Chainlit.
- `ConnectionFactory.for_session(session_id, database)` construye la cadena ODBC; la contraseña solo vive descifrada durante `pyodbc.connect`.
- Requiere **un solo proceso** (o sticky sessions). Escalar horizontalmente queda fuera del alcance on-premise.

## Criterios de aceptación
1. Los criterios de F14 se cumplen con dos logins SQL de prueba con permisos distintos.
2. Tras reiniciar el contenedor, ningún `session_id` anterior es válido.
3. Un volcado de logs no contiene contraseñas (test).
