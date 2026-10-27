"""Extractor de metadatos de SQL Server (F18), solo lectura y con consultas fijas.

Una pasada por base de datos: objetos, columnas, PKs, FKs, filas aproximadas, `MS_Description`, clasificación de
sensibilidad, dependencias de vistas y SPs, y parámetros de SPs. No hay ninguna función que acepte SQL del llamador.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Callable

from converdata.config import ServerConfig
from converdata.metadata.ports import MetadataSource, RawColumn, RawObject  # noqa: F401  (reexportados)

log = logging.getLogger(__name__)

SYSTEM_DATABASES = {"master", "model", "msdb", "tempdb", "SSISDB", "ReportServer", "ReportServerTempDB"}

# --- consultas fijas -------------------------------------------------------------------------------
Q_DATABASES = """
SELECT name FROM sys.databases
WHERE database_id > 4 AND state_desc = 'ONLINE' AND HAS_DBACCESS(name) = 1
ORDER BY name
"""
Q_OBJECTS = """
SELECT o.object_id, s.name, o.name, o.type, CAST(ep.value AS nvarchar(4000))
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.extended_properties ep
       ON ep.class = 1 AND ep.major_id = o.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
WHERE o.type IN ('U', 'V', 'P') AND o.is_ms_shipped = 0
ORDER BY s.name, o.name
"""
Q_COLUMNS = """
SELECT c.object_id, c.column_id, c.name, t.name, c.max_length, c.precision, c.scale, c.is_nullable,
       CAST(ep.value AS nvarchar(4000))
FROM sys.columns c
JOIN sys.types t ON t.user_type_id = c.user_type_id
JOIN sys.objects o ON o.object_id = c.object_id AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0
LEFT JOIN sys.extended_properties ep
       ON ep.class = 1 AND ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
ORDER BY c.object_id, c.column_id
"""
Q_PRIMARY_KEYS = """
SELECT ic.object_id, c.name
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE i.is_primary_key = 1
ORDER BY ic.object_id, ic.key_ordinal
"""
Q_FOREIGN_KEYS = """
SELECT fk.name, fk.parent_object_id, pc.name, rs.name, ro.name, rc.name
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.objects ro ON ro.object_id = fkc.referenced_object_id
JOIN sys.schemas rs ON rs.schema_id = ro.schema_id
JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
ORDER BY fk.name, fkc.constraint_column_id
"""
Q_ROW_COUNTS = """
SELECT object_id, SUM(rows) FROM sys.partitions WHERE index_id IN (0, 1) GROUP BY object_id
"""
Q_SENSITIVITY = """
SELECT major_id, minor_id, CAST(label AS nvarchar(256)), CAST(information_type AS nvarchar(256))
FROM sys.sensitivity_classifications
"""
Q_DEPENDENCIES = """
SELECT d.referencing_id, d.referenced_server_name, d.referenced_database_name,
       COALESCE(d.referenced_schema_name, 'dbo'), d.referenced_entity_name
