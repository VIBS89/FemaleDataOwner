"""Ensambla el DiscoverFlow a partir de un directorio con `config/`, `catalog/` y `knowledge/`.

On-premise, `ConverData-API` lo hará leyendo los esquemas de la BD `ConverData` y con `SqlServerVectorStore` (OP-02);
la forma de ensamblar es la misma.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from converdata.audit.recorder import AuditSink
from converdata.audit.sqlserver import SqlServerAuditSink
from converdata.catalog.files import FileCatalogStore
from converdata.catalog.ports import CatalogStore
from converdata.config import Settings, load_inventory, load_owners, load_settings
from converdata.flows.discover import DiscoverDeps, DiscoverService
from converdata.memory.memory_store import InMemoryVectorStore
from converdata.models.identity import UserContext


class ConfiguracionInvalida(ValueError):
    """La configuración de adaptadores no es válida; el mensaje nombra la variable que hay que corregir."""


ALMACENES = ("files", "sqlserver")
ENTORNOS = ("dev", "qa", "prod")
FUERA_DE_DEV = ("qa", "prod")
PROVEEDORES_SOLO_DEV = ("ollama", "nvidia_nim")  # F16, OP-09: no se usan en qa ni prod
_VERDADERO = ("1", "true", "yes", "si", "sí")
_CONTRASENA_EN_CADENA = re.compile(r"(^|;)\s*(pwd|password)\s*=", re.IGNORECASE)


@dataclass(frozen=True)
class AdapterConfig:
    """Qué adaptadores usa el servicio, decidido solo por variables de entorno (OP-09 §Selección de adaptadores).

    No guarda la contraseña de la BD: `connection_string` la lee de `CONVERDATA_DB_PASSWORD` en el momento de conectar."""

    store: str = "files"
    audit: str = "files"
    db: str | None = None
    models: Path | None = None
    env: str = "dev"
    demo: bool = field(default=False, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str], settings: Settings | None = None) -> AdapterConfig:
        env = _elegir(environ, "CONVERDATA_ENV", ENTORNOS + ("local",), "dev")
        env = "dev" if env == "local" else env  # `local` es la máquina del desarrollador (F16): mismo régimen que dev
        store = _elegir(environ, "CONVERDATA_STORE", ALMACENES, "files")
        audit = _elegir(environ, "CONVERDATA_AUDIT", ALMACENES, store)
        db = (environ.get("CONVERDATA_DB") or "").strip() or None
        models = (environ.get("CONVERDATA_MODELS") or "").strip() or None
        demo = environ.get("CONVERDATA_DEMO", "").strip().lower() in _VERDADERO

        if "sqlserver" in (store, audit) and db is None:
            raise ConfiguracionInvalida("CONVERDATA_DB: falta la cadena ODBC de la BD ConverData (hay adaptadores sqlserver)")
        if db and _CONTRASENA_EN_CADENA.search(db):
            raise ConfiguracionInvalida(
                "CONVERDATA_DB: no puede llevar la contraseña; defínala en CONVERDATA_DB_PASSWORD o use autenticación integrada"
            )
        if models and not Path(models).is_file():
            raise ConfiguracionInvalida(f"CONVERDATA_MODELS: no existe el archivo {models}")

        if env in FUERA_DE_DEV:
            for nombre, valor in (("CONVERDATA_STORE", store), ("CONVERDATA_AUDIT", audit)):
                if valor == "files":
                    raise ConfiguracionInvalida(f"{nombre}=files no se permite con CONVERDATA_ENV={env}; use sqlserver")
            if demo:
                raise ConfiguracionInvalida(f"CONVERDATA_DEMO=1 no se permite con CONVERDATA_ENV={env}")
            if models:
                prohibidos = sorted(_proveedores(Path(models)) & set(PROVEEDORES_SOLO_DEV))
                if prohibidos:
                    raise ConfiguracionInvalida(
                        f"CONVERDATA_MODELS usa {', '.join(prohibidos)}, que no se permite con CONVERDATA_ENV={env}; use bedrock"
                    )
            if settings is not None and settings.audit.fail_open:
                raise ConfiguracionInvalida(f"settings.yaml audit.fail_open: true no se permite con CONVERDATA_ENV={env} (F11)")
        return cls(store=store, audit=audit, db=db, models=Path(models) if models else None, env=env, demo=demo)

    def connection_string(self, environ: Mapping[str, str]) -> str:
        """Cadena ODBC final; la contraseña (login SQL de desarrollo) viene de `CONVERDATA_DB_PASSWORD`."""
        if self.db is None:
            raise ConfiguracionInvalida("CONVERDATA_DB: no hay cadena de conexión configurada")
        password = environ.get("CONVERDATA_DB_PASSWORD")
        return f"{self.db.rstrip(';')};PWD={password}" if password else self.db


def _elegir(environ: Mapping[str, str], variable: str, validos: tuple[str, ...], por_defecto: str) -> str:
    valor = (environ.get(variable) or por_defecto).strip().lower()
    if valor not in validos:
        raise ConfiguracionInvalida(f"{variable}: '{valor}' no es válido; use {' | '.join(v for v in validos if v != 'local')}")
    return valor


def _proveedores(models_path: Path) -> set[str]:
    data = yaml.safe_load(models_path.read_text(encoding="utf-8")) or {}
    usados = {r.get("provider") for r in (data.get("roles") or {}).values() if isinstance(r, dict)}
    respaldo = data.get("fallback")
    if isinstance(respaldo, dict):
        usados.add(respaldo.get("provider"))
    return {p for p in usados if p}


def resolve_catalog_store(config: AdapterConfig, root: str | Path) -> CatalogStore:
    if config.store == "files":
        return FileCatalogStore(root)
    raise ConfiguracionInvalida(
        "adaptador no disponible: CONVERDATA_STORE=sqlserver para el catálogo llega con HU-06; use files mientras tanto"
    )


def resolve_audit_sink(config: AdapterConfig, connect: Callable[[], object]) -> AuditSink | None:
    """`None` con `files`: la auditoría en archivos la compone la integración (`api/converdata_api/audit.py`)."""
    return SqlServerAuditSink(connect) if config.audit == "sqlserver" else None


def build_service(
    root: str | Path, *, models_path: str | Path | None = None, gateway=None, llm_nodes: bool = True,
    embedder_override=None, store: CatalogStore | None = None, **overrides
) -> DiscoverService:
    """Sin `models_path` ni `gateway`, modo determinista. Con ellos, los nodos `intent`, `rerank` y `respond` y los
    embeddings pasan por el gateway de LLM (NVIDIA NIM o Bedrock según `config/models.yaml`)."""
    root = Path(root)
    inventory = load_inventory(root / "config" / "databases.yaml")
    catalog_store = store or FileCatalogStore(root)
    catalog = catalog_store.load_catalog(inventory)
    knowledge = catalog_store.load_knowledge()
    owners = load_owners(root / "config" / "owners.yaml")
    settings = load_settings(root / "config" / "settings.yaml")

    embedder, embed_model = None, None
    llm_ports: dict = {}
    model_names = {}
    if models_path and gateway is None:
        from converdata.llm.gateway import LLMGateway

        gateway = LLMGateway.from_file(models_path)
    if gateway is not None:
        from converdata.llm.nodes import LlmIntentClassifier, LlmNarrator, LlmReranker

        if llm_nodes and gateway.has_role("planner"):
            llm_ports["intent_classifier"] = LlmIntentClassifier(gateway.chat("planner"))
            llm_ports["reranker"] = LlmReranker(gateway.chat("planner"))
        if llm_nodes and gateway.has_role("fast"):
            llm_ports["narrator"] = LlmNarrator(gateway.chat("fast"))
        embedder, embed_model = gateway.embeddings(), gateway.embed_model
        model_names = gateway.labels  # vista viva: proveedor:modelo que atendió cada rol (audit_step.model)

    if embedder_override is not None:  # tests y evaluaciones con un embedder propio
        embedder, embed_model = embedder_override, type(embedder_override).__name__
    vector_store = InMemoryVectorStore(embedder=embedder, embed_model=embed_model)
    vector_store.index_catalog(catalog)
    vector_store.index_knowledge(knowledge.all_items(), knowledge.golden)
    deps = DiscoverDeps(
        catalog=catalog, knowledge=knowledge, store=vector_store, owners=owners, settings=settings,
        model_names=model_names, **{**llm_ports, **overrides},
    )
    return DiscoverService(deps)


def user_with_databases(service: DiscoverService, user_id: str, databases: list[str] | None, groups=None) -> UserContext:
    """Identidad de desarrollo: visibilidad sobre las BDs indicadas (todas si `None`).

    En producción `visible_ids` lo calcula `VisibilityResolver` con el login SQL del usuario (F14)."""
    ids = frozenset(
        o.id for o in service.deps.catalog.objects if databases is None or o.database in databases
    )
    return UserContext(user_id=user_id, groups=list(groups or []), visible_ids=ids)
