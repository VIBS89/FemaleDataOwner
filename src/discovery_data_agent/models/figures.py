"""Cifras agregadas del AnswerEnvelope (primer corte del AskFlow). Solo totales: nunca filas de datos."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Operation = Literal["COUNT", "COUNT_DISTINCT", "SUM", "AVG"]


class FigureQuery(BaseModel):
    purpose: Literal["total", "cardinality", "groups"]
    sql: str  # plantilla fija con identificadores del catálogo; sin texto del usuario ni de un modelo


class FigurePlan(BaseModel):
    """Qué se va a calcular y dónde. Lo arma `discovery.figures.plan_figure`."""

    asset_key: str  # tabla o vista sobre la que se calcula
    server: str  # id del servidor en el inventario (no se muestra)
    database: str
    environment: str = ""  # ambiente de la copia sobre la que se calcula (se muestra)
    server_alias: str = ""  # alias mostrable del servidor, nunca el host
    operation: Operation
    description: str  # qué se calcula, en palabras
    group_by: str | None = None
    queries: list[FigureQuery]
    notes: list[str] = Field(default_factory=list)  # lo que la pregunta pedía y no se aplicó


class FigureGroup(BaseModel):
    label: str
    value: float | int


class Figure(BaseModel):
    """La cifra calculada. `sql` se muestra para que el equipo de datos pueda verificarla."""

    asset_key: str
    description: str
    environment: str = ""
    server_alias: str = ""
    operation: Operation
    value: float | int | None = None
    rows: int | None = None  # registros sobre los que se calculó el total
    group_by: str | None = None
    groups: list[FigureGroup] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sql: list[str] = Field(default_factory=list)