FROM sys.sql_expression_dependencies d
JOIN sys.objects o ON o.object_id = d.referencing_id AND o.type IN ('V', 'P')
WHERE d.referenced_entity_name IS NOT NULL
"""
Q_PARAMETERS = """
SELECT p.object_id, p.name, t.name, p.max_length, p.precision, p.scale, p.is_output, p.has_default_value
FROM sys.parameters p
JOIN sys.types t ON t.user_type_id = p.user_type_id
JOIN sys.procedures pr ON pr.object_id = p.object_id
WHERE p.parameter_id > 0
ORDER BY p.object_id, p.parameter_id
"""


def format_type(type_name: str, max_length: int, precision: int, scale: int) -> str:
    t = type_name.lower()
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}({'max' if max_length == -1 else max_length})"
    if t in ("nvarchar", "nchar"):
        return f"{t}({'max' if max_length == -1 else max_length // 2})"
    if t in ("decimal", "numeric"):
        return f"{t}({precision},{scale})"
    if t in ("datetime2", "time", "datetimeoffset") and scale not in (None, 7):
        return f"{t}({scale})"
    return t


def connection_string(server: ServerConfig, database: str = "master", driver: str | None = None) -> str:
    """Cadena ODBC del login de metadatos. Las credenciales nunca se registran en logs."""
    driver = driver or best_driver()
    host = server.read_replica or server.host or server.id
    parts = [f"DRIVER={{{driver}}}", f"SERVER={host}", f"DATABASE={database}", "APP=ConverData-Builder", "Encrypt=yes"]
    if server.trust_server_certificate:
        parts.append("TrustServerCertificate=yes")
    if server.read_replica:
        parts.append("ApplicationIntent=ReadOnly")
    if server.auth == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        user = os.environ.get(server.metadata_user_env or "")
        password = os.environ.get(server.metadata_password_env or "")
        if not user or not password:
            raise RuntimeError(f"Faltan las variables {server.metadata_user_env}/{server.metadata_password_env} del login de metadatos")
        parts += [f"UID={user}", f"PWD={password}"]
    return ";".join(parts)


def best_driver() -> str:
    import pyodbc

    drivers = pyodbc.drivers()
    for name in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
        if name in drivers:
            return name
    raise RuntimeError("No hay ODBC Driver 17/18 para SQL Server instalado")


class SqlServerMetadata:
    def __init__(self, server: ServerConfig, connect: Callable[[str], object] | None = None, timeout_s: int = 30):
        self.server = server
        self.timeout_s = timeout_s
        self._connect = connect or self._pyodbc_connect

    def _pyodbc_connect(self, database: str):
        import pyodbc

        conn = pyodbc.connect(connection_string(self.server, database), timeout=self.timeout_s, readonly=True)
        conn.timeout = self.timeout_s
        return conn

    def _rows(self, conn, sql: str):
        cur = conn.cursor()
        cur.execute("SET LOCK_TIMEOUT 2000;")  # F18: nunca bloquear al servidor de datos
        cur.execute(sql)
        return cur.fetchall()

    def list_databases(self) -> list[str]:
        if not self.server.all_databases:
            return list(self.server.databases)
        conn = self._connect("master")
        try:
            return [r[0] for r in self._rows(conn, Q_DATABASES) if r[0] not in SYSTEM_DATABASES]
        finally:
            conn.close()

    def extract_database(self, database: str) -> list[RawObject]:
        conn = self._connect(database)
        try:
            objects: dict[int, RawObject] = {}
            kinds = {"U": "table", "V": "view", "P": "procedure"}
            for oid, schema, name, otype, desc in self._rows(conn, Q_OBJECTS):
                objects[oid] = RawObject(database, schema, name, kinds[otype.strip()], desc)
            sensitivity: dict[tuple[int, int], str] = {}
            try:
                for major, minor, label, info in self._rows(conn, Q_SENSITIVITY):
                    sensitivity[(major, minor)] = " / ".join(filter(None, [label, info]))
            except Exception:  # SQL Server < 2019 o sin permiso: la clasificación es opcional
                log.info("sin sys.sensitivity_classifications en %s", database)
            for oid, col_id, name, tname, max_len, prec, scale, nullable, desc in self._rows(conn, Q_COLUMNS):
                if oid in objects:
                    objects[oid].columns.append(
                        RawColumn(name, format_type(tname, max_len, prec, scale), bool(nullable), desc,
                                  sensitivity.get((oid, col_id)))
                    )
            for oid, col in self._rows(conn, Q_PRIMARY_KEYS):
                if oid in objects:
                    objects[oid].primary_key.append(col)
            fks: dict[str, dict] = {}
            for fk_name, parent, pcol, rschema, rtable, rcol in self._rows(conn, Q_FOREIGN_KEYS):
                fk = fks.setdefault(fk_name, {"name": fk_name, "parent": parent, "columns": [], "ref_schema": rschema,
                                              "ref_table": rtable, "ref_columns": []})
                fk["columns"].append(pcol)
                fk["ref_columns"].append(rcol)
            for fk in fks.values():
                if fk["parent"] in objects:
                    objects[fk.pop("parent")].foreign_keys.append(fk)
            for oid, rows in self._rows(conn, Q_ROW_COUNTS):
                if oid in objects:
                    objects[oid].row_count = int(rows)
            deps: dict[int, set[str]] = defaultdict(set)
            for oid, rserver, rdb, rschema, rname in self._rows(conn, Q_DEPENDENCIES):
                if oid in objects and not rserver:
                    deps[oid].add(f"{rdb or database}.{rschema}.{rname}")
            for oid, keys in deps.items():
                objects[oid].dependencies = sorted(keys)
            for oid, pname, tname, max_len, prec, scale, is_out, has_default in self._rows(conn, Q_PARAMETERS):
                if oid in objects:
                    objects[oid].parameters.append({
                        "name": pname, "type": format_type(tname, max_len, prec, scale),
                        "direction": "out" if is_out else "in", "has_default": bool(has_default),
                    })
            return list(objects.values())
        finally:
            conn.close()
