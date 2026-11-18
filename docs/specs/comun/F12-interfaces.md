# F12 — Interfaces: API, web y MCP · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Publicación y autenticación: **on-premise** → IIS + web Next.js + `ConverData-API` + `/mcp` ([OP-04](../on-premise/OP-04-interfaces.md)) · **cloud native** → los mismos dos contenedores detrás de un ALB interno ([CN-04](../cloud-native/CN-04-interfaces.md))

## Contrato de la API (igual en ambos despliegues)
Rutas de `ConverData-API` (`api/converdata_api/main.py`; PRD §13, decisión 15). La API no se publica directamente: la web le reenvía
`/api/*`, así que el navegador las ve con el prefijo `/api`. Solo `/mcp` se publica desde la API.

**Fase 1a (construidas)**
| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| POST | `/auth/login` (alias `/login`) | `{login, password, auth, servers[]}` (una sola credencial; `servers` lista los servidores donde se usa, y en el primer arranque `host`, `alias`, `environment`, `setup_token`; modelo `LoginRequest` en `api/converdata_api/main.py`) → sesión, servidores y roles; deja la cookie de sesión y devuelve el token para clientes API y MCP (F14) |
| POST · GET | `/auth/logout` (alias `/logout`) · `/auth/me` | Cierra la sesión · usuario, roles, dominios y servidores de la sesión |
| POST | `/discover` | `{question, history?}` → `AnswerEnvelope` con `flow=discover` (F22) |
| POST | `/discover/stream` | Lo mismo por SSE, con eventos `step` (progreso de cada nodo) y `answer` |
| POST | `/discover/feedback` | `{trace_id, asset_key, verdict}` con `verdict` = `confirm` o `reject` (F24). Sin comentario: el voto no guarda texto libre |
| GET | `/assets/{asset_key}` | Ficha del activo: ubicaciones por ambiente, descripción y fuente, reglas, responsables, relaciones, linaje, documentos vinculados |
| GET | `/catalog/databases` · `/catalog/objects` · `/catalog/object` | Exploración del catálogo filtrada por la visibilidad del usuario |
| POST | `/curation/requests` | Escalamiento de una duda al responsable (cualquier usuario, F24) |
| GET/POST/PUT/DELETE | `/curation/*` | Vista de curación: solicitudes y su respuesta, cola de revisión, descripciones y su historial (`GET /curation/history?asset_key=`), diccionario CSV y reglas; solo `steward`/`data_admin` (F24). Ser responsable no da lectura: lo que su login no puede ver responde igual que lo inexistente (OP-04) |
| GET | `/me/requests` · `/me/history` | Solicitudes y preguntas propias |
| GET/PUT/POST/DELETE | `/admin/*` | Inventario de servidores, responsables de curación (`GET`/`PUT /admin/stewards`), build del catálogo, auditoría y su verificación (F11), sesiones y métricas de F25; solo `data_admin` |
| GET | `/health` · `/setup/status` | Públicas: proceso vivo · estado del inventario, del catálogo, del último build y del LLM, sin hosts |
| GET | `/health/metrics` | Contadores para el monitoreo, sin contenido (OP-05) |

> **Estado al 2026-11-17:** la ficha de `GET /assets/{asset_key}` (`object_detail` en `api/converdata_api/main.py`) devuelve ubicaciones (`copies`), descripción, llaves foráneas visibles, reglas, responsables y `referenced_by`; no devuelve linaje ni documentos vinculados. Ver [brechas funcionales](../../wiki/brechas-funcionales.md).

**Fase 1b (pendientes)**
| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| POST | `/ask` | `{question, conversation_id?, database?, confirm_procedure?}` → `AnswerEnvelope`. También enruta a descubrimiento según F3 |
| POST | `/ask/stream` | Lo mismo por SSE |
| POST | `/feedback` | `{trace_id, rating, comment?}` |

- Las preguntas viajan siempre en el cuerpo, nunca en la URL, para que no queden en logs de acceso.
- Toda ruta no pública exige sesión, y la identidad sale solo de la cookie de sesión o del `Authorization: Bearer` (F14).
- Los controles de cada petición (límite de ritmo, tope de tokens, cabeceras, CSRF, tamaño del cuerpo) están en [calidad bancaria §3](../../calidad-bancaria.md).

