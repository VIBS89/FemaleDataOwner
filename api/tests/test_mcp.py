"""`/mcp` de ConverData-API (HU-16, OP-04 CA2/CA3, OP-03 CA5) de punta a punta con el servidor simulado.

El `Bearer` es el token de `/login`; la identidad de cada herramienta sale de él y hereda los permisos del login (F14).
"""

from contextlib import asynccontextmanager

import pytest

pytest.importorskip("mcp")

import httpx2  # noqa: E402  (cliente HTTP del SDK de MCP)
from fastapi.testclient import TestClient  # noqa: E402
from mcp import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from test_api import login, ready, settings  # noqa: E402,F401  (fixtures y ayudantes de la API)

BASE = "http://127.0.0.1:8000"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def token_of(app, user: str) -> str:
    client = TestClient(app)
    login(client, user=user)
    return client.cookies.get("cd_session")


@pytest.fixture
async def live(ready):
    """La API con el ciclo de vida iniciado (el gestor de sesiones de /mcp solo arranca una vez por app)."""
    async with ready.app.router.lifespan_context(ready.app):
        yield ready


@asynccontextmanager
async def mcp_client(app, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers) as http:
        async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http)) as client:
            yield client


def structured(result) -> dict:
    assert not result.is_error, result.content
    return result.structured_content


@pytest.mark.anyio
async def test_mcp_sin_bearer_o_con_token_invalido_responde_401(live):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=live.app), base_url=BASE) as http:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        for headers in ({}, {"Authorization": "Bearer caducado"}, {"Authorization": "Basic abc"}):
            assert (await http.post("/mcp", json=body, headers=headers)).status_code == 401


@pytest.mark.anyio
async def test_mcp_discover_devuelve_answer_envelope_con_el_bearer_de_login(live):
    token = token_of(live.app, "analista")
    async with mcp_client(live.app, token) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"discover", "get_asset"} <= names
        assert not {"record_discovery_feedback", "curation_answer"} & names  # solo herramientas externas (F12)
        envelope = structured(await client.call_tool("discover", {"question": "¿Dónde está el saldo del préstamo?"}))
    assert envelope["flow"] == "discover" and envelope["discovery"] is not None
    # la pregunta quedó auditada con el cliente `mcp` (F11)
    rows = live.get("/admin/audit", params={"kind": "question"}).json()["items"]
    assert any(r.get("user_id") == "analista" and r.get("client") == "mcp" for r in rows)


@pytest.mark.anyio
async def test_mcp_hereda_los_permisos_del_login_y_ignora_identidad_en_argumentos(live):
    hidden = live.get("/catalog/objects", params={"database": "BancaLeasing"}).json()["items"][0]["asset_key"]
    analyst = token_of(live.app, "analista")
    async with mcp_client(live.app, analyst) as client:
        # un activo que el analista no ve responde igual que uno que no existe (F14)
        assert structured(await client.call_tool("get_asset", {"asset_key": hidden})) == {"found": False}
        # un argumento extra con otra identidad no cambia quién pregunta
        try:
            result = await client.call_tool("get_asset", {"asset_key": hidden, "user_id": "demo"})
        except Exception:  # el SDK puede rechazar argumentos no declarados
            pass
        else:
            assert result.is_error or result.structured_content == {"found": False}
    admin = token_of(live.app, "demo")
    async with mcp_client(live.app, admin) as client:
        assert structured(await client.call_tool("get_asset", {"asset_key": hidden}))["found"] is True


@pytest.mark.anyio
async def test_mcp_deja_de_funcionar_al_cerrar_sesion(live):
    client = TestClient(live.app)
    login(client, user="analista")
    token = client.cookies.get("cd_session")
    assert client.post("/auth/logout").status_code == 200
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=live.app), base_url=BASE) as http:
        r = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_rutas_desconocidas_siguen_dando_404(ready):
    assert ready.get("/no-existe").status_code == 404
    assert ready.get("/health").status_code == 200
