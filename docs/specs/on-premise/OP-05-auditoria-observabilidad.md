# OP-05 — Auditoría y observabilidad · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Implementa en on-premise Microsoft: [F11](../comun/F11-audit.md). Controles implementados, pendientes y compuerta de calidad:
> [calidad bancaria](../../calidad-bancaria.md).

## Auditoría en la BD `DiscoveryDataAgent`
- **Esquema `audit`** de la BD `DiscoveryDataAgent` (tablas normales, SQL Server 2016 o posterior), con el modelo de tablas de F11 en tipos de SQL Server (`nvarchar(max)`, `datetime2`, `uniqueidentifier`), incluidas las tablas de descubrimiento (`audit_discovery`, `audit_discovery_feedback`) y `audit_event`; `golden_discovery` vive en `knowledge` y las solicitudes escaladas viven en `curation.request` (`db/discovery_data_agent/002_curacion.sql`; sin `DISCOVERY_DATA_AGENT_DB`, en un archivo).
- La escribe el proceso `DiscoveryDataAgent-API` con su cuenta gMSA y el rol `discovery_data_agent_app`: `INSERT` y `SELECT` en `audit` (la API sirve el historial propio, Administración y las métricas), nunca `UPDATE` ni `DELETE`; `SELECT` para el rol `discovery_data_agent_auditor`.
- **Fail-closed** como en F11: sin registro de auditoría no hay respuesta ni se aplica un cambio (votos, solicitudes y ediciones de curación se auditan antes de aplicarse). Un fallo de escritura deja el evento `audit.write_failed` en el log operativo, sin la pregunta.
- Respaldo, retención y alta disponibilidad: los del plan del DBA para la BD `DiscoveryDataAgent`. La purga por retención (180 días) es una **tarea programada de Windows** (PRD §13, decisión 12).
- **Scorecard** (precisión, calibración, latencia, coste, confirmaciones y las métricas de F25): `GET /admin/metrics` y la vista Métricas de la web; con la BD, además, vistas SQL en el esquema `audit`. Si la organización tiene **Power BI Report Server**, puede leer esas vistas para un tablero.

**Estado (2026-11-16).** Con `DISCOVERY_DATA_AGENT_DB` definida (obligatoria en qa y prod) la auditoría se escribe en el esquema `audit`
(`discovery_data_agent.audit.sqlserver.SqlServerAuditSink`, probada contra SQL Server real en `api/tests/test_audit_db.py`):
- Una pregunta deja `audit_question`, `audit_step` y `audit_discovery` en **una transacción**; los eventos de la API (inicios de sesión,
  accesos denegados, cambios de curación e inventario, lecturas de la auditoría) van a `audit_event`, y cada voto, además, a
  `audit_discovery_feedback` con `time_to_verdict_ms`.
- La cuenta de la API pertenece a `discovery_data_agent_app`: **inserta y lee, pero no puede modificar ni borrar** (`DENY UPDATE, DELETE, ALTER`).
  En qa y prod la API no arranca si su cuenta sí puede; `discovery-data-agent audit verify --db` y `GET /admin/audit/verify` lo comprueban.
- La **purga** es el procedimiento `audit.usp_purge` (se niega con menos de 180 días y deja el evento `audit_purged`); solo la ejecuta
  el rol `discovery_data_agent_maintenance`, con `discovery-data-agent audit purge`. Desde la migración `002` borra también lo que guarda preguntas
  fuera de la auditoría: las dudas escaladas (`curation.request`) y los originales de las confirmaciones
  (`golden.golden_discovery_original`) anteriores al corte; los votos y las plantillas, sin texto libre, se conservan. Falta
  programarla (HU-37).
- **Cambios que fallan**: cada cambio se audita antes de aplicarse; si después falla, queda `<evento>_failed` con el tipo del error
  (`feedback_failed` para un voto). `catalog_build_finished` no lleva el texto del error, solo los ids de los servidores que fallaron.
- La comprobación de permisos (`verify`) incluye que la cuenta no pueda alterar los esquemas `catalog`, `knowledge` ni `curation`.
- La consulta es `GET /admin/audit` (rol `data_admin`; la propia lectura queda auditada) y, para un auditor, `SELECT` directo con el
  rol `discovery_data_agent_auditor`.

Sin `DISCOVERY_DATA_AGENT_DB` (desarrollo) la auditoría va a `data/audit/audit-AAAA-MM-DD.jsonl` con cadena de hashes
(`discovery-data-agent audit verify --dir data/audit`), que detecta la manipulación pero no la impide. Pendiente: las vistas SQL del scorecard
(HU-23) y decidir qué lecturas se auditan además de las preguntas ([calidad bancaria §5](../../calidad-bancaria.md)).

## Rastro en las BDs de datos
- Todas las conexiones de usuarios llevan `ApplicationName=DiscoveryDataAgent`, así que el DBA puede filtrar su actividad con **SQL Server Audit** o Extended Events (`client_app_name`) sin cambios en DiscoveryDataAgent.
- En la fase 1a esas conexiones solo leen metadatos (visibilidad del usuario); en la fase 1b esto complementa la auditoría de F11 (que tiene la pregunta y el contexto) con la evidencia nativa de SQL Server (que tiene lo ejecutado).

