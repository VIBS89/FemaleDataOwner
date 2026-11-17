# CN-04 — Publicación de interfaces · despliegue en AWS

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Despliegue posterior al piloto on-premise; nada está desplegado.
>
> Implementa en AWS: [F12](../comun/F12-interfaces.md) · equivalente on-premise: [OP-04](../on-premise/OP-04-interfaces.md). El contrato de la API, el chat y las herramientas MCP son los de F12.

| Interfaz | Dónde corre | Autenticación |
|---|---|---|
| Entrada | **ALB interno**, HTTPS 443 con certificado de ACM; `/` → Web, `/mcp` → API. Equivale a IIS con la PKI corporativa. Solo alcanzable desde la red corporativa por la VPN (PRD §13, decisión 11) | — |
| Web (Next.js, puerto 3000) | Contenedor `web/Dockerfile` de la tarea: chat con tarjetas de candidatos, Curación y Administración. Reenvía `/api/*` a la API en `localhost:8000` (`API_URL`); no guarda credenciales ni conversaciones | Cookie de sesión `cd_session` |
| `ConverData-API` (FastAPI, puerto 8000) | Contenedor `api/Dockerfile` de la misma tarea, un worker. No se publica salvo `/mcp` | Cookie o Bearer |
| MCP (`/mcp`) | El servidor MCP montado en la API: `discover`, `search_catalog`, `where_is`, `get_asset`, `get_related`, `find_alternatives`, `list_business_rules`, `get_lineage`, `find_join_path`, `estate_overview` | Token de sesión de `/auth/login` como **Bearer**; hereda los permisos del login SQL |

## Rutas de la API (PRD §13, decisión 15)
Son las del código; el navegador las ve bajo `/api/` porque la web las reenvía.

| Ruta | Uso | Acceso |
|---|---|---|
| `/auth/login` | Inicio de sesión con el login SQL por servidor | Público |
| `/discover`, `/discover/feedback` | Pregunta de descubrimiento y confirmación ✔/✖ | Sesión |
| `/assets/{asset_key}` | Ficha de un activo, filtrada por permisos | Sesión |
| `/curation/*` | Dudas escaladas, descripciones, diccionario, reglas | Rol `steward` o `data_admin` |
| `/admin/*` | Inventario, construcción del catálogo, auditoría, sesiones, métricas | Rol `data_admin` |
| `/health` | Comprobación de salud del ALB y del contenedor | Público |
| `/mcp` | Clientes MCP | Bearer |

En qa y prod no se publican `/docs` ni `/openapi.json`.

## Límites y controles (los aplica la API, no la red)
- **Ritmo por usuario**: 30 preguntas por minuto (`CONVERDATA_RATE_LIMIT`); en `/mcp`, el mismo cupo para `discover` y cuatro veces más para las herramientas de detalle. Abrir más sesiones no da más cupo.
- **Tope diario de tokens** de LLM por usuario (`CONVERDATA_TOKEN_LIMIT`; 0 = sin tope): al agotarlo, rechaza con 429 o responde sin LLM (`CONVERDATA_TOKEN_LIMIT_MODE=deterministic`). También en `/mcp`.
- Cuerpo máximo de 4 MB, verificación de `Origin` en cambios de estado con cookie (CSRF), cabeceras de seguridad, `Cache-Control: no-store` y HSTS.
- `CONVERDATA_MCP_HOSTS` con el nombre del ALB es obligatorio con `/mcp` activo; `CONVERDATA_CORS_ORIGINS` y `CONVERDATA_PUBLIC_URL` llevan su URL `https://`.
- Los contadores viven en memoria: se reinician con la tarea.
- Los access logs del ALB, si se activan, no incluyen cuerpos; las preguntas viajan en el cuerpo, nunca en la URL.
- **Notificaciones a responsables** (F24): webhook `https` de Teams con el dominio y un enlace, sin el texto de la pregunta. La tarea no tiene salida a internet, así que su ruta de red está por confirmar.

Por confirmar: `CONVERDATA_TRUST_PROXY` detrás del ALB (el bloqueo por origen necesita la IP real del cliente) y el tiempo de inactividad del ALB para las conexiones de `/mcp`.

## Criterios de aceptación
1. Sin sesión, cualquier ruta no pública devuelve 401; un `consumer` recibe 403 en `/curation/*` y `/admin/*`.
2. El ALB no resuelve ni responde desde fuera de la red corporativa.
3. Un cliente MCP con un Bearer válido invoca `discover` y recibe solo activos visibles para ese login; sin Bearer, 401.
4. La pregunta 31 de un usuario en un minuto devuelve 429, también si abre otra sesión o usa `/mcp`.
5. Con el tope diario agotado, `/discover` rechaza o responde en modo determinista según la configuración.
6. El puerto 8000 de la API no es alcanzable desde la red corporativa salvo `/mcp` a través del ALB.
