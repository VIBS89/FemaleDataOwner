"""Conocimiento no estructural (F23) y capturado de expertos (F24). Todo es clase D3/D4 de F17: ya redactado o anonimizado."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

KnowledgeKind = Literal["glossary", "business_rule", "document", "annotation", "etl", "data_dictionary"]


class LinkedAsset(BaseModel):
    asset_key: str
    method: Literal["exact", "semantic", "llm", "human"] = "exact"
    score: float = 1.0


class KnowledgeItem(BaseModel):
    """Fragmento indexable de conocimiento con sus vínculos al catálogo."""

    id: str
    kind: KnowledgeKind
    text: str
    source: str
    domain: str | None = None
    linked_assets: list[LinkedAsset] = Field(default_factory=list)
    allowed_groups: list[str] | None = None  # None = sin ACL de origen
    reviewed: bool = False
    redacted: bool = False

    @property
    def asset_keys(self) -> list[str]:
        return [link.asset_key for link in self.linked_assets]


class BusinessRule(BaseModel):
    id: str
    text: str
    domain: str | None = None
    applies_to: list[str]
    source: str | None = None
    owner: str | None = None
    reviewed: bool = False

    def as_item(self) -> KnowledgeItem:
        return KnowledgeItem(
            id=self.id,
            kind="business_rule",
            text=f"{self.id}: {self.text}",
            source=self.source or "knowledge/rules",
            domain=self.domain,
            linked_assets=[LinkedAsset(asset_key=a, method="human") for a in self.applies_to],
            reviewed=self.reviewed,
        )


class LineageVia(BaseModel):
    kind: Literal["ssis", "agent_job", "procedure", "view"]
    name: str
    job: str | None = None
    schedule: str | None = None


class LineageEdge(BaseModel):
    """Arista `etl` a nivel de tabla (un salto en la fase 1)."""

    model_config = {"populate_by_name": True}

    from_: str = Field(alias="from")
    to: str
    via: LineageVia
    level: Literal["table", "column"] = "table"

    def as_item(self) -> KnowledgeItem:
        return KnowledgeItem(
            id=f"etl:{self.via.name}:{self.from_}->{self.to}",
            kind="etl",
            text=f"{self.via.name}: {self.from_} → {self.to}.",
            source=f"{self.via.kind}:{self.via.name}",
            linked_assets=[LinkedAsset(asset_key=self.from_), LinkedAsset(asset_key=self.to)],
            reviewed=True,
        )


class BusinessEntity(BaseModel):
    """Nodo `entity` del grafo del patrimonio (F19): dónde vive un concepto de negocio entre BDs."""

    name: str
    synonyms: list[str] = Field(default_factory=list)
    definition: str | None = None
    tables: list[str]  # asset_keys de tablas que representan la entidad (aristas `same_entity`)
    canonical: str | None = None
    domain: str | None = None


class GoldenDiscovery(BaseModel):
    """Plantilla anonimizada de una pregunta de descubrimiento confirmada (F24)."""

    id: str
    template: str
    asset_keys: list[str]
    confirmed_by: Literal["steward", "users"]
    confirmations: int = 1
    rejected: bool = False
