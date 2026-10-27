"""Ajustes de la API leídos de variables de entorno (`.env` en desarrollo, `docker-compose.yml` en contenedores)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


DEFAULT_DEMO_FIXTURES = (Path("tests/fixtures/vbank"), Path("tests/fixtures/bancos"))


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "si", "sí")


@dataclass
class ApiSettings:
    # Directorio que escribe el CatalogBuildFlow y carga el DiscoverFlow (config/, catalog/, knowledge/).
    data_root: Path = Path("data/catalog")
    # Inventario de servidores con hosts (no se copia al catálogo). Si no existe, el primer login lo crea.
    inventory_path: Path = Path("data/inventory.yaml")
    audit_dir: Path = Path("data/audit")
    curation_dir: Path = Path("data/curation")
    log_dir: Path | None = None  # logs JSON rotados sin contenido (HU-21, OP-05); None = sin archivo
    event_log: bool = True  # además, errores al Visor de eventos de Windows (origen ConverData)
    models_path: Path | None = None  # config/models.yaml; sin él, modo determinista
    embeddings_only: bool = False
    admins: frozenset[str] = field(default_factory=frozenset)  # logins con rol admin además de sysadmin/VIEW ANY DEFINITION
    session_ttl_s: int = 8 * 3600  # OP-03: 8 h con expiración deslizante
    cookie_secure: bool = False
    allow_windows_auth: bool = False  # solo fuera de contenedores: Trusted_Connection con la cuenta del proceso
    demo: bool = False  # servidores simulados con los metadatos de los fixtures; nunca en producción
    demo_fixtures: list[Path] = field(default_factory=lambda: list(DEFAULT_DEMO_FIXTURES))
    demo_preload_inventory: bool = True  # demo: el inventario arranca con los servidores de los fixtures
    demo_history: bool = False  # demo: siembra 30 días de actividad simulada (marcada) tras el primer build
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_per_minute: int = 30  # OP-04: preguntas por minuto y sesión
    notify_webhook: str | None = None  # F24: webhook de Teams para dudas escaladas (solo dominio y enlace)
    token_limit_mode: Literal["reject", "deterministic"] = "reject"  # al agotar el tope: rechazar o responder sin LLM
    token_limit_daily: int = 0  # tope diario de tokens de LLM por usuario (HU-19); 0 = sin tope
    public_url: str = ""  # URL del sitio para los enlaces de las notificaciones
    mcp_enabled: bool = True  # `/mcp` (F12): herramientas de descubrimiento para Claude Code y otros clientes MCP
    mcp_allowed_hosts: list[str] = field(default_factory=list)  # Host del servidor (p. ej. converdata.banco.local:443)
    mcp_allowed_origins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "ApiSettings":
        models = os.environ.get("CONVERDATA_MODELS")
        return cls(
            data_root=Path(os.environ.get("CONVERDATA_DATA_ROOT", "data/catalog")),
            inventory_path=Path(os.environ.get("CONVERDATA_INVENTORY", "data/inventory.yaml")),
            audit_dir=Path(os.environ.get("CONVERDATA_AUDIT_DIR", "data/audit")),
            curation_dir=Path(os.environ.get("CONVERDATA_CURATION_DIR", "data/curation")),
            log_dir=Path(os.environ.get("CONVERDATA_LOG_DIR", "data/logs")),
            event_log=_flag("CONVERDATA_EVENT_LOG", True),
            models_path=Path(models) if models and Path(models).is_file() else None,
            embeddings_only=_flag("CONVERDATA_EMBEDDINGS_ONLY"),
            admins=frozenset(a.strip().lower() for a in os.environ.get("CONVERDATA_ADMINS", "").split(",") if a.strip()),
            session_ttl_s=int(os.environ.get("CONVERDATA_SESSION_TTL_S", 8 * 3600)),
            cookie_secure=_flag("CONVERDATA_COOKIE_SECURE"),
            allow_windows_auth=_flag("CONVERDATA_ALLOW_WINDOWS_AUTH", os.name == "nt"),
            demo=_flag("CONVERDATA_DEMO"),
            demo_fixtures=[Path(p.strip()) for p in os.environ.get("CONVERDATA_DEMO_FIXTURE", ",".join(
                str(f) for f in DEFAULT_DEMO_FIXTURES)).split(",") if p.strip()],
            demo_preload_inventory=_flag("CONVERDATA_DEMO_PRELOAD", True),
            demo_history=_flag("CONVERDATA_DEMO_HISTORY", True),
            cors_origins=[o.strip() for o in os.environ.get("CONVERDATA_CORS_ORIGINS", "http://localhost:3000").split(",")
                          if o.strip()],
            rate_limit_per_minute=int(os.environ.get("CONVERDATA_RATE_LIMIT", 30)),
            notify_webhook=os.environ.get("CONVERDATA_NOTIFY_WEBHOOK") or None,
            public_url=os.environ.get("CONVERDATA_PUBLIC_URL", ""),
            token_limit_daily=int(os.environ.get("CONVERDATA_TOKEN_LIMIT", 0)),
            token_limit_mode="deterministic" if os.environ.get("CONVERDATA_TOKEN_LIMIT_MODE", "").strip().lower() == "deterministic" else "reject",
            mcp_enabled=_flag("CONVERDATA_MCP", True),
            mcp_allowed_hosts=[h.strip() for h in os.environ.get("CONVERDATA_MCP_HOSTS", "").split(",") if h.strip()],
            mcp_allowed_origins=[o.strip() for o in os.environ.get("CONVERDATA_MCP_ORIGINS", "").split(",") if o.strip()],
        )
