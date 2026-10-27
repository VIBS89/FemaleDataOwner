"""`converdata mcp serve` (stdio): Claude Desktop o Claude Code sobre un catálogo local con identidad de desarrollo.

La identidad fija no viene de un login SQL, así que solo se permite fuera de qa y prod (F14, F17).
"""

import os
import sys

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from converdata.integration.mcp.stdio import DevIdentityNotAllowed, build_stdio_server  # noqa: E402
from conftest import FIXTURE  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("env", ["qa", "prod", "QA"])
def test_identidad_de_desarrollo_bloqueada_en_qa_y_prod(monkeypatch, env):
    monkeypatch.setenv("CONVERDATA_ENV", env)
    with pytest.raises(DevIdentityNotAllowed, match="/mcp"):
        build_stdio_server(FIXTURE)


@pytest.mark.anyio
async def test_stdio_respeta_las_bds_indicadas(monkeypatch):
    monkeypatch.setenv("CONVERDATA_ENV", "local")
    server = build_stdio_server(FIXTURE, databases=["RRHH"], user="dev")
    async with Client(server) as client:
        result = await client.call_tool("get_asset", {"asset_key": "VBank_ING.dbo.Users.ClientCode"})
        overview = await client.call_tool("estate_overview", {})
    assert result.structured_content == {"found": False}
    assert [d["database"] for d in overview.structured_content["databases"]] == ["RRHH"]


@pytest.mark.anyio
async def test_stdio_sin_bds_ve_todo_el_catalogo_local(monkeypatch):
    monkeypatch.delenv("CONVERDATA_ENV", raising=False)
    server = build_stdio_server(FIXTURE)
    async with Client(server) as client:
        overview = (await client.call_tool("estate_overview", {})).structured_content
    assert {"VBank_ING", "Onboarding", "DWH", "RRHH"} <= {d["database"] for d in overview["databases"]}


@pytest.mark.anyio
async def test_cli_mcp_serve_como_proceso_stdio(monkeypatch):
    """Lo mismo que hace Claude Desktop o Claude Code: lanzar `converdata mcp serve` y hablar por stdin/stdout."""
    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "converdata.cli", "mcp", "serve", "--root", str(FIXTURE)],
        env={**os.environ, "CONVERDATA_ENV": "local", "PYTHONPATH": str(FIXTURE.parents[2] / "src")},
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        env = (await client.call_tool("discover", {"question": "¿dónde está el DUI del cliente?"})).structured_content
    assert "discover" in names and env["flow"] == "discover"
