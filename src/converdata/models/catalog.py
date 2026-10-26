"""Formato lógico de un objeto del catálogo (F1). El catálogo nunca contiene valores de datos."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DescriptionSource = Literal["human", "data_dictionary", "ms_description", "document", "generated"]
ObjectKind = Literal["table", "view", "procedure"]

# Campos prohibidos en cualquier YAML de catálogo (F1, F17): el indexador rechaza el objeto.
FORBIDDEN_KEYS = {"sample_values", "samples", "values", "sample_rows"}


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    nullable: bool = True
    description: str | None = None
    description_source: DescriptionSource = "generated"
    reviewed: bool = False
    synonyms: list[str] = Field(default_factory=list)
    low_cardinality: bool = False
    pii: bool = False


class ForeignKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    ref: str  # asset_key de la tabla referenciada (misma BD y ambiente)
    ref_columns: list[str]


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    direction: Literal["in", "out", "inout"] = "in"
    has_default: bool = False


class Drift(BaseModel):
    environment: str
    detail: str


class CatalogObject(BaseModel):
    """Una copia física de un objeto en un ambiente y servidor."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    asset_key: str
    environment: str
    server: str
    kind: ObjectKind = "table"
    database: str
    schema_: str = Field(alias="schema")
    name: str
    description: str | None = None
    description_source: DescriptionSource = "generated"
    reviewed: bool = False
    domain: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    row_count: int | None = None
    primary_key: list[str] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    schema_hash: str | None = None
    drift: list[Drift] = Field(default_factory=list)
    deprecated: bool = False

    @model_validator(mode="before")
    @classmethod
    def _reject_values(cls, data):
        if isinstance(data, dict):
            _assert_no_values(data, data.get("id", "?"))
        return data

    @model_validator(mode="after")
    def _check_ids(self):
        from converdata.catalog.ids import asset_key_of, physical_id

        expected = physical_id(self.environment, self.server, self.database, self.schema_, self.name)
        if self.id != expected:
            raise ValueError(f"id {self.id!r} no corresponde a {expected!r}")
        if self.asset_key != asset_key_of(self.database, self.schema_, self.name):
            raise ValueError(f"asset_key {self.asset_key!r} inconsistente con {self.id!r}")
        return self

    def column_asset_key(self, column: str) -> str:
        return f"{self.asset_key}.{column}"


def _assert_no_values(node, where: str) -> None:
    if isinstance(node, dict):
        bad = FORBIDDEN_KEYS.intersection(node)
        if bad:
            raise ValueError(f"El catálogo no puede contener valores de datos ({', '.join(sorted(bad))}) en {where}")
        for value in node.values():
            _assert_no_values(value, where)
    elif isinstance(node, list):
        for value in node:
            _assert_no_values(value, where)
