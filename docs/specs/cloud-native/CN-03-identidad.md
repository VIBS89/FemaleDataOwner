# CN-03 — Identidad y custodia de credenciales · despliegue en AWS

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Despliegue posterior al piloto on-premise; nada está desplegado.
>
> Implementa en AWS: [F14](../comun/F14-identity.md) · equivalente on-premise: [OP-03](../on-premise/OP-03-identidad.md). El principio y el flujo de herencia de permisos son los de F14.

## Una sola identidad: el login SQL del usuario
- El inicio de sesión es **el mismo que on-premise**: el usuario entra con su propio login SQL, uno por servidor (`POST /auth/login`), y `ConverData-API` lo valida con una conexión de prueba por la VPN. No hay proveedor de identidad adicional (PRD §13, decisión 11).
- SQL Server sigue siendo la fuente de verdad de los permisos: la API pregunta con el login del propio usuario qué objetos puede ver y lo vuelve a leer cada 15 minutos (`CONVERDATA_VISIBILITY_TTL_S`).
- La autenticación de Windows no existe dentro del contenedor y `CONVERDATA_ALLOW_WINDOWS_AUTH` debe estar apagada en qa y prod.

## Custodia: SessionVault en memoria
- Los logins SQL de los usuarios **no se guardan en ningún almacén**: viven cifrados en la memoria de `ConverData-API` mientras dura la sesión (PRD §13, decisión 14). La clave de cifrado se genera al arrancar el proceso y no sale de él.
- Sesión: 8 h de inactividad, 12 h de vida total, 5 por usuario, revocable por el administrador (`/admin/sessions`). Cookie `cd_session` con `Secure`; el mismo token sirve como Bearer para `/mcp`.
- Bloqueo del login: 5 fallos en 10 minutos por usuario y 30 por origen, 15 minutos de bloqueo.
- Por eso el servicio corre con **una sola tarea y un worker**: un reinicio cierra las sesiones y los usuarios vuelven a entrar.

## Secretos de servicio: Secrets Manager
Equivale a DPAPI on-premise. Solo secretos del servicio, inyectados como variables de entorno de la tarea:

| Secreto | Quién lo lee |
|---|---|
| Login de metadatos del Builder | Solo el rol de la tarea del Builder |
| Código de instalación (`CONVERDATA_SETUP_TOKEN`), mientras no exista inventario | Tarea de la API |
| Login con el que la API escribe en la BD `ConverData` (catálogo, curación, auditoría) | Tarea de la API (y del Builder para `catalog`); por confirmar con HU-04 y HU-20 |
| Webhook de notificaciones (`CONVERDATA_NOTIFY_WEBHOOK`), si se usa | Tarea de la API |

## Roles de IAM
| Rol | Permisos |
|---|---|
| Tarea de la API | `bedrock:InvokeModel` sobre el modelo elegido; lectura de sus secretos; escritura en su grupo de logs |
| Tarea del Builder | Lectura del secreto del login de metadatos; Bedrock solo si genera descripciones; escritura en su grupo de logs |
| EventBridge Scheduler | `ecs:RunTask` sobre la definición del Builder |

Bedrock se llama con el rol de la tarea, sin claves (on-premise: IAM Roles Anywhere).

## Roles y grupos de la aplicación
Igual que on-premise: `data_admin` por lista explícita (`CONVERDATA_ADMINS_ONLY=1` + `CONVERDATA_ADMINS`), `steward` por los responsables
de dominio de Curación (F24) y `consumer` para el resto. El uso de grupos de Active Directory (HU-13) está **por confirmar** en ambos despliegues.

## Criterios de aceptación
1. Los criterios de F14 se cumplen en qa.
2. Ningún secreto de Secrets Manager contiene un login de usuario; tras una sesión de prueba, la búsqueda del login y su contraseña en secretos, logs y variables de la tarea devuelve 0 coincidencias.
3. El rol de la tarea de la API recibe `AccessDenied` al leer el secreto del login de metadatos.
4. Dos usuarios con permisos distintos hacen la misma pregunta y cada uno ve solo sus objetos.
5. Al reiniciar la tarea, las sesiones anteriores devuelven 401.
6. Ser `sysadmin` de un servidor no da el rol `data_admin` si el login no está en `CONVERDATA_ADMINS`.
