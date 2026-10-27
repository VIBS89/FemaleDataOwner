"""Prueba de humo de converdata-mcp con el cliente oficial de MCP contra `converdata mcp serve` (stdio), como lo usa Claude Desktop/Code.

    .venv/Scripts/python scripts/mcp_stdio_probe.py [raíz del catálogo]      (por defecto tests/fixtures/vbank)
"""

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital."
ASSET = "VBank_ING.dbo.Users.ClientCode"


async def main(catalog: str) -> None:
    params = StdioServerParameters(
        command=sys.executable, cwd=str(ROOT),
        args=["-m", "converdata.cli", "mcp", "serve", "--root", catalog, "--user", "analista", "--embeddings-only"])
    async with Client(params) as client:
        print("herramientas:", sorted(t.name for t in (await client.list_tools()).tools))
        envelope = (await client.call_tool("discover", {"question": QUESTION})).structured_content
        top = envelope["discovery"]["candidates"][0]
        print(f"discover: flow={envelope['flow']} {top['asset_key']} {top['confidence']:.0%}")
        asset = (await client.call_tool("get_asset", {"asset_key": ASSET})).structured_content
        print("get_asset:", asset["found"], asset["asset"]["description"])
        rules = (await client.call_tool("list_business_rules", {"asset_key": ASSET})).structured_content["rules"]
        print("reglas:", [r["id"] for r in rules])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/vbank"))
