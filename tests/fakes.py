"""Dobles de prueba compartidos para los adaptadores de SQL Server (contrato de pyodbc: connect → cursor → execute)."""

from __future__ import annotations

import re


class FakeCursor:
    def __init__(self, db: "FakeDb"):
        self.db = db
        self.description = None
        self._rows: list = []

    def execute(self, sql, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        self.db.statements.append((sql, params))
        if self.db.fail_on and re.search(self.db.fail_on, sql):
            raise RuntimeError("fallo simulado de SQL Server")
        self._rows = []
        for pattern, rows in self.db.results.items():
            if re.search(pattern, sql):
                self._rows = list(rows(params) if callable(rows) else rows)
                break
        self.description = ("x",) if self._rows else None
        return self

    def executemany(self, sql, seq):
        for params in seq:
            self.execute(sql, *params)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def nextset(self):
        return False


class FakeConnection:
    def __init__(self, db: "FakeDb"):
        self.db = db
        self.autocommit = True

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        self.db.commits += 1

    def rollback(self):
        self.db.rollbacks += 1

    def close(self):
        self.db.closed += 1


class FakeDb:
    """`connect()` devuelve una conexión nueva; todas registran en el mismo log."""

    def __init__(self, fail_on: str | None = None, results: dict | None = None):
        self.statements: list[tuple[str, tuple]] = []
        self.commits = self.rollbacks = self.closed = 0
        self.fail_on = fail_on
        self.results = results or {}

    def connect(self):
        return FakeConnection(self)

    def inserts_into(self, table: str) -> list[tuple]:
        return [p for s, p in self.statements if re.search(rf"INSERT\s+INTO\s+{re.escape(table)}\b", s, re.I)]

    def text(self) -> str:
        return "\n".join(f"{s} {p}" for s, p in self.statements)
