"""Sección `discovery` del AnswerEnvelope (F22) y AnswerEnvelope (PRD §8.3)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from converdata.models.catalog import DescriptionSource
from converdata.models.intent import Clarification


class Location(BaseModel):
    environment: str
    server: str  # alias mostrable (config/databases.yaml), nunca el host


class RuleRef(BaseModel):
    id: str
    text: str
    reviewed: bool


class Owners(BaseModel):
    business: str | None = None
    technical: str | None = None


class Lineage(BaseModel):
    upstream: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    kind: str
    source: str
    reviewed: bool | None = None


class Candidate(BaseModel):
    rank: int
    kind: Literal["column", "table", "view", "procedure"]
    asset_key: str
    database: str
    schema_: str = Field(alias="schema")
    table: str
    column: str | None = None
    data_type: str | None = None
    locations: list[Location] = Field(default_factory=list)
    drift_warning: str | None = None
    description: str | None = None
    description_source: DescriptionSource = "generated"
    business_rules: list[RuleRef] = Field(default_factory=list)
    owners: Owners = Field(default_factory=Owners)
    lineage: Lineage = Field(default_factory=Lineage)
    evidence: list[Evidence] = Field(default_factory=list)
    why: str = ""
    confidence: float = 0.0
    copies: list[str] = Field(default_factory=list)  # el mismo dato en otras BDs (misma entidad, F19)

    model_config = {"populate_by_name": True}


class JoinPath(BaseModel):
    """Cómo cruzar el candidato principal con la tabla que responde otra parte de la pregunta (GraphRAG, F19)."""

    purpose: str  # término de la pregunta que resuelve la tabla destino
    tables: list[str]
    steps: list[str]  # "A → B (fk: ClienteID)"


class Alternative(BaseModel):
    asset_key: str
    why: str
    confidence: float


class Related(BaseModel):
    from_: str = Field(alias="from")
    to: str
    relation: Literal["fk", "etl", "same_entity"]
    on: str | None = None
    via: str | None = None

    model_config = {"populate_by_name": True}


class Discovery(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    related: list[Related] = Field(default_factory=list)
    join_paths: list[JoinPath] = Field(default_factory=list)
    knowledge_gap: bool = False
    unresolved_parts: list[str] = Field(default_factory=list)  # partes de una pregunta compuesta sin respuesta
    suggested_questions: list[str] = Field(default_factory=list)


class Check(BaseModel):
    name: str
    status: Literal["pass", "warn", "fail", "fixed"]
    detail: str = ""


class Validation(BaseModel):
    """Revisión del resultado (patrón evaluador-optimizador). En el AskFlow también lleva static/compile/plan (F7)."""

    checks: list[Check] = Field(default_factory=list)
    judge: dict | None = None  # veredicto del juez LLM, si intervino
    attempts: int = 1


class AnswerEnvelope(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flow: Literal["discover", "ask"] = "discover"
    status: Literal["ok", "needs_clarification", "rejected", "error"] = "ok"
    answer_text: str = ""
    clarification: Clarification | None = None
    databases: list[str] = Field(default_factory=list)
    tables_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validation: Validation | None = None
    confidence: float | None = None
    discovery: Discovery | None = None
    timings_ms: dict[str, int] = Field(default_factory=dict)
