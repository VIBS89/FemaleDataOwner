"""Salida del nodo `intent` (F3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["discovery", "exploration", "data_query", "procedure", "out_of_scope", "ambiguous"]


class Clarification(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list, max_length=4)


class IntentResult(BaseModel):
    intent: Intent
    analysis_mode: Literal["lookup", "compare", "explain", "explore", "forecast", "report"] = "lookup"
    entities_resolved: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    domain: str | None = None
    entities: list[str] = Field(default_factory=list)
    business_context: str | None = None
    asset_kind_hint: Literal["column", "table", "indicator", "rule"] | None = None
    environment_hint: str | None = "produccion"
    literals: list[str] = Field(default_factory=list)
    time_range: str | None = None
    rewritten_question: str
    confidence: float = Field(ge=0.0, le=1.0)
    clarification: Clarification | None = None
