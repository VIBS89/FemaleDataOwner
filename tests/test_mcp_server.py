"""Capa de integración: `converdata-mcp` (F12, OP-03, OP-04) probado con el cliente MCP oficial.

Por HTTP, contra la app ASGI en memoria (sin puertos): sin `Bearer` válido → 401; la identidad sale del token, nunca de
los argumentos; no se publican herramientas internas. En proceso (como stdio), con la identidad fija de desarrollo.
"""

from contextlib import asynccontextmanager

import pytest

pytest.importorskip("mcp")

import httpx2  # noqa: E402  (cliente HTTP del SDK de MCP)
from mcp import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from converdata.application.discovery import DiscoveryTools  # noqa: E402
from converdata.integration.mcp.server import bearer_token, build_mcp_server, require_bearer  # noqa: E402
from conftest import ONBOARDING_Q  # noqa: E402

CLIENT_CODE = "VBank_ING.dbo.Users.ClientCode"
EXPECTED_TOOLS = {"discover", "get_asset", "get_related", "find_alternatives", "list_business_rules", "get_lineage",
                  "search_catalog", "where_is", "find_join_path", "estate_overview"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def sessions(analyst, rrhh_user):
    return {"tok-analista": analyst, "tok-rrhh": rrhh_user}


@pytest.fixture
def server(service, sessions):
    tools = DiscoveryTools(service)
    return build_mcp_server(lambda: tools, lambda request: sessions.get(bearer_token(request)))


@asynccontextmanager
async def http_client(server, sessions, token: str | None):
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    guarded = require_bearer(app, lambda t: t in sessions)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=guarded), base_url="http://127.0.0.1:8000",
                                      headers=headers) as http:
            async with Client(streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)) as client:
                yield client


def structured(result) -> dict:
    assert not result.is_error, result.content
    return result.structured_content


# --- HTTP con Bearer ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_http_sin_token_responde_401(server, sessions):
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    guarded = require_bearer(app, lambda t: t in sessions)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=guarded), base_url="http://127.0.0.1:8000") as http:
        for headers in ({}, {"Authorization": "Bearer caducado"}, {"Authorization": "Basic abc"}):
            response = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)
            assert response.status_code == 401


@pytest.mark.anyio
async def test_http_publica_solo_herramientas_de_lectura(server, sessions):
    async with http_client(server, sessions, "tok-analista") as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS  # sin record_discovery_feedback ni curation_* (F12)
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    for t in tools:  # ninguna herramienta acepta identidad como argumento (OP-03)
        assert not {"user_id", "session_id", "user", "login", "password"} & set(t.input_schema.get("properties", {}))


@pytest.mark.anyio
async def test_http_discover_con_la_identidad_del_token(server, sessions):
    async with http_client(server, sessions, "tok-analista") as client:
        env = structured(await client.call_tool("discover", {"question": ONBOARDING_Q}))
    assert env["flow"] == "discover" and env["status"] == "ok"
    assert env["discovery"]["candidates"][0]["asset_key"] == CLIENT_CODE


@pytest.mark.anyio
async def test_http_argumentos_no_cambian_la_identidad(server, sessions):
    """OP-03 CA5: el usuario de RRHH no obtiene lo del analista aunque meta otra identidad en los argumentos."""
    async with http_client(server, sessions, "tok-rrhh") as client:
        result = await client.call_tool("get_asset", {"asset_key": CLIENT_CODE, "user_id": "analista",
                                                      "session_id": "tok-analista"})
    if not result.is_error:  # el esquema puede rechazar los argumentos extra; si los acepta, los ignora
        assert result.structured_content == {"found": False}


@pytest.mark.anyio
async def test_http_activo_no_visible_responde_como_inexistente(server, sessions):
    async with http_client(server, sessions, "tok-rrhh") as client:
        hidden = structured(await client.call_tool("get_asset", {"asset_key": CLIENT_CODE}))
        missing = structured(await client.call_tool("get_asset", {"asset_key": "NoExiste.dbo.T"}))
    assert hidden == missing == {"found": False}


@pytest.mark.anyio
async def test_http_sesion_revocada_entre_llamadas(server, sessions):
    """Tras /logout el mismo token deja de servir aunque la conexión MCP siga abierta (F14 CA4)."""
    async with http_client(server, sessions, "tok-analista") as client:
        structured(await client.call_tool("estate_overview", {}))
        del sessions["tok-analista"]
        with pytest.raises(Exception):
            await client.call_tool("estate_overview", {})


# --- en proceso (stdio) ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_en_proceso_usa_la_identidad_fija_y_devuelve_estructurado(service, analyst):
    tools = DiscoveryTools(service)
    server = build_mcp_server(lambda: tools, lambda request: analyst if request is None else None)
    async with Client(server) as client:
        card = structured(await client.call_tool("get_asset", {"asset_key": CLIENT_CODE}))
        path = structured(await client.call_tool("find_join_path", {"source": "Onboarding.dbo.Solicitud",
                                                                     "target": "DWH.dim.Cliente"}))
    assert card["found"] and card["asset"]["schema"] == "dbo" and card["asset"]["column"] == "ClientCode"
    assert path["found"] and path["path"]["tables"][-1] == "DWH.dim.Cliente"


@pytest.mark.anyio
async def test_sin_identidad_la_herramienta_falla_sin_datos(service):
    server = build_mcp_server(lambda: DiscoveryTools(service), lambda request: None)
    async with Client(server) as client:
        result = await client.call_tool("estate_overview", {})
    assert result.is_error and "Sesión no válida" in result.content[0].text


@pytest.mark.anyio
async def test_sin_catalogo_cargado_lo_dice(analyst):
    server = build_mcp_server(lambda: None, lambda request: analyst)
    async with Client(server) as client:
        result = await client.call_tool("estate_overview", {})
    assert result.is_error and "catálogo" in result.content[0].text
