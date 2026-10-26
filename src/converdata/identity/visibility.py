"""Cálculo de `visible_ids` con el login del propio usuario en cada servidor (F14 §Flujo, paso 3).

La consulta es la de F14; aquí solo se mapea el resultado a ids físicos del catálogo. El acceso a SQL Server queda detrás
de `ObjectLister` para que la lógica sea determinista y probable sin un servidor real.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from converdata.catalog.ids import physical_id
from converdata.config import Inventory

# F14: objetos legibles (U, V) o ejecutables (P) por el login, en cada BD configurada con HAS_DBACCESS = 1.
VISIBILITY_SQL = """
SELECT s.name AS [schema], o.name, o.type
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('U','V','P')
  AND HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name), 'OBJECT',
      CASE o.type WHEN 'P' THEN 'EXECUTE' ELSE 'SELECT' END) = 1;
"""


@dataclass(frozen=True)
class VisibleObject:
    database: str
    schema: str
    name: str


class ObjectLister(Protocol):
    """Lista lo que un login puede leer en un servidor. La implementación real abre la conexión del usuario."""

    def visible_objects(self, server_id: str, databases: list[str]) -> Iterable[VisibleObject]: ...


class PyodbcObjectLister:
    """Implementación on-premise: usa `ConnectionFactory.for_session` (OP-03) con la credencial del usuario."""

    def __init__(self, connect: Callable[[str, str], object]):
        self._connect = connect  # (server_id, database) -> conexión pyodbc abierta con el login del usuario

    def visible_objects(self, server_id: str, databases: list[str]) -> Iterable[VisibleObject]:
        for db in databases:
            conn = self._connect(server_id, db)
            try:
                cur = conn.cursor()
                cur.execute("SELECT HAS_DBACCESS(?)", db)
                if cur.fetchone()[0] != 1:
                    continue
                cur.execute(VISIBILITY_SQL)
                for schema, name, _type in cur.fetchall():
                    yield VisibleObject(db, schema, name)
            finally:
                conn.close()


class VisibilityResolver:
    """Calcula y cachea (15 min por sesión, F14) los `visible_ids` de un usuario."""

    def __init__(self, inventory: Inventory, ttl_seconds: int = 900, clock: Callable[[], float] = time.monotonic):
        self.inventory = inventory
        self.ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, frozenset[str]]] = {}

    def resolve(self, session_id: str, lister: ObjectLister, servers: list[str]) -> frozenset[str]:
        cached = self._cache.get(session_id)
        if cached and self._clock() - cached[0] < self.ttl:
            return cached[1]
        ids: set[str] = set()
        for server_id in servers:  # solo los servidores donde el login se validó (F14, paso 1)
            server = self.inventory.server(server_id)
            if server is None:
                continue
            for obj in lister.visible_objects(server.id, server.databases):
                ids.add(physical_id(server.environment, server.id, obj.database, obj.schema, obj.name))
        result = frozenset(ids)
        self._cache[session_id] = (self._clock(), result)
        return result

    def invalidate(self, session_id: str) -> None:
        self._cache.pop(session_id, None)
