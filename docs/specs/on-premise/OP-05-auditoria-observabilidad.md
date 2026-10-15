# OP-05 — Auditoría y observabilidad · on-premise

> Implementa en on-premise Microsoft: [F11](../comun/F11-audit.md)

## Auditoría en la BD `ConverData`
- **Esquema `audit`** de la BD `ConverData` (SQL Server 2025), con el modelo de tablas de F11 en tipos de SQL Server (`nvarchar(max)`, `datetime2`, `uniqueidentifier`), incluidas las tablas de descubrimiento (`audit_discovery`, `audit_discovery_feedback`); `golden_discovery` vive en `golden` y `curation_request` en `curation`.
- La escribe el servicio `ConverData-API` con su cuenta gMSA (solo `INSERT` en `audit`; `SELECT` para el rol `auditor`).
- **Fail-closed** como en F11.
- Respaldo, retención y alta disponibilidad: los del plan del DBA para la BD `ConverData`. La purga por retención (180 días) es un job de SQL Server Agent.
- **Scorecard** (precisión, calibración, latencia, coste, 👍 y las métricas de F25): vistas SQL en el esquema `audit` y el comando `converdata report scorecard`. Si la organización tiene **Power BI Report Server**, puede leer esas vistas para un tablero.

## Rastro en las BDs de datos
- Todas las conexiones de usuarios llevan `ApplicationName=ConverData`, así que el DBA puede filtrar su actividad con **SQL Server Audit** o Extended Events (`client_app_name`) sin cambios en ConverData.
- Esto complementa la auditoría de F11 (que tiene la pregunta y el contexto) con la evidencia nativa de SQL Server (que tiene lo ejecutado).

## Observabilidad
- Logs JSON (structlog) rotados en disco del servidor de aplicación, con la lista blanca D5 de F17.
- Errores y arranques o paradas de los servicios en el **Visor de eventos de Windows** (origen `ConverData`), sin contenido de preguntas.
- Contadores básicos (peticiones, latencia p50/p95, errores, tokens) expuestos en `/health/metrics` para el monitoreo existente (por ejemplo SCOM o Zabbix).

## Criterios de aceptación
1. Cada pregunta deja exactamente un registro en `audit.audit_question`.
2. El scorecard se genera desde las vistas del esquema `audit`, incluidas las métricas de descubrimiento de F25 (tiempo hasta "✔", escalamientos, Hit@k del set de evaluación).
3. Los logs, el Visor de eventos y los logs de IIS no contienen preguntas, SQL ni filas.
4. Una sesión de SQL Server Audit filtrada por `ConverData` muestra las consultas ejecutadas con el login de cada usuario.
5. Un job de SQL Server Agent ejecuta `converdata eval discovery` cada semana y tras cada cambio de modelo o índice; si Hit@3 baja más de 5 puntos, avisa por Database Mail.
