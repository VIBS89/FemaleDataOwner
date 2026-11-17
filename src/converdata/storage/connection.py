"""Conexión a la BD `ConverData` (OP-02).

La cadena llega de `CONVERDATA_DB`. En el servidor usa la cuenta del proceso (`Trusted_Connection=yes`, gMSA), sin
contraseña; nunca es la credencial de un usuario (esas viven en el SessionVault y solo sirven para leer permisos).
"""

from __future__ import annotations

import os
from typing import Callable

ENV_VAR = "CONVERDATA_DB"
Connect = Callable[[], object]


def connection_string(value: str | None = None) -> str | None:
    """La cadena ODBC configurada, o None si la BD `ConverData` no está configurada (modo archivos)."""
    value = (value if value is not None else os.environ.get(ENV_VAR, "")).strip()
    return value or None


def with_driver(conn_str: str) -> str:
    """Completa la cadena con el driver ODBC de SQL Server más reciente instalado, si no nombra uno."""
    if "DRIVER=" in conn_str.upper().replace(" ", ""):
        return conn_str
    import pyodbc

    installed = pyodbc.drivers()
    for name in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
        if name in installed:
            return f"DRIVER={{{name}}};{conn_str}"
    raise RuntimeError("No hay un driver ODBC de SQL Server instalado (ODBC Driver 18 o 17 for SQL Server)")


def connector(conn_str: str, *, timeout_s: int = 5) -> Connect:
    """Devuelve `connect()`: cada llamada abre una conexión (el administrador de ODBC las agrupa)."""
    conn_str = with_driver(conn_str)
    if "APP=" not in conn_str.upper().replace(" ", ""):
        conn_str = conn_str.rstrip(";") + ";APP=ConverData"

    def connect():
        import pyodbc

        return pyodbc.connect(conn_str, timeout=timeout_s)

    return connect


def names_database(conn_str: str) -> bool:
    """¿La cadena fija una base de datos? Las pruebas exigen una cadena de servidor para no tocar nunca una BD real."""
    keys = {chunk.partition("=")[0].strip().lower() for chunk in conn_str.split(";")}
    return bool(keys & {"database", "initial catalog"})


def describe(conn_str: str) -> str:
    """Servidor y BD de la cadena, sin usuario ni contraseña (para logs y mensajes)."""
    parts = {}
    for chunk in conn_str.split(";"):
        key, _, value = chunk.partition("=")
        parts[key.strip().lower()] = value.strip()
    return f"{parts.get('server', '?')}/{parts.get('database', '?')}"
