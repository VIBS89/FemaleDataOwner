"""`converdata-mcp` (F12, OP-04): publica las herramientas de descubrimiento para Claude y otros agentes.

Dos transportes con el mismo código:
- **HTTP** (`streamable_http_app`), montado en `/mcp` de `ConverData-API`: la identidad sale del `Authorization: Bearer`
  obtenido con `/login` (OP-03). `require_bearer` rechaza con 401 cualquier petición sin sesión válida.
- **stdio** (`converdata mcp serve`), para Claude Desktop o Claude Code en la máquina del desarrollador: identidad fija
  de desarrollo sobre un catálogo local (ver `converdata.integration.mcp.stdio`).

Solo se publican herramientas de lectura. Las internas de F12 (`record_discovery_feedback`, `curation_*`) no se
exponen a clientes externos. Ninguna herramienta acepta identidad como argumento: el LLM no puede suplantar a otro usuario.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, Callable, ContextManager

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from converdata.models.identity import UserContext
from converdata.application.discovery import DiscoveryTools

# (petición HTTP de Starlette o None en stdio) → usuario autenticado, o None si no hay sesión válida.
Identify = Callable[[Any | None], UserContext | None]
ToolsProvider = Callable[[], DiscoveryTools | None]

# (usuario, herramienta) → contexto que envuelve la llamada: límites de ritmo y de tokens, atribución del consumo.
# Lanza `ToolDenied` para rechazarla con un mensaje apto para el usuario.
Guard = Callable[[UserContext, str], ContextManager]
MAX_QUESTION = 2000
MAX_ARGUMENT = 400


class ToolDenied(Exception):
    pass


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

INSTRUCTIONS = (
    "ConverData responde dónde está un dato en los SQL Server del banco, qué significa, qué reglas aplican, con qué se "
    "relaciona y cuánta confianza merece. Usa `discover` para preguntas en lenguaje natural ('¿dónde está el DUI del "
    "cliente?') y las demás herramientas para profundizar en un activo (`asset_key` = BD.esquema.tabla[.columna]). "
    "Solo devuelve metadatos que el usuario autenticado puede ver; nunca valores de datos."
)


def bearer_token(request: Any | None) -> str | None:
    if request is None:
        return None
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def build_mcp_server(tools: ToolsProvider, identify: Identify, *, name: str = "converdata",
                     guard: Guard | None = None) -> MCPServer:
    server = MCPServer(name=name, title="ConverData — descubrimiento de datos", instructions=INSTRUCTIONS)

    @contextlib.contextmanager
    def call(ctx: Context, tool: str, *texts: str, limit: int = MAX_ARGUMENT):
        """Identidad, tamaño de los argumentos y la guarda de quien monta el servidor (los mismos topes que la web)."""
        if any(len(t) > limit for t in texts):
            raise ToolError(f"Argumento demasiado largo (máximo {limit} caracteres).")
        t, user = resolve(ctx)
        if guard is None:
            yield t, user
            return
        try:
            with guard(user, tool):
                yield t, user
        except ToolDenied as exc:
            raise ToolError(str(exc)) from None

    def resolve(ctx: Context) -> tuple[DiscoveryTools, UserContext]:
        try:
            request = ctx.request_context.request
        except ValueError:
            request = None
        user = identify(request)
        if user is None:
            raise ToolError("Sesión no válida o expirada: inicia sesión de nuevo en ConverData.")
        current = tools()
        if current is None:
            raise ToolError("El catálogo todavía no está disponible.")
        return current, user

    def dump(model) -> dict:
        return json.loads(model.model_dump_json(by_alias=True))

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def discover(question: str, ctx: Context) -> dict[str, Any]:
        """Busca dónde está un dato a partir de una pregunta en lenguaje natural.

        Devuelve el AnswerEnvelope (flow=discover): candidatos con BD, esquema, tabla, columna, ambiente y servidor,
        descripción y su fuente, reglas de negocio, relaciones, responsables y confianza, más alternativas y si hay una
        brecha de conocimiento. Cada llamada queda auditada.
        """
        with call(ctx, "discover", question, limit=MAX_QUESTION) as (t, user):
            return dump(t.discover(user, question, client="mcp"))

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_asset(asset_key: str, ctx: Context) -> dict[str, Any]:
        """Ficha de un activo (`BD.esquema.tabla` o `BD.esquema.tabla.columna`): ubicaciones, descripción, columnas,
        reglas, responsables, linaje y copias en otras BDs. Si no existe o no tienes acceso, `found` es false."""
        with call(ctx, "get_asset", asset_key) as (t, user):
            card = t.get_asset(user, asset_key)
        return {"found": False} if card is None else {"found": True, "asset": dump(card)}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_related(asset_key: str, ctx: Context) -> dict[str, Any]:
        """Relaciones a un salto de la tabla del activo: FKs, linaje ETL y la misma entidad en otras BDs."""
        with call(ctx, "get_related", asset_key) as (t, user):
            return {"related": [dump(r) for r in t.get_related(user, asset_key)]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def find_alternatives(asset_key: str, ctx: Context) -> dict[str, Any]:
        """Columnas con la misma semántica que una columna dada (sinónimo compartido o mismo nombre normalizado)."""
        with call(ctx, "find_alternatives", asset_key) as (t, user):
            return {"alternatives": [dump(a) for a in t.find_alternatives(user, asset_key)]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def list_business_rules(asset_key: str, ctx: Context) -> dict[str, Any]:
        """Reglas de negocio conocidas de un activo, con su estado de revisión."""
        with call(ctx, "list_business_rules", asset_key) as (t, user):
            return {"rules": [dump(r) for r in t.list_business_rules(user, asset_key)]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_lineage(asset_key: str, ctx: Context) -> dict[str, Any]:
        """Linaje ETL a un salto de la tabla del activo: paquete SSIS, job de SQL Agent, SP o vista que la carga o lee."""
        with call(ctx, "get_lineage", asset_key) as (t, user):
            return {"lineage": [dump(e) for e in t.get_lineage(user, asset_key)]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def search_catalog(query: str, ctx: Context, k: int = 10) -> dict[str, Any]:
        """Búsqueda directa (léxica y semántica) de tablas y columnas por nombre, descripción o sinónimo. Más rápida
        que `discover`, sin ranking por confianza ni narrativa."""
        with call(ctx, "search_catalog", query) as (t, user):
            return {"hits": [dump(h) for h in t.search_catalog(user, query, k=k)]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def where_is(entity: str, ctx: Context) -> dict[str, Any]:
        """Dónde vive una entidad de negocio (p. ej. 'cliente') entre las BDs: tablas y copia canónica."""
        with call(ctx, "where_is", entity) as (t, user):
            return {"entities": [dump(e) for e in t.where_is(user, entity)]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def find_join_path(source: str, target: str, ctx: Context, max_hops: int = 3) -> dict[str, Any]:
        """Camino de unión más corto entre dos tablas (`BD.esquema.tabla`): FKs, misma entidad o linaje."""
        with call(ctx, "find_join_path", source, target) as (t, user):
            path = t.find_join_path(user, source, target, max_hops=max_hops)
        return {"found": False} if path is None else {"found": True, "path": dump(path)}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def estate_overview(ctx: Context) -> dict[str, Any]:
        """Resumen de lo que puedes ver: BDs con sus ambientes y número de tablas, vistas y SPs, y entidades de negocio."""
        with call(ctx, "estate_overview") as (t, user):
            return dump(t.estate_overview(user))

    return server


def require_bearer(app, is_valid: Callable[[str], bool]):
    """ASGI: 401 para cualquier petición HTTP a `/mcp` sin un `Bearer` de una sesión vigente (OP-04 CA2)."""

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            scheme, _, token = headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not token.strip() or not is_valid(token.strip()):
                body = json.dumps({"detail": "No autenticado"}).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": body})
                return
        await app(scope, receive, send)

    return guarded
