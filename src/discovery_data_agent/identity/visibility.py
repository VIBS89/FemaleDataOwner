"""Qué puede leer un login en un servidor (F14 §Flujo, paso 3): la consulta de F14 detrás del puerto `ObjectLister`.

Con el resultado, DiscoveryDataAgent-API arma y cachea los `visible_ids` de cada sesión (`AgentRuntime.visible_ids`): 15 minutos,
solo los servidores donde el login se validó y, si un servidor no responde, nada de ese servidor (fail-closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol


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
        """Primero pregunta, desde `master`, a qué bases entra el login; solo abre esas. Abrir una base sin acceso
        hace fallar la conexión, y ese fallo no debe ocultar las demás bases del servidor. Si el servidor no
        responde, falla la primera conexión y quien llama no ve nada de él (fail-closed)."""
        conn = self._connect(server_id, "master")
        try:
            cur = conn.cursor()
            accessible = []
            for db in databases:
                cur.execute("SELECT HAS_DBACCESS(?)", db)
                if cur.fetchone()[0] == 1:
                    accessible.append(db)
        finally:
            conn.close()
        for db in accessible:
            try:
                conn = self._connect(server_id, db)
            except Exception:  # la base dejó de estar disponible entre las dos consultas: se omite solo esa base
                continue
            try:
                cur = conn.cursor()
                cur.execute(VISIBILITY_SQL)
                for schema, name, _type in cur.fetchall():
                    yield VisibleObject(db, schema, name)
            finally:
                conn.close()
