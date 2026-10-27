# OP-05 — Auditoría y observabilidad · on-premise

> Implementa en on-premise Microsoft: [F11](../comun/F11-audit.md)

## Auditoría en la BD `ConverData`
- **Esquema `audit`** de la BD `ConverData` (SQL Server 2025), con el modelo de tablas de F11 en tipos de SQL Server (`nvarchar(max)`, `datetime2`, `uniqueidentifier`), incluidas las tablas de descubrimiento (`audit_discovery`, `audit_discovery_feedback`); `golden_discovery` vive en `golden` y `curation_request` en `curation`.
- La escribe el servicio `ConverData-API` con su cuenta gMSA, con los permisos de escritor de F11 (solo `INSERT` en `audit`; `INSERT`/`UPDATE` en `golden.golden_discovery` y `curation.curation_request`); `SELECT` para el rol `auditor`.
- **Fail-closed** como en F11.
- Respaldo, retención y alta disponibilidad: los del plan del DBA para la BD `ConverData`. La purga por retención (180 días) es un job de SQL Server Agent.
- **Scorecard** (precisión, calibración, latencia, coste, 👍 y las métricas de F25): vistas SQL en el esquema `audit` y el comando `converdata metrics report` de F25. Si la organización tiene **Power BI Report Server**, puede leer esas vistas para un tablero.

## Rastro en las BDs de datos
- Todas las conexiones de usuarios llevan `ApplicationName=ConverData`, así que el DBA puede filtrar su actividad con **SQL Server Audit** o Extended Events (`client_app_name`) sin cambios en ConverData.
- Esto complementa la auditoría de F11 (que tiene la pregunta y el contexto) con la evidencia nativa de SQL Server (que tiene lo ejecutado).

## Observabilidad
- Logs JSON (structlog) rotados en disco del servidor de aplicación, con la lista blanca D5 de F17.
- Errores y arranques o paradas de los servicios en el **Visor de eventos de Windows** (origen `ConverData`), sin contenido de preguntas.
- Contadores básicos (peticiones, latencia p50/p95, errores, tokens, bloqueos de Guardrails) expuestos en `/health/metrics` para el monitoreo existente (por ejemplo SCOM o Zabbix).
- **Correlación**: cada línea de log, cada evento y cada fila de `audit.audit_question` llevan el mismo `trace_id`, que la API devuelve en la cabecera `X-Trace-Id`; así se reconstruye una pregunta de punta a punta (IIS → API → DiscoverFlow → SQL Server) sin que los logs contengan su texto.

## Alertas
Las recoge el monitoreo existente a partir del Visor de eventos (origen `ConverData`, un ID de evento por tipo) y de `/health/metrics`; los jobs
de SQL Server Agent avisan además por Database Mail.

| Alerta | Condición | Severidad |
|---|---|---|
| Fallo de escritura de auditoría | Cualquier escritura fallida en `audit` (las respuestas quedan bloqueadas por fail-closed) | Crítica |
| BD `ConverData` inaccesible | Fallo de conexión durante más de 1 min | Crítica |
| Latencia | p95 del descubrimiento > 10 s durante 15 min | Alta |
| Bedrock | Tasa de *throttling* o de errores > 5 % durante 5 min, o circuit breaker abierto (F16) | Alta |
| Jobs de SQL Server Agent | Fallo del refresco, de la ingesta o de la purga, o regresión de Hit@3 | Alta |
| Certificados | TLS de IIS o certificado de IAM Roles Anywhere a menos de 30 días de expirar | Media |
| Proceso reiniciado | HttpPlatformHandler o el administrador de servicios reinició un proceso de ConverData | Media |

## Criterios de aceptación
1. Cada pregunta deja exactamente un registro en `audit.audit_question`.
2. El scorecard se genera desde las vistas del esquema `audit`, incluidas las métricas de descubrimiento de F25 (tiempo hasta "✔", escalamientos, Hit@k del set de evaluación).
3. Los logs, el Visor de eventos y los logs de IIS no contienen preguntas, SQL ni filas.
4. Una sesión de SQL Server Audit filtrada por `ConverData` muestra las consultas ejecutadas con el login de cada usuario.
5. Un job de SQL Server Agent ejecuta `converdata eval discovery` cada semana y tras cada cambio de modelo o índice; si Hit@3 baja más de 5 puntos, avisa por Database Mail.
6. Con la BD `ConverData` inaccesible, las preguntas no reciben respuesta (fail-closed) y se disparan las alertas "BD `ConverData` inaccesible" y "Fallo de escritura de auditoría".
7. A partir del `trace_id` de una respuesta se encuentran sus líneas de log, sus eventos y su fila de `audit.audit_question`, y ningún log contiene el texto de la pregunta.