## Observabilidad
- Logs JSON rotados en disco del servidor de aplicación (`DISCOVERY_DATA_AGENT_LOG_DIR`), con la lista blanca D5 de F17: lo que no está en la lista se descarta, y de las excepciones solo queda el tipo.
- Errores y arranques o paradas de los procesos en el **Visor de eventos de Windows** (origen `DiscoveryDataAgent`), sin contenido de preguntas.
- Contadores básicos (peticiones, errores y latencia p50/p95 por ruta, tokens, y contadores de bloqueos de login, límite de ritmo, tope de tokens y cadena de auditoría rota) en `GET /health/metrics` para el monitoreo existente (por ejemplo SCOM o Zabbix). Hoy esa ruta exige una sesión `data_admin`; la credencial que usará el monitoreo está por definir (HU-37).
- **Correlación**: cada línea de log y cada registro de auditoría llevan el mismo `trace_id`, que la API devuelve en la respuesta y, en `POST /discover`, en la cabecera `X-Trace-Id`; así se reconstruye una pregunta de punta a punta (IIS → web → API → DiscoverFlow) sin que los logs contengan su texto.
- Construido: logs, Visor de eventos, contadores y `trace_id`. Pendiente: logs de IIS y alertas en el monitoreo del banco (HU-37).

> **Estado al 2026-11-17:** las líneas `http.request` (`api/discovery_data_agent_api/main.py`, `log_event(..., "http.request", ...)`) llevan ruta, método, estado y duración, pero no `trace_id`: la petición no lo conoce hasta que el flujo responde, y el `trace_id` solo viaja en los eventos del flujo (`flows/discover.py`) y en la auditoría. Ver [brechas funcionales](../../wiki/brechas-funcionales.md).

## Alertas
Las recoge el monitoreo existente a partir del Visor de eventos (origen `DiscoveryDataAgent`, un ID de evento por tipo), de `/health/metrics`
y del resultado de las tareas programadas (un código de salida distinto de 0 deja un error en el Visor de eventos).

| Alerta | Condición | Severidad |
|---|---|---|
| Fallo de escritura de auditoría | Cualquier escritura fallida en `audit` (las respuestas quedan bloqueadas por fail-closed) | Crítica |
| Cadena de auditoría rota | `audit verify` falla (mientras la auditoría siga en archivos) | Crítica |
| BD `DiscoveryDataAgent` inaccesible | Fallo de conexión durante más de 1 min | Crítica |
| Latencia | p95 del descubrimiento > 10 s durante 15 min | Alta |
| Bedrock | Tasa de *throttling* o de errores > 5 % durante 5 min, o circuit breaker abierto (F16) | Alta |
| Tareas programadas | Fallo del build nocturno, de la ingesta o de la purga, o regresión de Hit@3 | Alta |
| Certificados | TLS de IIS o certificado de IAM Roles Anywhere a menos de 30 días de expirar | Media |
| Proceso reiniciado | HttpPlatformHandler reinició la web o la API | Media |

## Compuerta de calidad
`discovery-data-agent eval gate` (7 suites: `calidad`, `permisos`, `inyeccion`, `guardas`, `robustez`, `determinismo` y `auditoria`) debe aprobar
antes de cada despliegue; la suite `auditoria` comprueba que cada respuesta deja un registro con los mismos candidatos mostrados y que
sin auditoría no hay respuesta. Detalle, umbrales y evidencia en [calidad bancaria §2](../../calidad-bancaria.md). La CI
(`.github/workflows/calidad.yml`) la corre en cada push y PR.

## Criterios de aceptación
1. Cada pregunta deja exactamente un registro en `audit.audit_question`.
2. El scorecard se genera desde `/admin/metrics` (y, con la BD, desde las vistas del esquema `audit`), incluidas las métricas de descubrimiento de F25 (tiempo hasta "✔", escalamientos, Hit@k del set de evaluación).
3. Los logs, el Visor de eventos y los logs de IIS no contienen preguntas, SQL ni filas.
4. Una sesión de SQL Server Audit filtrada por `DiscoveryDataAgent` muestra las consultas ejecutadas con el login de cada usuario.
5. Una tarea programada de Windows ejecuta `discovery-data-agent eval discovery --min-hit3 <umbral>` cada semana y tras cada cambio de modelo o de catálogo; si Hit@3 baja más de 5 puntos, sale con código distinto de 0 y el monitoreo avisa.
6. Con la BD `DiscoveryDataAgent` inaccesible, las preguntas no reciben respuesta (fail-closed) y se disparan las alertas "BD `DiscoveryDataAgent` inaccesible" y "Fallo de escritura de auditoría".
7. A partir del `trace_id` de una respuesta se encuentran sus líneas de log, sus eventos y su fila de `audit.audit_question`, y ningún log contiene el texto de la pregunta.
8. Mientras la auditoría esté en archivos, `discovery-data-agent audit verify` detecta una fila alterada, borrada o insertada (test).

Estado de los criterios (2026-11-16): 1 y la parte fail-closed de 6 se cumplen en tablas (`api/tests/test_audit_db.py`); 3 (salvo los
logs de IIS), 7 y 8, con la suite `auditoria` y `tests/test_observability.py`; 2 se cumple desde `/admin/metrics` leyendo el esquema
`audit` y faltan las vistas SQL (HU-23); las alertas de 6 y la tarea de 5 dependen de HU-37; 4 es de la fase 1b.