## Web (Next.js, `web/`)
Sustituye al chat de Chainlit de la versión anterior de esta spec (PRD §13, decisión 11). No guarda credenciales ni conversaciones (F17).
- Vistas: **chat** de descubrimiento, **Catálogo**, **Solicitudes** (dudas propias escaladas), **Curación** (solo `steward`/`data_admin`), **Métricas** y **Administración** (solo `data_admin`).
- Los pasos del flow se muestran en vivo a partir de los eventos SSE de `/discover/stream`.
- Las tarjetas de candidatos llegan antes que la narrativa.

Fase 1b (pendiente): tabla interactiva de resultados (primeras 200 filas, descarga CSV/XLSX generada en streaming), gráfico,
"🔎 Cómo lo obtuve" plegable con SQL o SP, tablas, supuestos, validaciones y confidence, botones 👍/👎, aclaraciones de F3 como botones y
confirmación explícita de los SPs con `side_effects`.

### Respuestas de descubrimiento (F22)
Cada candidato se muestra como una tarjeta con el formato de la propuesta:
```
1. ClientCode                                      Confianza: 92 %
   Base de datos: VBank_ING · Tabla: dbo.Users · Ambiente: Producción · Servidor: SQL Producción Canales
   Descripción: Código que identifica a los clientes digitales registrados.   [revisada por Banca Digital]
   Reglas: BR-ONB-004 Se asigna al completar la verificación de identidad.
   Relacionadas: UserDevices (FK UserId) · DWH.dim.Cliente (ETL ONB_CargaUsuarios)
   [✔ Es este] [✖ No es] [Ver ficha] [Ver relacionadas]
Alternativas: LegalClientId (71 %) · UserId (64 %)
```
- La fuente de la descripción siempre es visible; las `generated` se marcan "sugerida por IA, sin revisar".
- Solo se muestran activos, ubicaciones y relaciones que el usuario puede leer (F14); lo que no puede ver no aparece en la tarjeta.
- Con `knowledge_gap`, se muestra el botón "Preguntar al responsable" (F24).

## Herramientas MCP de `converdata-mcp`
Montado en `/mcp` de `ConverData-API` (`src/converdata/integration/mcp/`); también por stdio para desarrollo (`converdata mcp serve`).
- **Fase 1a (construidas, todas de solo lectura)**: `discover`, `get_asset`, `get_related`, `get_lineage`, `list_business_rules`,
  `find_alternatives` (F22–F24), `search_catalog`, `where_is`, `estate_overview` y `find_join_path` entre BDs (F19).
  `discover` devuelve el `AnswerEnvelope` con `flow=discover`.
- **Fase 1b (pendientes)**: `ask`, `describe_table`, `lookup_values`, `validate_sql`, `run_select`, `list_procedures`, `exec_procedure`,
  `list_metrics` (F21) y `analyze` (F20). `run_select` siempre llama primero a `validate_sql`; no hay forma de ejecutar sin validar.
- Para un cliente externo (Claude Desktop o Claude Code), basta normalmente con `discover` (fase 1a) o `ask` (fase 1b).
- **Escrituras**: el feedback y la curación (crear, responder y cerrar solicitudes; editar descripciones, reglas y vínculos) no se
  publican como herramientas MCP. Hoy su único camino son las rutas `/discover/feedback` y `/curation/*` de la API, que comprueban el rol
  (`steward`/`data_admin`) y auditan antes de aplicar el cambio; así ambos despliegues escriben por el mismo código.
- La identidad del usuario llega por el contexto autenticado de la petición, **nunca como argumento** que el LLM pueda modificar (F14).
- `/mcp` respeta el mismo límite de ritmo y el mismo tope de tokens que la API.

## Criterios de aceptación
1. Flujo E2E en la web: pregunta → tarjetas de candidatos → "✔ Es este" → el registro aparece en auditoría y en golden discovery. En la fase 1b: pregunta → tabla, gráfico y SQL → 👍 → auditoría y golden.
2. `/discover` (y `/ask` en la fase 1b) sin autenticación devuelve 401.
3. Desde Claude Code, la herramienta `discover` (y `ask` en la fase 1b) devuelve un `AnswerEnvelope`.
4. Flujo E2E de descubrimiento: pregunta de la propuesta (onboarding digital) → tarjetas de candidatos → "✔ Es este" → registro en
   `audit_discovery_feedback` y aumento del contador de `golden_discovery`.
