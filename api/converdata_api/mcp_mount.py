"""`converdata-mcp` (F12, HU-16) montado en `/mcp` de ConverData-API.

Usa las mismas sesiones que la web: el `Bearer` es el token de `/login` (SessionVault) y la identidad de cada herramienta sale
de ese token con `runtime.user_context`, es decir, con `visible_ids` calculado con el login del propio usuario (F14, OP-03).
Si el paquete `mcp` no está instalado (extra `mcp`/`api`), la API arranca sin `/mcp`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from converdata_api.runtime import AgentRuntime
from converdata_api.settings import ApiSettings
from converdata_api.vault import SessionVault

MCP_PATH = "/mcp"


def build_mcp_mount(runtime: AgentRuntime, vault: SessionVault, settings: ApiSettings):
    """(app ASGI para `app.mount("/")`, `lifespan` del gestor de sesiones MCP), o None si no hay SDK de MCP."""
    try:
        from converdata.integration.mcp.server import bearer_token, build_mcp_server, require_bearer
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError:
        return None
    from converdata.application.discovery import DiscoveryTools

    cached: dict = {}

    def tools() -> DiscoveryTools | None:
        service = runtime.service  # se reemplaza tras cada build del catálogo
        if service is None:
            return None
        if cached.get("service") is not service:
            cached["service"], cached["tools"] = service, DiscoveryTools(service)
        return cached["tools"]

    def identify(request):
        session = vault.get(bearer_token(request))
        return runtime.user_context(session) if session is not None else None

    security = (TransportSecuritySettings(allowed_hosts=settings.mcp_allowed_hosts,
                                          allowed_origins=settings.mcp_allowed_origins)
                if settings.mcp_allowed_hosts else None)
    mcp_app = build_mcp_server(tools, identify).streamable_http_app(
        streamable_http_path=MCP_PATH, stateless_http=True, transport_security=security)  # SSE: con json_response=True las respuestas llegan truncadas bajo uvicorn (mcp 2.3.0)
    guarded = require_bearer(mcp_app, lambda token: vault.get(token) is not None)

    async def asgi(scope, receive, send):
        # Montado en "/" para servir `/mcp` sin redirección; lo demás que no sea una ruta de la API es 404.
        if scope["type"] == "http" and (scope["path"] == MCP_PATH or scope["path"].startswith(MCP_PATH + "/")):
            await guarded(scope, receive, send)
        elif scope["type"] == "http":
            await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"detail":"Not Found"}'})
        elif scope["type"] == "lifespan":
            await mcp_app(scope, receive, send)

    @asynccontextmanager
    async def lifespan():
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    return asgi, lifespan
