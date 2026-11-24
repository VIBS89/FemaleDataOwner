"""Ejecutor del AskFlow (F8): corre la consulta ya validada con la credencial de la sesión del usuario.

- Conexión de solo lectura (`readonly=True`), `LOCK_TIMEOUT` y timeout de consulta: no bloquea el servidor.
- Lee como máximo `max_rows + 1` filas para marcar truncado.
- Los errores de SQL Server se traducen a mensajes sin host ni login; un permiso denegado no se reintenta.
"""

from __future__ import annotations

from converdata.ask.ports import QueryRejected, QueryResult
from converdata.config import Inventory

from converdata_api.connector import LoginFailed
from converdata_api.vault import Session, SessionVault

QUERY_TIMEOUT_S = 60
LOCK_TIMEOUT_MS = 5000


class SessionQueryExecutor:
    def __init__(self, connector, inventory: Inventory, vault: SessionVault, session: Session):
        self._connector, self._inventory, self._vault, self._session = connector, inventory, vault, session

    def server_label(self, server: str) -> str:
        return self._inventory.alias(server)

    def run(self, server: str, database: str, sql: str, max_rows: int) -> QueryResult:
        import pyodbc

        config = self._inventory.server(server)
        cred = self._vault.credential(self._session, server)
        if config is None or cred is None:
            raise QueryRejected("Tu sesión no tiene acceso a ese servidor.", retry=False)
        try:
            conn = self._connector.connect(config, cred, database)
        except LoginFailed as exc:
            raise QueryRejected(str(exc), retry=False) from None
        except pyodbc.Error:
            raise QueryRejected("No se pudo conectar al servidor para calcular el dato.", retry=False) from None
        try:
            conn.timeout = QUERY_TIMEOUT_S
            cursor = conn.cursor()
            cursor.execute(f"SET NOCOUNT ON; SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS};")
            cursor.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            rows = [list(r) for r in cursor.fetchmany(max_rows + 1)]
        except pyodbc.Error as exc:
            text = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
            if "(229)" in text or "(230)" in text:
                raise QueryRejected("No tienes permiso para leer esa información.", retry=False) from None
            # El mensaje de SQL Server (columna inválida, conversión…) vuelve al planner para que corrija.
            raise QueryRejected(text.split("[SQL Server]")[-1][:400]) from None
        finally:
            conn.close()
        return QueryResult(columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows)
