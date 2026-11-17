"""Fixtures compartidas por `tests/` y `api/tests/`: una BD `ConverData` real y desechable (HU-05).

Las pruebas marcadas `sqlserver` necesitan una instancia de SQL Server 2016 o posterior. Se activan con la variable
`CONVERDATA_TEST_DB`, que es una cadena ODBC **del servidor, sin `DATABASE`**, con permiso para crear bases de datos:

    CONVERDATA_TEST_DB="DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;Trusted_Connection=yes;TrustServerCertificate=yes"

Sin la variable se omiten (CI y equipos sin SQL Server). Con ella, se crea una BD `ConverData_test_<aleatorio>`, se
aplican las migraciones y se elimina al terminar la sesión; nunca se toca una BD existente.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).parent / "db" / "converdata"


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlserver: necesita un SQL Server real (variable CONVERDATA_TEST_DB)")


def _server_string() -> str | None:
    value = os.environ.get("CONVERDATA_TEST_DB", "").strip().rstrip(";")
    if not value:
        return None
    from converdata.storage.connection import names_database

    if names_database(value):
        # Con una BD en la cadena, las pruebas publicarían un catálogo vacío y filas de auditoría falsas en ella.
        pytest.exit("CONVERDATA_TEST_DB no puede nombrar una base de datos (DATABASE=…): debe ser la cadena del servidor. "
                    "Las pruebas crean y eliminan su propia BD ConverData_test_<aleatorio>.", returncode=2)
    return value


@pytest.fixture(scope="session")
def sqlserver_database():
    """Cadena ODBC de una BD vacía y desechable; `pytest.skip` si no hay servidor configurado."""
    server = _server_string()
    if server is None:
        pytest.skip("CONVERDATA_TEST_DB no está definida: se omiten las pruebas contra SQL Server")
    import pyodbc

    from converdata.storage.connection import with_driver

    pyodbc.pooling = False  # sin conexiones en reserva: la BD temporal se puede eliminar al terminar
    server = with_driver(server)
    name = f"ConverData_test_{secrets.token_hex(4)}"
    admin = pyodbc.connect(f"{server};DATABASE=master", autocommit=True, timeout=10)
    admin.execute(f"CREATE DATABASE [{name}]")
    try:
        yield f"{server};DATABASE={name}"
    finally:
        admin.execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
        admin.execute(f"DROP DATABASE [{name}]")
        admin.close()


@pytest.fixture(scope="session")
def converdata_db(sqlserver_database):
    """Cadena ODBC de una BD `ConverData` con todas las migraciones aplicadas."""
    from converdata.storage.connection import connector
    from converdata.storage.migrations import migrate

    connect = connector(sqlserver_database)
    conn = connect()
    try:
        current = conn.cursor().execute("SELECT DB_NAME()").fetchone()[0]
    finally:
        conn.close()
    if not current.startswith("ConverData_test_"):  # defensa en profundidad: nunca migrar ni publicar en otra BD
        pytest.exit(f"Las pruebas se conectaron a {current!r} y no a su BD desechable", returncode=2)
    migrate(connect, MIGRATIONS)
    return sqlserver_database


@pytest.fixture
def db_connect(converdata_db):
    from converdata.storage.connection import connector

    return connector(converdata_db)


@pytest.fixture
def empty_catalog_db(converdata_db, db_connect):
    """La misma BD con el catálogo vacío: cada prueba de la API parte de un primer arranque."""
    from converdata.catalog.store import CatalogSnapshot, KnowledgeBase
    from converdata.config import Inventory, OwnersDirectory
    from converdata.storage.catalog_repository import SqlServerCatalogRepository

    SqlServerCatalogRepository(db_connect).publish(
        CatalogSnapshot(Inventory(servers=[]), [], KnowledgeBase(), OwnersDirectory()),
        published_by="prueba", reason="import")
    return converdata_db
