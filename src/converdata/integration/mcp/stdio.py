"""`converdata mcp serve`: `converdata-mcp` por stdio para Claude Desktop o Claude Code en la máquina del desarrollador.

Raíz de composición del modo local: carga el DiscoverFlow sobre un catálogo en disco y fija una identidad de desarrollo
(como `converdata discover`). Esa identidad no sale de un login SQL, así que se niega en qa y prod: allí Claude se
conecta al `/mcp` de `ConverData-API` con el `Bearer` de `/login` (OP-03, OP-04).
"""

from __future__ import annotations

import os
from pathlib import Path

from converdata.application.discovery import DiscoveryTools
from converdata.bootstrap import build_service, user_with_databases
from converdata.integration.mcp.server import build_mcp_server
from converdata.llm.factory import ENV_VAR

BLOCKED_ENVIRONMENTS = {"qa", "prod"}


class DevIdentityNotAllowed(RuntimeError):
    pass


def build_stdio_server(
    root: str | Path, *, models_path: str | Path | None = None, databases: list[str] | None = None,
    user: str = "dev", groups: list[str] | None = None, embeddings_only: bool = False,
):
    env = os.environ.get(ENV_VAR, "local").strip().lower()
    if env in BLOCKED_ENVIRONMENTS:
        raise DevIdentityNotAllowed(
            f"{ENV_VAR}={env}: la identidad de desarrollo por stdio no se permite aquí; "
            "conecta Claude al /mcp de ConverData-API con el Bearer de /login."
        )
    service = build_service(root, models_path=models_path, llm_nodes=not embeddings_only)
    identity = user_with_databases(service, user, databases, groups)
    tools = DiscoveryTools(service)
    # Sin petición HTTP (stdio) → identidad fija; cualquier otra cosa se rechaza.
    return build_mcp_server(lambda: tools, lambda request: identity if request is None else None)


def serve(args) -> int:
    server = build_stdio_server(
        args.root, models_path=args.models, user=args.user,
        databases=args.databases.split(",") if args.databases else None,
        groups=[g for g in args.groups.split(",") if g], embeddings_only=args.embeddings_only,
    )
    server.run("stdio")
    return 0
