"""Identificadores del catálogo (F1).

- Id físico: ``<environment>:<server>.<db>.<schema>.<objeto>``
- ``asset_key`` lógico: ``<db>.<schema>.<objeto>[.<columna>]``
"""

from __future__ import annotations


def physical_id(environment: str, server: str, database: str, schema: str, name: str) -> str:
    return f"{environment}:{server}.{database}.{schema}.{name}"


def asset_key_of(database: str, schema: str, name: str, column: str | None = None) -> str:
    key = f"{database}.{schema}.{name}"
    return f"{key}.{column}" if column else key


def table_key(asset_key: str) -> str:
    """`db.schema.tabla[.columna]` → `db.schema.tabla`."""
    parts = asset_key.split(".")
    return ".".join(parts[:3])


def is_column_key(asset_key: str) -> bool:
    return asset_key.count(".") >= 3


def short_name(asset_key: str) -> str:
    return asset_key.split(".")[-1]
