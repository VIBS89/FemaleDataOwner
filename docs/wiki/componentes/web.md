# Web (ConverData-Web)

Actualizado el 2026-11-17.

## Para qué sirve
Frontend Next.js 15 (App Router, React 19, Tailwind 4, componentes shadcn/Radix) en `web/`. Es la única cara pública de ConverData: pregunta dónde está un dato, muestra el catálogo que el usuario puede ver, permite curar y administrar. No tiene lógica de negocio ni de permisos: toda decisión la toma `ConverData-API`.

## Lo esencial
- El navegador solo habla con la web. La API no se publica: el proxy `web/src/app/api/[...path]/route.ts` la alcanza por la red interna (`API_URL`) y solo reenvía las rutas que usa la web (`auth`, `login`, `setup`, `me`, `discover`, `catalog`, `assets`, `curation` y `admin`); el resto (`/api/mcp`, `/api/health/metrics`, `/api/docs`) responde 404.
- La web no guarda credenciales. La contraseña viaja una vez en `POST /api/login`; la sesión es una cookie `httpOnly` y `SameSite=Lax` que fija la API.
- Los roles (`consumer`, `steward`, `data_admin`) vienen de `GET /auth/me`. La web solo oculta pantallas; la API vuelve a comprobar cada llamada.
- Las conversaciones viven en el `localStorage` del navegador, por usuario. El servidor no guarda chats. Al cerrar sesión se borran (`session-provider.tsx`).
- No hay pruebas automáticas de la web. La CI comprueba tipos, lint y compilación.

## Responsabilidades
- Iniciar sesión (login SQL por servidor, o autenticación de Windows si la API la permite) y primer arranque (registrar el servidor).
- Chat de descubrimiento con respuesta por pasos (SSE), confirmación o rechazo de candidatos y escalamiento al responsable.
- Catálogo navegable y ficha del activo (columnas, relaciones, reglas y responsables).
- Curación (responsables), métricas y administración (administradores de datos).
- Reenviar a la API sin interpretar, sin cachear y sin exponer su URL.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| Layout raíz | `web/src/app/layout.tsx` | Idioma `es`, `SessionProvider`, `TooltipProvider`, avisos (`sonner`). |
| Layout de la app | `web/src/app/(app)/layout.tsx` | Espera la sesión; sin usuario muestra "Cargando…". Monta `ConversationsProvider`, la barra lateral y el contenido. |
| Preguntar | `web/src/app/(app)/page.tsx` | Chat. Llama `discoverStream`, `feedback` y `escalate`. Si no hay catálogo, invita a descubrir esquemas (solo admin). |
| Catálogo | `web/src/app/(app)/catalogo/page.tsx` | Lista de BDs y objetos con filtros (todo, tablas, vistas, SPs) y búsqueda. Abre la ficha. |
| Mis solicitudes | `web/src/app/(app)/solicitudes/page.tsx` | Dudas que el usuario escaló y su respuesta (`GET /me/requests`). |
| Curación | `web/src/app/(app)/curacion/page.tsx` | Pestañas: solicitudes, revisión, reglas y diccionario CSV. Solo con rol `steward`. |
| Métricas | `web/src/app/(app)/metricas/page.tsx` | Tablero de 7, 30 o 90 días (`GET /admin/metrics`). Solo `data_admin`. |
| Administración | `web/src/app/(app)/admin/page.tsx` | Pestañas: descubrir esquemas, servidores, responsables, auditoría y manual de desarrollo. Solo `data_admin`. |
| Asistente "Conectar base de datos" | `web/src/components/connect-database-wizard.tsx` | Diálogo de la pestaña Servidores: host, nombre visible, ambiente y certificado → "Probar conexión" (`POST /admin/inventory/probe`); casillas por base con tablas y vistas (las sin acceso, deshabilitadas con el motivo; "todas las accesibles" e "incluir las futuras" = `*`); "Conectar y descubrir" (`POST /admin/inventory/connect`), avance del build y resumen con enlaces al chat y al Catálogo. El botón de cada fila lo abre sobre ese servidor para añadirle bases. |
| Avance del build | `web/src/components/build-progress.tsx` | `useBuildJob` (sondea `GET /admin/catalog/build` cada 1,2 s y avisa al terminar) y `BuildSteps`; los usan "Descubrir esquemas" y el asistente. |
| Login | `web/src/app/login/page.tsx` | Contraseña, selección de servidores, interruptor de autenticación de Windows y formulario de primer arranque (con código de instalación si la API lo pide). |
| Proxy | `web/src/app/api/[...path]/route.ts` | Reenvía GET, POST, PUT, PATCH y DELETE a `API_URL`. |
| Cliente de la API | `web/src/lib/api.ts` | Objeto `api` con una función por endpoint; `ApiError`; lector de SSE. |
| Tipos | `web/src/lib/types.ts` | Contrato con la API (`AnswerEnvelope`, `User`, `SetupStatus`, `BuildJob`, `Metrics`…). |
| Formato | `web/src/lib/format.ts` | Etiquetas de ambiente (`ENV_LABEL`) y de tipo (`KIND_LABEL`), fechas y números. |
| Sesión | `web/src/components/session-provider.tsx` | Contexto `useSession()`: `user`, `status`, `isAdmin`, `isSteward`, `logout`. |
| Barra lateral | `web/src/components/app-sidebar.tsx` | Menú por rol, conversaciones recientes, usuario y servidores conectados. |
| Chat | `web/src/components/chat/` | `assistant-message`, `candidate-card`, `composer`, `conversations` (almacén local), `thinking`. |
| Ficha | `web/src/components/asset-sheet.tsx` | Panel lateral con columnas, relaciones, reglas y responsables; botón "Historial" para responsables. |
| Historial | `web/src/components/description-history.tsx` | Versiones de una descripción con autor y fecha (`GET /curation/history`). |
| Markdown | `web/src/components/markdown.tsx` | Visor mínimo (títulos, listas, tablas, código). Construye elementos de React, nunca inserta HTML. Lo usa el manual. |
| Otros | `confidence.tsx`, `source-badge.tsx`, `page-header.tsx`, `brand.tsx`, `ui/` | Indicadores y componentes shadcn. |

