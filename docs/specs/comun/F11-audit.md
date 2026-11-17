# F11 — Auditoría y trazabilidad · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Almacenamiento: esquema `audit` de la BD `ConverData` en SQL Server, on-premise en los dos despliegues ([OP-05](../on-premise/OP-05-auditoria-observabilidad.md), [CN-05](../cloud-native/CN-05-auditoria-observabilidad.md))

## Historia de usuario
Como **auditor o administrador**, quiero saber quién preguntó qué, qué SQL se ejecutó, sobre qué objetos, cuánto costó y
cómo valoró el usuario la respuesta.

## Modelo de datos
Fase 1a, tal como está en `db/converdata/001_esquemas.sql`:
```
audit_question(trace_id PK, ts, user_id, client{web|ui|api|mcp|cli}, flow{discover|ask},
               question, intent, databases, status, confidence, total_ms)
audit_step(id PK, trace_id FK, step{intent|retrieve|rerank|expand|respond|…},
           attempt, started_at, duration_ms, model, ok, error, detail)
audit_discovery(id PK, trace_id FK, rank, asset_key, environment, confidence, description_source,
                kind{candidate|alternative|related})
audit_discovery_feedback(id PK, trace_id FK, ts, user_id, asset_key, verdict{confirm|reject|correct_is},
                         correct_asset_key, actor_role{consumer|steward}, time_to_verdict_ms)
audit_event(id PK, ts, kind, user_id, trace_id, data_json)   -- inicios de sesión, accesos denegados, cambios de
                                                             -- curación e inventario, builds, purgas, conflictos
knowledge.golden_discovery(id PK, template, asset_keys, confirmed_by, confirmations, rejected, created_at)
```
Pendiente o de la fase 1b (no están en el DDL):
```
audit_question: sql_login, user_group, rewritten_question      -- user_group: perfil para las métricas de F25 (HU-13)
audit_step: prompt_tokens, completion_tokens                   -- hoy los tokens solo se cuentan en /health/metrics
curation.curation_request(id PK, trace_id, ts, domain, assigned_group, status, answer_kind, …)  -- hoy en archivo
audit_query, audit_feedback, golden                            -- AskFlow, fase 1b
```
- `user_id` es el login SQL del usuario (F14). En la fase 1b, `sql_login` será el login con el que se consultó;
  `user_group` guardará el perfil (ingeniería, analítica, BI, PO) para las métricas por perfil de F25, cuando exista el directorio de usuarios (HU-13).
  `time_to_verdict_ms` es la base de la métrica "tiempo de localización".
- Pasos `retrieve`, `rerank`, `expand` y `respond` son los del DiscoverFlow (F22); el resto, los del AskFlow.
- **No se guardan datos de resultado**, solo metadatos (número de filas y nombres de columnas).
- Los parámetros se guardan como hash, salvo que la configuración indique `audit.store_params: true`.
- Retención de 180 días como mínimo, con una purga programada (`converdata audit purge`; la tarea programada está pendiente, HU-37).
- **Fail-closed**: si no se puede escribir la auditoría, la respuesta no se entrega (`audit.fail_open: true` solo en dev).
- **Permisos del escritor**: `INSERT` en las tablas `audit_*` (nunca `UPDATE` ni `DELETE`, salvo la tarea de purga); `INSERT`/`UPDATE` en
  `golden`, `golden_discovery` y `curation_request`, que cambian de estado (confirmaciones, rechazos, respuestas).

## Estado (2026-11-16)
Con `CONVERDATA_DB` definida la auditoría se escribe en las tablas del esquema `audit` de la BD `ConverData`
(`converdata.audit.sqlserver`), una transacción por pregunta, fail-closed, con una cuenta que no puede modificarla ni borrarla; la purga es
`audit.usp_purge` (`converdata audit purge`), que desde el 2026-11-17 alcanza también las dudas escaladas y los originales de las
confirmaciones. Un cambio anunciado que falla deja además un evento `<evento>_failed` con el tipo del error. Sin la variable, en desarrollo, va a **archivos JSONL con cadena de hashes**
(`api/converdata_api/audit.py`, `converdata.audit.chain`) con el mismo modelo lógico. Detalle en
[OP-05](../on-premise/OP-05-auditoria-observabilidad.md) y [calidad bancaria](../../calidad-bancaria.md).

## Trazabilidad
- `trace_id` se propaga por el flow, los logs y el header `X-Trace-Id`.
- Los logs y la telemetría **no contienen contenido**: ni preguntas, ni SQL, ni filas (F17). El texto completo solo está en la auditoría.

## Criterios de aceptación
1. Cada llamada a `/discover` (y a `/ask` en la fase 1b) crea exactamente una fila en `audit_question` y N filas en `audit_step`.
2. La consulta de auditoría (`GET /admin/audit`, F12) filtra correctamente, solo la usa el rol `data_admin` (lista en la configuración) y la propia lectura queda auditada.
3. Ningún campo de auditoría contiene contraseñas (test).
4. Si la auditoría falla, la respuesta no se entrega en prod (test con el almacén caído).
5. Cada respuesta del DiscoverFlow crea una fila en `audit_discovery` por candidato, alternativa y relación mostrados.
