"""Puertos de los tres nodos que razonan con LLM (intent, rerank, respond).

Cada puerto tiene una implementación determinista (`converdata.discovery.deterministic`) y una con LLM
(`converdata.llm.nodes`, servida por el gateway: NVIDIA NIM o Bedrock). El grafo no sabe cuál usa: el orden de los pasos nunca depende del modelo (PRD §8.1).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from converdata.models.discovery import Discovery
from converdata.models.intent import IntentResult


class RerankItem(BaseModel):
    """Formato compacto que recibe el reranker (F22 paso 4)."""

    id: str
    kind: str
    description: str | None
    description_source: str
    rules: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class RerankScore(BaseModel):
    id: str
    relevance: float = Field(ge=0.0, le=1.0)
    why: str = Field(description="Justificación de una línea, en español")


class RerankResult(BaseModel):
    items: list[RerankScore]


class DiscoveryVerdict(BaseModel):
    """Veredicto del juez (rol `judge`) sobre el candidato principal."""

    answers_question: bool = Field(description="¿El candidato principal responde la pregunta?")
    issues: list[str] = Field(default_factory=list, description="Problemas concretos, en español")
    better_candidate: str | None = Field(None, description="id de la lista que responde mejor; nunca un id nuevo")
    score: float = Field(ge=0.0, le=1.0)


class QueryVariants(BaseModel):
    variants: list[str] = Field(default_factory=list, max_length=3,
                                description="Reformulaciones con términos técnicos o nombres probables de columnas")


class QueryExpander(Protocol):
    def expand(self, question: str, weak_terms: list[str]) -> list[str]: ...


class Reviewer(Protocol):
    def review(self, question: str, items: list[RerankItem], top_id: str, issues: list[str]) -> DiscoveryVerdict: ...


class IntentClassifier(Protocol):
    def classify(self, question: str, history: list[str]) -> IntentResult: ...


class Reranker(Protocol):
    def rerank(self, question: str, items: list[RerankItem]) -> list[RerankScore]: ...


class Narrator(Protocol):
    def narrate(self, question: str, discovery: Discovery) -> str: ...
