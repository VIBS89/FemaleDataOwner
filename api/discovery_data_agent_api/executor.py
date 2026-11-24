"""Ejecutor del AskFlow con SQL de un LLM (fase 1b, `ask_llm_sql`): corre la consulta ya validada (F7) con la
credencial de la sesión, a través de los mismos controles que las cifras de plantilla (`runtime.figure_executor`):
servidor autorizado en el inventario, tope diario por usuario, concurrencia acotada, auditoría antes de ejecutar
(fail-closed), solo lectura con tiempo límite y transacción que siempre se revierte.

Los errores de SQL Server se traducen a mensajes sin host ni login; un permiso denegado no se reintenta.
"""

from __future__ import annotations

from typing import Callable

from discovery_data_agent.ask.ports import QueryRejected, QueryResult
from discovery_data_agent.config import Inventory

# (servidor, base, sql, filas máximas, ¿sondeo?) → (columnas, filas). Lo implementa `AgentRuntime._run_ask`.
GuardedRun = Callable[[str, str, str, int, bool], tuple[list[str], list[list]]]


class SessionQueryExecutor:
    def __init__(self, inventory: Inventory, run: GuardedRun):
        self._inventory, self._run = inventory, run

    def server_label(self, server: str) -> str:
        return self._inventory.alias(server)

    def run(self, server: str, database: str, sql: str, max_rows: int, probe: bool = False) -> QueryResult:
        import pyodbc

        try:
            columns, rows = self._run(server, database, sql, max_rows + 1, probe)
        except PermissionError as exc:
            raise QueryRejected(str(exc), retry=False) from None
        except TimeoutError:
            raise QueryRejected("El servidor está ocupado; intenta de nuevo en un momento.", retry=False) from None
        except pyodbc.Error as exc:
            text = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
            if "(229)" in text or "(230)" in text:
                raise QueryRejected("No tienes permiso para leer esa información.", retry=False) from None
            if exc.args and exc.args[0] in ("HYT00", "HYT01"):
                raise QueryRejected("La consulta tardó demasiado; prueba con un periodo más corto.", retry=False) from None
            # El mensaje de SQL Server (columna inválida, conversión…) vuelve al planner para que corrija.
            raise QueryRejected(text.split("[SQL Server]")[-1][:400]) from None
        return QueryResult(columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows)
