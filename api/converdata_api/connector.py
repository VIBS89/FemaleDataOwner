"""Conexiones a SQL Server con la credencial del propio usuario (F14, OP-03).

`SqlConnector` usa pyodbc. `DemoConnector` simula los servidores de uno o varios fixtures (sin valores de datos) para
probar el flujo completo sin SQL Server; solo se activa con `CONVERDATA_DEMO=1`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from converdata.catalog.files import FileCatalogStore
from converdata.config import Inventory, ServerConfig, load_inventory
from converdata.identity.visibility import ObjectLister, PyodbcObjectLister, VisibleObject
from converdata.metadata.sqlserver import MetadataSource, RawColumn, RawObject, SqlServerMetadata, best_driver

from converdata_api.vault import Credential

Q_IDENTIFY = """
SELECT SUSER_SNAME(), IS_SRVROLEMEMBER('sysadmin'), HAS_PERMS_BY_NAME(NULL, NULL, 'VIEW ANY DEFINITION')
"""


class LoginFailed(Exception):
    """Mensaje apto para el usuario: nunca incluye la contraseña ni el host."""


@dataclass(frozen=True)
class LoginInfo:
    sql_login: str
    can_build: bool  # sysadmin o VIEW ANY DEFINITION: puede descubrir los esquemas del servidor


class Connector(Protocol):
    def identify(self, server: ServerConfig, cred: Credential) -> LoginInfo: ...
    def object_lister(self, servers: dict[str, ServerConfig], cred: Credential) -> ObjectLister: ...
    def metadata_source(self, server: ServerConfig, cred: Credential) -> MetadataSource: ...


class SqlConnector:
    def __init__(self, timeout_s: int = 10):
        self.timeout_s = timeout_s

    def connection_string(self, server: ServerConfig, cred: Credential, database: str = "master") -> str:
        host = server.read_replica or server.host or server.id
        parts = [f"DRIVER={{{best_driver()}}}", f"SERVER={host}", f"DATABASE={database}", "APP=ConverData", "Encrypt=yes"]
        if server.trust_server_certificate:
            parts.append("TrustServerCertificate=yes")
        if server.read_replica:
            parts.append("ApplicationIntent=ReadOnly")
        if cred.login is None:
            parts.append("Trusted_Connection=yes")
        else:
            parts += [f"UID={cred.login}", "PWD={" + (cred.password or "").replace("}", "}}") + "}"]
        return ";".join(parts)

    def connect(self, server: ServerConfig, cred: Credential, database: str = "master"):
        import pyodbc

        conn = pyodbc.connect(self.connection_string(server, cred, database), timeout=self.timeout_s, readonly=True)
        conn.timeout = 30
        return conn

    def identify(self, server: ServerConfig, cred: Credential) -> LoginInfo:
        import pyodbc

        try:
            conn = self.connect(server, cred)
        except pyodbc.InterfaceError as exc:
            raise LoginFailed("No hay un driver ODBC 17/18 para SQL Server") from exc
        except pyodbc.Error as exc:
            state = exc.args[0] if exc.args else ""
            if state == "28000":
                raise LoginFailed("Usuario o contraseña incorrectos") from None
            raise LoginFailed("No se pudo conectar al servidor") from None
        try:
            login, sysadmin, view_def = conn.cursor().execute(Q_IDENTIFY).fetchone()
            return LoginInfo(sql_login=login, can_build=bool(sysadmin) or bool(view_def))
        finally:
            conn.close()

    def object_lister(self, servers: dict[str, ServerConfig], cred: Credential) -> ObjectLister:
        return PyodbcObjectLister(lambda server_id, db: self.connect(servers[server_id], cred, db))

    def metadata_source(self, server: ServerConfig, cred: Credential) -> MetadataSource:
        return SqlServerMetadata(server, connect=lambda db: self.connect(server, cred, db))


# --- modo demo --------------------------------------------------------------------------------------
DEMO_PASSWORD = "demo"


@dataclass(frozen=True)
class DemoUser:
    databases: list[str] | None  # BDs que puede leer (None = todas): muestra la herencia de permisos (F14)
    can_build: bool  # sysadmin o VIEW ANY DEFINITION en el servidor simulado → rol data_admin


DEMO_USERS: dict[str, DemoUser] = {
    "demo": DemoUser(None, can_build=True),
    "analista": DemoUser(["VBank_ING", "Onboarding", "DWH", "BancaPrestamos", "BancaCuentasDebito"], can_build=False),
    "responsable": DemoUser(None, can_build=False),  # steward de todos los dominios (curation/stewards.yaml)
}


def _as_list(fixtures: Path | list[Path]) -> list[Path]:
    return [Path(f) for f in fixtures] if isinstance(fixtures, (list, tuple)) else [Path(fixtures)]


class FixtureMetadata:
    """Devuelve los metadatos de uno o varios catálogos de fixture como si los leyera de `sys.*` de un servidor.

    Con `server_id` de un servidor de los fixtures, solo sus objetos; con otro (el primer arranque registra uno nuevo),
    una copia de cada objeto de todos los fixtures."""

    def __init__(self, fixtures: Path | list[Path], databases: list[str] | None = None, server_id: str | None = None):
        objects = []
        for fixture in _as_list(fixtures):
            inventory = load_inventory(fixture / "config" / "databases.yaml")
            objects += FileCatalogStore(fixture).load_catalog(inventory).objects
        known = {o.server for o in objects}
        if server_id in known:
            objects = [o for o in objects if o.server == server_id]
        else:
            seen, unique = set(), []
            for o in objects:
                if (o.database, o.schema_, o.name) not in seen:
                    seen.add((o.database, o.schema_, o.name))
                    unique.append(o)
            objects = unique
        self.objects = objects
        self.allowed = databases

    def list_databases(self) -> list[str]:
        dbs = sorted({o.database for o in self.objects})
        return [d for d in dbs if self.allowed is None or d in self.allowed]

    def extract_database(self, database: str) -> list[RawObject]:
        out = []
        for o in self.objects:
            if o.database != database:
                continue
            fks = []
            for i, fk in enumerate(o.foreign_keys):
                _db, ref_schema, ref_table = fk.ref.split(".", 2)
                fks.append({"name": f"FK_{o.name}_{i}", "columns": fk.columns, "ref_schema": ref_schema,
                            "ref_table": ref_table, "ref_columns": fk.ref_columns})
            out.append(RawObject(
                database=o.database, schema=o.schema_, name=o.name, kind=o.kind,
                ms_description=o.description if o.description_source == "ms_description" else None,
                columns=[RawColumn(c.name, c.type, c.nullable,
                                   c.description if c.description_source == "ms_description" else None,
                                   "Confidential / PII" if c.pii else None) for c in o.columns],
                primary_key=list(o.primary_key), foreign_keys=fks, row_count=o.row_count,
                parameters=[p.model_dump() for p in o.parameters],
            ))
        return out


class _FixtureLister:
    def __init__(self, fixtures: list[Path], databases: list[str] | None):
        self.fixtures, self.databases = fixtures, databases

    def visible_objects(self, server_id: str, databases: list[str]) -> Iterable[VisibleObject]:
        metadata = FixtureMetadata(self.fixtures, self.databases, server_id)
        allowed = set(metadata.list_databases())
        for o in metadata.objects:
            if o.database in databases and o.database in allowed:
                yield VisibleObject(o.database, o.schema_, o.name)


class DemoConnector:
    def __init__(self, fixtures: Path | list[Path]):
        self.fixtures = _as_list(fixtures)

    def _check(self, cred: Credential) -> DemoUser:
        user = DEMO_USERS.get((cred.login or "").lower())
        if user is None or cred.password != DEMO_PASSWORD:
            raise LoginFailed("Usuario o contraseña incorrectos")
        return user

    def identify(self, server: ServerConfig, cred: Credential) -> LoginInfo:
        return LoginInfo(sql_login=cred.login.lower(), can_build=self._check(cred).can_build)

    def object_lister(self, servers: dict[str, ServerConfig], cred: Credential) -> ObjectLister:
        return _FixtureLister(self.fixtures, self._check(cred).databases)

    def metadata_source(self, server: ServerConfig, cred: Credential) -> MetadataSource:
        return FixtureMetadata(self.fixtures, self._check(cred).databases, server.id)


def server_from_host(host: str, alias: str | None, environment: str, trust_certificate: bool,
                     inventory: Inventory) -> ServerConfig:
    """Primer arranque: el servidor del primer login entra al inventario y el agente descubre todas sus BDs."""
    base = "".join(ch if ch.isalnum() else "_" for ch in host.upper()).strip("_") or "SERVIDOR"
    server_id, n = base, 2
    while inventory.server(server_id):
        server_id, n = f"{base}_{n}", n + 1
    return ServerConfig(id=server_id, host=host, alias=alias or host, environment=environment, is_reference=True,
                        databases=["*"], auth="sql", trust_server_certificate=trust_certificate)