## Cómo funciona
1. `SessionProvider` pide `GET /setup/status` y `GET /auth/me`. Con 401 manda a `/login`.
2. El login envía `POST /login` con `auth: "sql"` o `"windows"`. En el primer arranque (sin inventario) añade `host`, `alias`, `environment`, `trust_server_certificate` y `setup_token`.
3. Cualquier 401 posterior dispara el evento `converdata:unauthorized`; el proveedor limpia el usuario y vuelve a `/login`.
4. Preguntar: `POST /api/discover/stream` devuelve eventos `step` (un nodo del DiscoverFlow cada uno) y un `answer` final. `discoverStream` los parsea en `api.ts`; si el flujo se corta sin `answer`, lanza 502.
5. Los candidatos se confirman o rechazan (`POST /discover/feedback`) o se escalan (`POST /curation/requests`).
6. El proxy construye la URL con `API_URL` leída en tiempo de ejecución, reenvía `content-type`, `cookie`, `authorization`, `accept` y `origin` (la API lo compara para rechazar con 403 un cambio de estado con cookie desde otro sitio), añade `X-Forwarded-Host` con el sitio que vio el navegador y, solo con `TRUST_FORWARDED_FOR=1`, la dirección del cliente (último valor de `X-Forwarded-For`). Si la primera ruta no está en la lista permitida, responde 404 con `detail`. Devuelve `content-type`, `cache-control` (por defecto `no-store`) y todos los `set-cookie`. Sin respuesta de la API, 502 con `detail`.
7. La barra lateral decide el menú: Preguntar, Catálogo y Mis solicitudes siempre; Curación si `isSteward`; Métricas y Administración si `isAdmin`. Las páginas restringidas redirigen a `/` si el rol no alcanza.

