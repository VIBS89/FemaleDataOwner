"""Puerto de lectura de metadatos (F18) y sus DTOs: lo que el Catalog Builder necesita de un servidor.

`converdata.metadata.sqlserver.SqlServerMetadata` es el adaptador real (pyodbc); los tests usan fuentes falsas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawColumn:
    name: str
    type: str
    nullable: bool
    ms_description: str | None = None
    sensitivity: str | None = None


@dataclass
class RawObject:
    database: str
    schema: str
    name: str
    kind: str  # table | view | procedure
    ms_description: str | None = None
    columns: list[RawColumn] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[dict] = field(default_factory=list)  # {name, columns, ref_schema, ref_table, ref_columns}
    row_count: int | None = None
    dependencies: list[str] = field(default_factory=list)  # asset_keys referenciados (vistas y SPs)
    parameters: list[dict] = field(default_factory=list)


class MetadataSource(Protocol):
    """Lo que el Catalog Builder necesita de un servidor. `SqlServerMetadata` lo implementa con pyodbc."""

    def list_databases(self) -> list[str]: ...
    def extract_database(self, database: str) -> list[RawObject]: ...
