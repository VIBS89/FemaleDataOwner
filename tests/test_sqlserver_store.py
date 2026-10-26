"""`SqlServerVectorStore` sin instancia real: condición Full-Text y parámetros (el contrato completo requiere SQL Server 2025)."""

import json

from converdata.memory.sqlserver_store import SqlServerVectorStore, fulltext_condition


def test_condicion_fulltext_usa_los_mismos_stems():
    cond = fulltext_condition("identificador único del cliente; DROP TABLE x--")
    # Solo términos alfanuméricos entre comillas: el texto del usuario no puede inyectar operadores Full-Text.
    assert cond == '"client*" OR "drop*" OR "identi*" OR "table*" OR "unico*"'


class FakeCursor:
    def __init__(self, log):
        self.log, self.description = log, ("x",)

    def execute(self, sql, *params):
        self.log.append((sql, params))

    def nextset(self):
        return False

    def fetchall(self):
        return [("VBank_ING.dbo.Users.ClientCode", 0.0328)]


class FakeConn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        pass


def test_visible_ids_viaja_como_json_y_es_obligatorio():
    log = []
    store = SqlServerVectorStore(lambda: FakeConn(log))
    hits = store.search_columns("ClientCode", visible_ids=frozenset({"produccion:SRVPRDSQL01.VBank_ING.dbo.Users"}))
    assert hits[0].table_key == "VBank_ING.dbo.Users"
    sql, params = log[0]
    assert "OPENJSON" in sql and "VECTOR_DISTANCE" in sql and "CONTAINSTABLE" in sql
    assert json.loads(params[0]) == ["produccion:SRVPRDSQL01.VBank_ING.dbo.Users"]
    try:
        store.search_tables("x", visible_ids=None)
    except ValueError:
        pass
    else:
        raise AssertionError("debió exigir visible_ids")
