# CN-03 — Identidad y custodia de credenciales · cloud native

> Implementa en AWS: [F14](../comun/F14-identity.md). El principio y el flujo de herencia de permisos son los de F14.

## Identidad en dos capas
1. **Identidad de aplicación: Amazon Cognito**, federado con el IdP corporativo (por ejemplo Entra ID o Google). Su JWT autentica en el ALB, AgentCore Runtime y AgentCore Gateway. El `sub` de Cognito es el `user_id`.
2. **Identidad de datos: login SQL por usuario**, que determina los permisos.

## Custodia del login SQL
- En el primer uso, el BFF pide el login SQL y lo valida con una conexión de prueba (desde AgentCore Runtime en modo VPC, por la VPN).
- Lo guarda en **AWS Secrets Manager** como `converdata/sql-logins/<cognito_sub>/<server>`, cifrado con una **CMK de KMS dedicada**. La política del secreto y de la clave solo permite `GetSecretValue` al rol de ejecución de `converdata-mcp`, con la condición de tag `user_sub`.
- Expira por política (por defecto 30 días; tag `expires_at` y una Lambda de limpieza) o cuando SQL Server rechaza el login (error 18456): se borra y se vuelve a pedir.
- `converdata-mcp` obtiene el `user_sub` del **JWT propagado por AgentCore Gateway o Runtime** (nunca de un argumento que el LLM pueda modificar) y recupera la credencial. La credencial queda en memoria solo dentro de la **microVM de la sesión** de AgentCore Runtime, aislada por sesión.
- CloudTrail registra cada `GetSecretValue`.

## Pendiente de verificar en stg
Que AgentCore Gateway propaga la identidad del usuario al target `converdata-mcp`. La herencia de permisos depende de ello.

## Evolución recomendada
Si SQL Server se integra con AD, usar Windows/Kerberos con delegación restringida, o migrar a Entra ID, y eliminar el almacenamiento de contraseñas.

## Criterios de aceptación
1. Los criterios de F14 se cumplen en stg.
2. El rol de cualquier otro componente recibe `AccessDenied` al leer un secreto de `converdata/sql-logins/*`.
3. Un usuario A no puede obtener la credencial de un usuario B aunque manipule los argumentos de las herramientas.
