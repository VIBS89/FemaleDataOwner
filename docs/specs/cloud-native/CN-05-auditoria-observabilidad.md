# CN-05 — Auditoría y observabilidad · cloud native

> Implementa en AWS: [F11](../comun/F11-audit.md)

## Auditoría: on-premise aunque la app esté en la nube
- BD **`ConverData_Audit` en el SQL Server on-prem**, con el modelo de F11 en tipos de SQL Server (`nvarchar(max)`, `datetime2`, `uniqueidentifier`), incluidas las tablas de descubrimiento y curación (`audit_discovery`, `audit_discovery_feedback`, `golden_discovery` original y `curation_request`).
- Las métricas de F25 se calculan con vistas en `ConverData_Audit` (on-prem); a CloudWatch solo llegan contadores sin contenido.
- Escribe `converdata-mcp` a través de Transit Gateway + VPN/DX con el login técnico `converdata_audit_writer`, con los permisos de escritor de F11 (solo `INSERT` en las tablas `audit_*`; `SELECT`/`INSERT`/`UPDATE` en `golden`, `golden_discovery` y `curation_request`). Sus credenciales están en Secrets Manager.
- Es fail-closed (F11): si no se puede escribir, no se responde.
- `GET /audit` lee on-prem en vivo con los permisos del auditor.

## Observabilidad (solo telemetría sin contenido, D5)
- **AgentCore Observability** (OTel) hacia **CloudWatch** y **X-Ray**: latencias por paso, tokens y coste por rol, errores y `trace_id` correlacionado con el `sessionId` de AgentCore.
- Lista blanca de atributos de span; nunca preguntas, SQL ni filas.
- Dashboards y alarmas en CloudWatch: tasa de error, p95, throttling de Bedrock y fallos de escritura de auditoría.

## Criterios de aceptación
1. Cada pregunta deja exactamente un registro en `ConverData_Audit`.
2. Las trazas de una pregunta se ven de punta a punta en CloudWatch (BFF → Runtime → Gateway → MCP → SQL) sin ningún texto de la pregunta.
3. Si se corta la VPN, las respuestas se bloquean (fail-closed) y salta una alarma.