## Qué ve cada rol
| Rol | Menú | Extras |
|---|---|---|
| `consumer` | Preguntar, Catálogo, Mis solicitudes | Solo lo que su login SQL puede leer (lo filtra la API). |
| `steward` | + Curación | Botón "Historial" en la ficha. |
| `data_admin` | + Métricas, Administración | La API también le da `steward` (dominios `*`). Ve el contador de BDs y objetos en el chat. |

El rol `data_admin` no es "administrador de la web": lo da la API según el login (permiso de metadatos en el servidor o lista `CONVERDATA_ADMINS`). Detalle en [OP-03](../../specs/on-premise/OP-03-identidad.md) y [F14](../../specs/comun/F14-identity.md).

## Contratos y datos
- Endpoints que usa `api.ts` (todos existen en `api/converdata_api/main.py`): `/setup/status`, `/auth/me`, `/login`, `/auth/logout`, `/discover`, `/discover/stream`, `/discover/feedback`, `/me/history`, `/me/requests`, `/catalog/*`, `/assets/*`, `/curation/*`, `/admin/inventory`, `/admin/inventory/probe`, `/admin/inventory/connect`, `/admin/stewards`, `/admin/catalog/build`, `/admin/audit`, `/admin/metrics`, `/admin/manual`.
- La API tiene rutas que la web no llama: `/admin/sessions`, `/admin/audit/verify`, `/health` y `/mcp` (si está montado). El proxy no reenvía `/health` ni `/mcp`.
- Los errores se leen de `detail`: texto simple, o la lista de validación de Pydantic sin el prefijo `Value error, `.
- `types.ts` declara que `AnswerEnvelope` y `Discovery` reflejan `src/converdata/models/discovery.py`. El contrato se mantiene a mano; no se genera.
- Almacén local: clave `converdata:conversations:<user_id>`, máximo 50 conversaciones, cada una con sus mensajes y sobres de respuesta (`web/src/components/chat/conversations.tsx`).
- Spec de interfaz: [OP-04](../../specs/on-premise/OP-04-interfaces.md) y [F12](../../specs/comun/F12-interfaces.md). Arquitectura: [diagrama on-premise](../../architecture/onpremise-architecture.html).

