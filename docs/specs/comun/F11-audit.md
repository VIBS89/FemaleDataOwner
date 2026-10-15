# F11 — Auditoría y trazabilidad · común

> Almacenamiento por entorno: **cloud native** → `ConverData_Audit` en SQL Server on-prem vía VPN ([CN-05](../cloud-native/CN-05-auditoria-observabilidad.md)) · **on-premise** → esquema `audit` de la BD `ConverData` en SQL Server ([OP-05](../on-premise/OP-05-auditoria-observabilidad.md))

## Historia de usuario
Como **auditor o administrador**, quiero saber quién preguntó qué, qué SQL se ejecutó, sobre qué objetos, cuánto costó y
cómo valoró el usuario la respuesta.

## Modelo de datos (el mismo en ambos entornos)
```
audit_question(trace_id PK, ts, sql_login, client{ui|api|mcp}, question, rewritten_question,
               intent, databases, status, confidence, total_ms)
audit_step(id PK, trace_id FK, step{intent|link|values|plan|validate|execute|verify|analyze},
           attempt, started_at, duration_ms, model, prompt_tokens, completion_tokens, ok, error)
audit_query(id PK, trace_id FK, attempt, kind{sql|procedure}, statement, params_hash,
            tables_used, validation_json, plan_cost, est_rows, actual_rows, truncated, db_ms, sql_error)
audit_feedback(id PK, trace_id FK, ts, rating{-1|1}, comment)
golden(id PK, question, sql|procedure, params, template, database, tables_used, approved_by, created_at)

-- DiscoverFlow (F22) y curación (F24)
audit_discovery(id PK, trace_id FK, rank, asset_key, environment, confidence, description_source,
                kind{candidate|alternative|related})
audit_discovery_feedback(id PK, trace_id FK, ts, asset_key, verdict{confirm|reject|correct_is},
                         correct_asset_key, actor_role{consumer|steward}, time_to_verdict_ms)
golden_discovery(id PK, question, template, asset_keys, confirmed_by, confirmations, rejected, created_at)
curation_request(id PK, trace_id FK, ts, domain, assigned_group, status{open|answered|no_source|closed},
                 answer_kind, answered_at, answered_by_group)
```
- `audit_question.flow` indica `discover` o `ask`, y `audit_question.user_group` guarda el perfil (ingeniería, analítica, BI, PO)
  para las métricas por perfil de F25. `time_to_verdict_ms` es la base de la métrica "tiempo de localización".
- **No se guardan datos de resultado**, solo metadatos (número de filas y nombres de columnas).
- Los parámetros se guardan como hash, salvo que la configuración indique `audit.store_params: true`.
- Retención configurable (por defecto 180 días) con un job de purga.
- **Fail-closed**: si no se puede escribir la auditoría, la respuesta no se entrega (`audit.fail_open: true` solo en dev).

## Trazabilidad
- `trace_id` se propaga por el flow, los logs y el header `X-Trace-Id`.
- Los logs y la telemetría **no contienen contenido**: ni preguntas, ni SQL, ni filas (F17). El texto completo solo está en la auditoría.

## Criterios de aceptación
1. Cada llamada a `/ask` crea exactamente una fila en `audit_question` y N filas en `audit_step`.
2. `GET /audit?user=…&from=…` filtra correctamente; solo lo usan los roles `auditor`/`admin` (lista en la configuración).
3. Ningún campo de auditoría contiene contraseñas (test).
4. Si la auditoría falla, la respuesta no se entrega en prod (test con el almacén caído).
5. Cada respuesta del DiscoverFlow crea una fila en `audit_discovery` por candidato, alternativa y relación mostrados.
