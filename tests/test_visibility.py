"""Lectura de permisos por base de datos (F14): `PyodbcObjectLister`.

La prueba marcada `sqlserver` necesita `CONVERDATA_TEST_DB` (ver `conftest.py` de la raíz).
"""

import secrets

import pytest

from converdata.identity.visibility import PyodbcObjectLister, VisibleObject


class _Cursor:
    def __init__(self, database, access, objects):
        self.database, self.access, self.objects, self.row = database, access, objects, None

    def execute(self, sql, *params):
        self.row = (1 if self.access.get(params[0]) else 0,) if "HAS_DBACCESS" in sql else None

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.objects.get(self.database, [])


class _Connection:
    def __init__(self, cursor, closed):
        self._cursor, self._closed = cursor, closed

    def cursor(self):
        return self._cursor

    def close(self):
        self._closed.append(self._cursor.database)


def _lister(access, objects, broken=()):
    opened, closed = [], []

    def connect(server_id, database):
        opened.append(database)
        if database in broken or (database != "master" and not access.get(database)):
            raise ConnectionError("Login failed")  # así responde SQL Server al abrir una base sin acceso
        return _Connection(_Cursor(database, access, objects), closed)

    return PyodbcObjectLister(connect), opened, closed


def test_una_base_sin_acceso_no_oculta_las_demas():
    lister, opened, closed = _lister({"Alfa": False, "Beta": True}, {"Beta": [("dbo", "Cuentas", "U")]})
    assert list(lister.visible_objects("srv", ["Alfa", "Beta"])) == [VisibleObject("Beta", "dbo", "Cuentas")]
    assert opened == ["master", "Beta"]  # la base sin acceso ni siquiera se intenta abrir
    assert closed == opened


def test_una_base_que_deja_de_responder_solo_se_omite_ella():
    lister, _, _ = _lister({"Alfa": True, "Beta": True}, {"Beta": [("dbo", "Cuentas", "U")]}, broken={"Alfa"})
    assert [o.database for o in lister.visible_objects("srv", ["Alfa", "Beta"])] == ["Beta"]


def test_si_el_servidor_no_responde_no_se_ve_nada():
    lister, _, _ = _lister({"Beta": True}, {}, broken={"master"})
    with pytest.raises(ConnectionError):  # quien llama lo trata como "nada de ese servidor" (fail-closed)
        list(lister.visible_objects("srv", ["Beta"]))


@pytest.mark.sqlserver
def test_contra_sql_server_una_base_inaccesible_no_oculta_la_siguiente(sqlserver_database):
    """Regresión de DT-57: antes, el fallo al abrir la primera base cortaba el recorrido de todo el servidor."""
    import pyodbc

    server = sqlserver_database.rsplit(";DATABASE=", 1)[0]
    admin = pyodbc.connect(f"{server};DATABASE=master", autocommit=True, timeout=10)
    suffix = secrets.token_hex(4)
    closed_db, open_db = f"ConverData_vis_a_{suffix}", f"ConverData_vis_b_{suffix}"
    try:
        for name in (closed_db, open_db):
            admin.execute(f"CREATE DATABASE [{name}]")
        admin.execute(f"CREATE TABLE [{open_db}].dbo.Cuentas (Id int)")
        # Fuera de línea nadie puede abrirla: el mismo efecto que un login sin acceso a esa base.
        admin.execute(f"ALTER DATABASE [{closed_db}] SET OFFLINE WITH ROLLBACK IMMEDIATE")
        lister = PyodbcObjectLister(lambda _server, db: pyodbc.connect(f"{server};DATABASE={db}", timeout=10))
        seen = list(lister.visible_objects("srv", [closed_db, open_db]))
        assert seen == [VisibleObject(open_db, "dbo", "Cuentas")]
    finally:
        admin.execute(f"ALTER DATABASE [{closed_db}] SET ONLINE")
        for name in (closed_db, open_db):
            admin.execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            admin.execute(f"DROP DATABASE [{name}]")
        admin.close()