## Configuración
| Dónde | Qué |
|---|---|
| `API_URL` (entorno de la web, en ejecución) | URL interna de la API. Por defecto `http://localhost:8000`; en `docker-compose.yml`, `http://api:8000`. |
| `CONVERDATA_PORT` | Puerto publicado de la web (por defecto 3000, en `docker-compose.yml`). |
| `NEXT_DIST_DIR` | Carpeta de compilación alterna, para no pisar `next dev` (`web/next.config.ts`). |
| `web/next.config.ts` | `output: "standalone"`, `poweredByHeader: false` y `headers()`: en todas las respuestas, CSP (con `frame-ancestors 'none'`), `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y, en producción, HSTS. |
| `TRUST_FORWARDED_FOR` (entorno de la web) | Apagada por defecto. Con `1` o `true`, el proxy reenvía a la API la dirección del cliente. Solo se activa detrás de un proxy inverso propio (IIS, ALB) que añada esa dirección al final de `X-Forwarded-For`; sin él, la cabecera la escribe el cliente. Se activa a la vez que `CONVERDATA_TRUST_PROXY` en la API (DT-02). |
| `CONVERDATA_CORS_ORIGINS`, `CONVERDATA_COOKIE_SECURE` | Son de la API. Con HTTPS delante hay que poner `CONVERDATA_COOKIE_SECURE=1`. Si delante de la web hay un proxy que cambia `Host`, el origen público debe estar en `CONVERDATA_CORS_ORIGINS`, o la API rechaza con 403 los cambios de estado. |

## Construcción y despliegue
- `web/package.json`: `dev`, `build`, `start`, `lint`. Next.js y React van con versión exacta (`15.5.29`, `19.1.0`); el resto con rangos, fijados por `web/package-lock.json`.
- `overrides`: `next` → `postcss 8.5.33`. Corrige una vulnerabilidad del `postcss` transitivo (ver [PLAN §3](../../PLAN-desarrollo.md)).
- `web/Dockerfile`: tres etapas sobre `node:22-alpine` fijada por digest. `npm ci` instala exactamente el bloqueo; `npm run build`; la imagen final copia `.next/standalone`, `.next/static` y `public`, corre como usuario `web` y ejecuta `node server.js` en el puerto 3000.
- `docker compose up --build` levanta `api` (sin puerto publicado) y `web` (`depends_on` el chequeo de salud de la API).
- En Windows Server (bloque F) todavía no hay despliegue: hoy solo `docker compose`.
- El plan ([PLAN §3](../../PLAN-desarrollo.md), cadena de suministro) anota que el 2026-11-17 no se construyó la imagen (Docker no estaba en marcha). Sin verificar la construcción de `web/Dockerfile` desde entonces.

## Pruebas que lo cubren
- CI, trabajo `web` de `.github/workflows/calidad.yml`: `npm ci`, `npx tsc --noEmit && npx eslint src --max-warnings=0`, `npm run build`.
- Cadena de suministro: `tests/test_supply_chain.py::test_la_web_fija_versiones_exactas_y_su_bloqueo_trae_integridad` y el trabajo `cadena-de-suministro` (`npm audit --omit=dev --audit-level=high`, SBOM).
- Contrato web-API: no hay prueba automática. Se revisa a mano (agente `.claude/agents/verificador-contrato-web-api.md`).
- Pruebas de interfaz, componentes o extremo a extremo: no existen. Sin verificar el comportamiento en navegador fuera de lo anotado en el plan (Responsables e Historial).

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md).
- La CSP usa `'unsafe-inline'` en scripts y estilos porque Next.js los inyecta en línea y no se usan nonces (DT-71).
- `TRUST_FORWARDED_FOR` y `CONVERDATA_TRUST_PROXY` están apagadas: hasta activarlas y probarlas detrás de IIS (bloque F), el bloqueo de login "por origen" ve la dirección del proxy (DT-02).
- Si la sesión caduca sin que el usuario pulse "Cerrar sesión", las conversaciones siguen en el `localStorage` hasta el siguiente cierre de sesión. Son preguntas en texto claro en el equipo del usuario.
- El rol decide qué se muestra, no qué se permite: si la API cambia un rol, la web lo sabe solo en la siguiente `GET /auth/me`.
- Los tipos de `types.ts` se escriben a mano y pueden desfasarse de la API.
- Sin pruebas de interfaz ni accesibilidad automatizadas.

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Añadir un endpoint al cliente | `web/src/lib/api.ts` y el tipo en `web/src/lib/types.ts`. |
| Cambiar el menú o qué rol ve qué | `web/src/components/app-sidebar.tsx` y el guardia de la página (`isAdmin`/`isSteward`). |
| Cambiar qué cabeceras viajan a la API | `FORWARD_REQUEST`, `ALLOWED` y el bloque `out` en `web/src/app/api/[...path]/route.ts`. |
| Cambiar cómo se muestra una respuesta | `web/src/components/chat/assistant-message.tsx` y `candidate-card.tsx`. |
| Cambiar el almacén de conversaciones | `web/src/components/chat/conversations.tsx`. |
| Mostrar otro documento Markdown | `web/src/components/markdown.tsx` (acepta solo la sintaxis mínima). |
| Cambiar el puerto o la URL de la API | `docker-compose.yml` (`API_URL`, `CONVERDATA_PORT`). |
| Actualizar dependencias | `web/package.json`, `web/package-lock.json` y volver a correr la CI (`npm audit`). |
