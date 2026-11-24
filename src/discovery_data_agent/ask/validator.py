"""Validador pre-ejecución del AskFlow (F7): ninguna consulta llega a SQL Server sin pasar por aquí.

Etapas, cada una corta el proceso si falla:
1. Parseo con sqlglot (`tsql`): una sola sentencia, sin errores de sintaxis.
2. Tipo de sentencia: solo `SELECT` (con CTEs o UNION). Nada de `SELECT … INTO`.
3. Lista negra: escritura, DDL, `EXEC`, funciones de acceso externo, `WAITFOR`, `DBCC`… (AST y regex de respaldo).
4. Objetos: cada tabla debe existir en el catálogo, ser visible para el usuario y estar en la base del plan.
5. Normalización: `TOP (max_rows + 1)` si falta o si pide más, para detectar truncado.

La compilación y el costo (etapas 6 y 7) los cubre SQL Server al ejecutar con los permisos y el timeout del usuario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from converdata.catalog.store import Catalog

BLOCKED = re.compile(
    r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|deny|exec|execute|openrowset|openquery|"
    r"opendatasource|waitfor|dbcc|shutdown|bulk|backup|restore|reconfigure)\b|\bxp_\w+|\bsp_\w+",
    re.I,
)
WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter, exp.Command,
               exp.TruncateTable, exp.Grant)


class ValidationError(ValueError):
    """La consulta no se puede ejecutar; `feedback` vuelve al planner para que la corrija."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


@dataclass
class ValidatedQuery:
    sql: str
    database: str
    tables: list[str] = field(default_factory=list)  # asset_keys de tres partes


def _strip_literals(sql: str) -> str:
    """Quita cadenas y comentarios para que la regex de respaldo no salte con un `'delete'` dentro de un texto."""
    sql = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"N?'(?:[^']|'')*'", "''", sql)


def validate(sql: str, database: str, catalog: Catalog, visible_ids, max_rows: int) -> ValidatedQuery:
    try:
        statements = [s for s in sqlglot.parse(sql, read="tsql") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise ValidationError("parse", f"El SQL no es T-SQL válido: {str(exc).splitlines()[0]}") from None
    if len(statements) != 1:
        raise ValidationError("parse", "Debe ser exactamente una sentencia SELECT.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise ValidationError("statement", "Solo se permiten consultas SELECT.")
    if any(tree.find_all(*WRITE_NODES)) or any(s.args.get("into") for s in tree.find_all(exp.Select)):
        raise ValidationError("statement", "La consulta intenta escribir o modificar objetos.")
    if BLOCKED.search(_strip_literals(sql)):
        raise ValidationError("blocklist", "La consulta usa una instrucción o función no permitida.")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name:
            raise ValidationError("objects", "Solo se pueden consultar tablas o vistas del catálogo.")
        if not table.db and not table.catalog and name.lower() in ctes:
            continue
        db = table.catalog or database
        if db.lower() != database.lower():
            raise ValidationError("objects", f"Todas las tablas deben estar en la base {database}.")
        key = f"{db}.{table.db or 'dbo'}.{name}"
        match = next((k for k in catalog.table_keys() if k.lower() == key.lower()), None)
        if match is None or not catalog.is_visible(match, visible_ids):
            raise ValidationError("objects", f"La tabla {key} no existe en el catálogo o no tienes acceso a ella.")
        if match not in tables:
            tables.append(match)
    if not tables:
        raise ValidationError("objects", "La consulta debe leer al menos una tabla del catálogo.")

    cap = max_rows + 1
    if isinstance(tree, exp.Select):
        limit = tree.args.get("limit")
        current = None
        if limit is not None:
            try:
                current = int(limit.expression.name)
            except (AttributeError, ValueError):
                current = None
        if current is None or current > cap:
            tree = tree.limit(cap)
    return ValidatedQuery(sql=tree.sql(dialect="tsql"), database=database, tables=tables)
