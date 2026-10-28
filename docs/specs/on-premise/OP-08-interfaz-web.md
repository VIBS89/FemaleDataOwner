# OP-08 — Interfaz web Next.js en IIS · on-premise

> Implementa en on-premise Microsoft la parte de chat y pantallas de [F12](../comun/F12-interfaces.md). **Sustituye a Chainlit** en
> [OP-01](OP-01-despliegue-local.md), [OP-04](OP-04-interfaces.md) y [OP-07](OP-07-instalacion-operacion.md) (⚠️ propuesto: lo confirma el
> Product Owner; es la decisión abierta n.º 2 del [reparto](../../backlog/reparto-5-devs.md#5-riesgos-y-decisiones-abiertas) y afecta a HU-17).
> Specs relacionadas: [OP-03](OP-03-identidad.md) sesión · [OP-05](OP-05-auditoria-observabilidad.md) logs · [OP-06](OP-06-residencia-datos.md) residencia.

## Contexto (revisión del 2026-10-27)
Las specs on-premise describen un chat en **Chainlit**, pero la solución ya tiene una aplicación **Next.js 15 + shadcn** (`web/`) con login,
chat con streaming, catálogo, curación, solicitudes, métricas y administración, que la demo usa de punta a punta. Mantener las dos interfaces
duplica trabajo, así que esta spec traslada a Next.js los requisitos que OP-04 ponía sobre Chainlit y fija cómo se publica en IIS.

Huecos que cierra:
| # | Hueco | Dónde estaba |
|---|---|---|
| 1 | La UI real (Next.js, proceso Node) no aparece en el modelo de procesos ni en los prerrequisitos | OP-01, OP-04, OP-07 §Decisión y paso 1 |
| 2 | Rutas: la API expone `/discover`, `/curation/*`…; OP-04 pide `/api/discover`, `/api/curation/*` | OP-04 §API, `api/converdata_api/main.py` |
| 3 | La sesión del navegador viaja en cookie `httpOnly`, no en `Bearer`; OP-03 solo describe `Bearer` y la sesión de Chainlit | OP-03 §Custodia |
| 4 | Streaming: Chainlit usaba WebSockets; el chat Next.js usa respuestas en streaming de `/discover/stream` a través de un proxy | OP-04 §IIS, CA8 |
| 5 | Residencia: Chainlit tenía *data layer*; Next.js puede cachear respuestas o guardar estado en el navegador | OP-06 |

## Decisión: topología
```
IIS :443 (TLS PKI corporativa, HSTS)
 ├─ /mcp, /mcp/*     → ConverData-API  127.0.0.1:8000  (URL Rewrite + ARR; Bearer)
 ├─ /api/admin/*     → ConverData-Builder 127.0.0.1:8100 (restricción por IP + token de servicio, OP-04)
 └─ /*               → ConverData-UI   (HttpPlatformHandler lanza `node server.js` de la salida standalone de Next.js)
                         └─ /api/*  route handler `web/src/app/api/[...path]` → ConverData-API 127.0.0.1:8000/*
```
- **`ConverData-UI`**: salida `output: "standalone"` de Next.js (`web/.next/standalone/server.js` más `.next/static` y `public`),
  lanzada por HttpPlatformHandler con `node`, Node.js 20 LTS instalado por `01-prerrequisitos.ps1`. Escucha en el puerto que pasa
  HttpPlatformHandler (`%HTTP_PLATFORM_PORT%`). No usa `next start` ni `npm` en el servidor.
- **`ConverData-API`** deja de ser aplicación de IIS publicada en `/api`: pasa a escuchar **solo en `127.0.0.1:8000`** (uvicorn, un solo
  proceso) y la publican el proxy de Next.js (`/api/*`) e IIS (`/mcp`). Se supervisa como **servicio de Windows** con acciones de
  recuperación, igual que `ConverData-Builder`, para que IIS no lo recicle y nunca haya dos SessionVault (OP-03, OP-07 CA4).
  ⚠️ propuesto: alternativa equivalente si Plataformas prefiere IIS para la API: aplicación con HttpPlatformHandler, sin reciclaje superpuesto.
- **Equivalencia de rutas**: la ruta pública de F12/OP-04 `/api/<ruta>` es la ruta interna `/<ruta>` de `ConverData-API`. La API **no** se
  renombra; los clientes externos (curl, scripts, SQL Agent) usan siempre la forma pública `https://<servidor>/api/...`. `POST /login` de OP-04
  es `POST /api/login` en público (alias interno `/auth/login`).

## Sesión en el navegador
- `POST /api/login` responde con la cookie de sesión `httpOnly`, `Secure`, `SameSite=Strict`, `Path=/` y sin `Domain`; su valor es el mismo
  `session_id` opaco de OP-03. Clientes no web usan `Authorization: Bearer <session_id>`; la API acepta ambos y **nunca** ambos con valores distintos (401).
- `CONVERDATA_COOKIE_SECURE=1` es obligatorio fuera de `dev`; el arranque falla si `CONVERDATA_ENV` ≠ `dev` y la cookie no es `Secure`.
- El proxy reenvía solo `content-type`, `cookie`, `authorization` y `accept` y devuelve solo `content-type` y `set-cookie`
  (`route.ts` actual); cualquier cabecera nueva pasa por esta spec.
- Las peticiones que cambian estado (`POST`, `PUT`, `DELETE`) exigen `Origin` igual a `CONVERDATA_PUBLIC_URL`; si no, 403 (CSRF).

## Streaming
- El chat consume `POST /api/discover/stream` como flujo de eventos. En IIS: `responseBufferLimit="0"` en el handler de HttpPlatformHandler,
  compresión dinámica desactivada para `text/event-stream` y ARR sin buffering para `/mcp`.
- No se necesitan WebSockets; si se activan para otro uso, no afectan a esta spec.

## Residencia y endurecimiento (complementa OP-06)
| Elemento | Riesgo | Control |
|---|---|---|
| Caché de Next.js (Data Cache, ISR) | Respuestas con nombres de objetos o preguntas en disco | Rutas `force-dynamic`, `cache: "no-store"` en el proxy, sin ISR; `.next/cache` vacío tras un flujo E2E |
| Navegador | Preguntas o candidatos en `localStorage`/`sessionStorage` | Solo preferencias de interfaz (tema); el historial se pide a `/api/me/history` |
| Logs de Node | Cuerpos o cookies en stdout que HttpPlatformHandler guarda en `stdoutLogFile` | `stdoutLogEnabled=false` en piloto; el proxy no registra cuerpos, URLs con consulta ni cabeceras |
| Cabeceras | Clickjacking, *sniffing*, fuga de referer | `Content-Security-Policy` sin orígenes externos, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; `poweredByHeader: false` (ya está) |
| Fuentes y scripts | Llamadas a CDNs desde la red del banco | Todo empaquetado en el build; CSP sin dominios externos |

## Pantallas (contrato con F12 y el backlog)
| Pantalla (`web/src/app`) | Historias | Rol mínimo |
|---|---|---|
| `login` | HU-10 | — |
| `(app)/page.tsx` chat con tarjetas, ✔/✖, "Ver ficha", "Ver relacionadas", "Preguntar al responsable" | HU-14, HU-15, HU-17, HU-30 | consumer |
| `(app)/catalogo` | HU-14 (`/api/assets`) | consumer (solo visibles) |
| `(app)/solicitudes` | HU-30 | consumer |
| `(app)/curacion` (descripciones, reglas, diccionario, cola) | HU-25, HU-28, HU-31 | steward |
| `(app)/metricas` | HU-22, HU-23 | data_admin |
| `(app)/admin` (inventario, construcción del catálogo, auditoría) | HU-18 | data_admin |

Las pantallas ocultan acciones según el rol, pero la autorización la decide **siempre** la API (un 403 de la API es la fuente de verdad).

## Criterios de aceptación
1. Flujo E2E en `https://<servidor>/` (sustituye a OP-04 CA1): login con login SQL → pregunta de onboarding digital → tarjetas con BD,
   ambiente, servidor, responsables y confianza → "✔ Es este" → fila en `audit.audit_discovery_feedback`.
2. Los pasos del flujo aparecen en streaming a través de IIS: el primer evento llega antes de 2 s y antes que la respuesta final (sustituye a OP-04 CA8).
3. `curl https://<servidor>/api/discover` sin cookie ni `Bearer` devuelve 401; `curl http://127.0.0.1:8000/discover` desde otra máquina no conecta.
4. La cookie de sesión tiene `HttpOnly`, `Secure` y `SameSite=Strict`; un `POST /api/discover` con `Origin` ajeno devuelve 403.
5. Tras un flujo E2E completo, la búsqueda de la pregunta y de un nombre de tabla de prueba en `.next/cache`, en los logs de HttpPlatformHandler,
   en los logs W3C de IIS y en `localStorage` da 0 resultados.
6. Un usuario `consumer` que abre `/curacion` o llama a `PUT /api/curation/description` recibe 403 de la API, aunque manipule la interfaz.
7. Matar el proceso `node` de `ConverData-UI` no cierra las sesiones (el SessionVault vive en la API); IIS lo relanza y el usuario sigue dentro.
8. La compilación (`npm run build`) y `npx tsc --noEmit` terminan sin errores y el paquete standalone no contiene `.env` ni `config/models.yaml`.

## Cambios que provoca en otras specs
| Spec | Cambio |
|---|---|
| OP-01 §Decisiones y topología | "Chainlit + FastAPI" → "Next.js (Node) + FastAPI"; la API pasa a `127.0.0.1` |
| OP-04 | Fila "Chat web" y CA1/CA8 sustituidos por esta spec; `/api/*` por equivalencia de rutas |
| OP-07 §Decisión y paso 1 | `ConverData-UI` con Node 20 LTS; `ConverData-API` como servicio de Windows (⚠️ propuesto) |
| OP-03 | Sesión por cookie además de `Bearer` (§Sesión en el navegador) |
| OP-06 | Fila "Chainlit" sustituida por §Residencia de esta spec |
| Backlog | HU-17 se reescribe sobre `web/` (chat Next.js) en lugar de Chainlit |
