# CN-06 — Residencia de datos: inventario de controles · despliegue en AWS

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Despliegue posterior al piloto on-premise; nada está desplegado.
>
> Aplica en AWS el principio de [F17](../comun/F17-data-residency.md) · equivalente on-premise: [OP-06](../on-premise/OP-06-residencia-datos.md)

**AWS procesa y muestra; no persiste catálogo, preguntas ni auditoría.** Todo lo persistente queda en el SQL Server del banco. En la fase 1a
DiscoveryDataAgent solo lee metadatos: no ejecuta SQL sobre datos de clientes.

| Componente | Riesgo | Control |
|---|---|---|
| Tarea ECS (Web + API) | Catálogo, preguntas y respuestas en memoria | Solo memoria del proceso; la tarea no monta volúmenes persistentes; al parar no queda nada |
| Índice léxico en memoria | Nombres de objetos que el usuario no puede ver | La búsqueda se limita a `visible_ids` del login del usuario; el índice no lleva valores de columnas (F1) |
| SessionVault | Logins SQL de usuarios | Cifrados en memoria durante la sesión; nunca en Secrets Manager, disco ni logs ([CN-03](CN-03-identidad.md)) |
| BD `DiscoveryDataAgent` (on-premise) | Catálogo, conocimiento, curación y auditoría | Permanece en el SQL Server del banco; AWS la alcanza solo por la VPN (PRD §13, decisión 10) |
| Site-to-Site VPN | Tráfico entre la VPC y el banco | Túnel cifrado; el firewall on-premise abre solo el 1433 a las subredes de la tarea; TLS de SQL Server validado (`trust_server_certificate` impide arrancar en qa y prod) |
| Builder | Metadatos y documentos durante la ingesta | Lee con consultas fijas a `sys.*`, sin valores; escribe solo en la BD `DiscoveryDataAgent`; sin almacenamiento en AWS ([CN-02](CN-02-catalogo-memoria.md)) |
| Fuentes de conocimiento (F23) | Datos personales en ejemplos de documentos | Redacción en memoria antes de escribir; el original no se copia |
| Ediciones de curación (F24) | Datos pegados por un responsable | El detector de datos personales rechaza la edición antes de guardarla |
| Bedrock | Contexto de la pregunta (nombres y descripciones de candidatos) | Un solo modelo, por VPC endpoint con el rol de la tarea; *invocation logging* desactivado; `data_mode: real` rechaza proveedores no aptos (PRD §13, decisión 13) |
| Guardrails de Bedrock | Evaluación de texto por otro servicio | No se usa; decisión pendiente de Seguridad de la Información |
| Texto generado por el LLM | Enlaces, HTML, correos u objetos inventados | Se reemplaza por la respuesta determinista (suite `guardas` de `eval gate`) |
| CloudWatch Logs | Preguntas, SQL, nombres de objetos | Logs JSON sin contenido; de los errores, solo el tipo ([CN-05](CN-05-auditoria-observabilidad.md)) |
| ALB | URLs, cabeceras y cuerpos | Interno; las preguntas van en el cuerpo y los access logs no registran cuerpos |
| Respuestas HTTP | Cachés intermedias | `Cache-Control: no-store` en todas las respuestas |
| Secrets Manager | Secretos de servicio | No son datos de clientes; cifrados con KMS y legibles solo por el rol de su tarea |
| Imágenes en ECR | Contenido de la imagen | Solo código y configuración; sin catálogo ni credenciales. La imagen incluye metadatos de prueba para el modo demo, que no arranca en qa ni prod |
| Red de salida | Envío de datos a terceros | Subredes privadas sin salida a internet; solo VPC endpoints y la VPN |
| Notificaciones (F24) | Texto de la pregunta | El mensaje lleva solo el dominio y un enlace |

Fase 1b (consulta de datos, sandbox de análisis F20, capa semántica F21): fuera de este despliegue; sus controles se definirán con la fase 1b (PRD §13, decisión 16).

## Criterios de aceptación
1. La prueba del literal marcado de F17 devuelve 0 coincidencias en CloudWatch Logs, en los access logs del ALB y en Secrets Manager, incluidos literales sembrados en documentos de prueba (F23).
2. El inventario de recursos de la cuenta no contiene ningún almacén de datos de DiscoveryDataAgent: sin buckets de catálogo, sin bases de datos y sin índices de búsqueda.
3. El *model invocation logging* de Bedrock está desactivado y hay una comprobación automática que lo detecta si se activa (mecanismo por confirmar).
4. Las subredes de la tarea no tienen ruta a internet.
5. `discovery-data-agent eval gate` (suites `permisos`, `inyeccion` y `guardas`) aprueba en qa con 0 fugas, también con el modelo de Bedrock.
