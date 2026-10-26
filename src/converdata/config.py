"""Carga de `config/*.yaml`: inventario de servidores (F1, F18), responsables (F24) y ajustes del flujo."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    id: str
    host: str | None = None  # nunca se muestra al usuario
    alias: str
    environment: str
    platform: str = "sqlserver"
    is_reference: bool = False
    databases: list[str] = Field(default_factory=list)  # ["*"] = todas las BDs de usuario accesibles al login de metadatos
    read_replica: str | None = None
    # Login de metadatos (F18): autenticación Windows (gMSA on-premise, usuario local en desarrollo) o login SQL
    # cuyas credenciales se leen de variables de entorno (en el servidor, desde DPAPI).
    auth: Literal["windows", "sql"] = "windows"
    metadata_user_env: str | None = None
    metadata_password_env: str | None = None
    trust_server_certificate: bool = False  # solo desarrollo: instancias locales con certificado autofirmado

    @property
    def all_databases(self) -> bool:
        return self.databases == ["*"]


class Inventory(BaseModel):
    servers: list[ServerConfig]

    def server(self, server_id: str) -> ServerConfig | None:
        return next((s for s in self.servers if s.id == server_id), None)

    def alias(self, server_id: str) -> str:
        server = self.server(server_id)
        return server.alias if server else server_id

    def is_reference(self, environment: str, server_id: str) -> bool:
        server = self.server(server_id)
        return bool(server and server.is_reference and server.environment == environment)


class OwnerRef(BaseModel):
    name: str
    group: str


class DomainOwners(BaseModel):
    domain: str
    assets: list[str]
    business_owner: OwnerRef | None = None
    technical_owner: OwnerRef | None = None

    def matches(self, asset_key: str) -> bool:
        return any(fnmatch.fnmatchcase(asset_key, pattern) for pattern in self.assets)


class OwnersDirectory(BaseModel):
    domains: list[DomainOwners] = Field(default_factory=list)

    def for_asset(self, asset_key: str) -> DomainOwners | None:
        return next((d for d in self.domains if d.matches(asset_key)), None)


class ConfidenceWeights(BaseModel):
    """Pesos de la confianza de descubrimiento (F22)."""

    relevance_llm: float = 0.35
    retrieval: float = 0.25
    evidence: float = 0.15
    confirmation: float = 0.15
    agreement: float = 0.10


class DiscoverySettings(BaseModel):
    k_columns: int = 50
    k_tables: int = 30
    k_knowledge: int = 30
    k_golden: int = 5
    rerank_max: int = 25
    expand_top: int = 5
    max_candidates: int = 3
    secondary_candidate_min: float = 0.5
    max_alternatives: int = 3
    min_relevance: float = 0.4  # por debajo, el activo no responde la pregunta y no se muestra
    gap_threshold: float = 0.6
    generated_only_cap: float = 0.6
    golden_similarity_min: float = 0.85
    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    # Patrones de mejora (ver Patterns): umbrales
    variant_weight: float = 0.8  # peso de las variantes de la consulta frente a la pregunta original
    grade_min_coverage: float = 0.6  # C: por debajo, la recuperación es pobre y se reformula una vez
    cascade_min_confidence: float = 0.85  # E: con esta confianza determinista y margen, no se llama al reranker LLM
    cascade_margin: float = 0.10
    review_judge_band: tuple[float, float] = (0.5, 0.75)  # B: el juez LLM opina en esta franja o si hay chequeos fallidos
    ambiguous_margin: float = 0.05


class Patterns(BaseModel):
    """Patrones de agentes activables por separado, para medir su efecto con `converdata eval discovery`."""

    query_expansion: bool = True  # D: términos técnicos (es→en) y foco de la pregunta
    grade: bool = True  # C: RAG correctivo, califica la recuperación y reformula una vez
    review: bool = True  # B: evaluador-optimizador, chequeos + juez con un reintento acotado
    cascade: bool = True  # E: el LLM solo interviene cuando el resultado determinista no es claro
    graph: bool = True  # GraphRAG: copias de una entidad agrupadas y caminos de unión entre tablas y BDs


class Features(BaseModel):
    ask_flow: bool = False  # fase 1a: las preguntas de datos se responden como descubrimiento (F3)


class AuditSettings(BaseModel):
    fail_open: bool = False  # F11: fail-closed salvo en dev


class Settings(BaseModel):
    features: Features = Field(default_factory=Features)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    patterns: Patterns = Field(default_factory=Patterns)
    audit: AuditSettings = Field(default_factory=AuditSettings)


def _read(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_inventory(path: str | Path) -> Inventory:
    return Inventory.model_validate(_read(Path(path)))


def load_owners(path: str | Path) -> OwnersDirectory:
    data = _read(Path(path))
    return OwnersDirectory(domains=[DomainOwners.model_validate(d) for d in (data or [])])


def load_settings(path: str | Path | None) -> Settings:
    if path is None or not Path(path).exists():
        return Settings()
    return Settings.model_validate(_read(Path(path)))
