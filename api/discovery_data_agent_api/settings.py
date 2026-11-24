"""Ajustes de la API leídos de variables de entorno (`.env` en desarrollo, `docker-compose.yml` en contenedores)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# Raíz de la instalación (el repositorio, o /app en la imagen): lo que viaja con el código se busca aquí y no en el
# directorio de trabajo, que depende de dónde se arranque la API (`uvicorn --app-dir api` desde la raíz, o desde `api/`).
INSTALL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEMO_FIXTURES = (INSTALL_ROOT / "tests" / "fixtures" / "vbank", INSTALL_ROOT / "tests" / "fixtures" / "bancos")
DEFAULT_DOCS_DIR = INSTALL_ROOT / "docs"


def _installed(value: str) -> Path:
    """Ruta de un archivo de la instalación: si es relativa, respecto a `INSTALL_ROOT`, no al directorio de trabajo."""
    path = Path(value)
    return path if path.is_absolute() else INSTALL_ROOT / path


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
    # Cadena ODBC de la BD `DiscoveryDataAgent` (OP-02). Con ella la auditoría va al esquema `audit`; sin ella, a archivos (solo dev).
    db: str | None = field(default=None, repr=False)  # puede llevar credenciales en desarrollo: nunca en un repr
    curation_dir: Path = Path("data/curation")
    log_dir: Path | None = None  # logs JSON rotados sin contenido (HU-21, OP-05); None = sin archivo
    event_log: bool = True  # además, errores al Visor de eventos de Windows (origen DiscoveryDataAgent)
    models_path: Path | None = None  # config/models.yaml; sin él, modo determinista
    admins: frozenset[str] = field(default_factory=frozenset)  # logins con rol admin además de sysadmin/VIEW ANY DEFINITION
    session_ttl_s: int = 8 * 3600  # OP-03: 8 h con expiración deslizante
    cookie_secure: bool = False
    allow_windows_auth: bool = False  # solo fuera de contenedores: Trusted_Connection con la cuenta del proceso
    figures_daily_limit: int = 300  # consultas de cifras por usuario y día (cada cifra son de 1 a 3); 0 = sin tope
    ask_flow: bool = False  # cifras agregadas con los permisos del usuario (DISCOVERY_DATA_AGENT_ASK_FLOW); apagado por defecto
    ask_llm_sql: bool = False  # fase 1b: SQL de un LLM cuando la plantilla no basta (DISCOVERY_DATA_AGENT_ASK_LLM_SQL); apagado
    demo: bool = False  # servidores simulados con los metadatos de los fixtures; nunca en producción
    demo_fixtures: list[Path] = field(default_factory=lambda: list(DEFAULT_DEMO_FIXTURES))
    demo_preload_inventory: bool = True  # demo: el inventario arranca con los servidores de los fixtures
    demo_history: bool = False  # demo: siembra 30 días de actividad simulada (marcada) tras el primer build
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_per_minute: int = 30  # OP-04: preguntas por minuto y usuario
    notify_webhook: str | None = None  # F24: webhook de Teams para dudas escaladas (solo dominio y enlace)
    token_limit_mode: Literal["reject", "deterministic"] = "reject"  # al agotar el tope: rechazar o responder sin LLM
    token_limit_daily: int = 0  # tope diario de tokens de LLM por usuario (HU-19); 0 = sin tope
    public_url: str = ""  # URL del sitio para los enlaces de las notificaciones
    mcp_enabled: bool = True  # `/mcp` (F12): herramientas de descubrimiento para Claude Code y otros clientes MCP
    mcp_allowed_hosts: list[str] = field(default_factory=list)  # Host del servidor (p. ej. discovery_data_agent.banco.local:443)
    mcp_allowed_origins: list[str] = field(default_factory=list)
    # --- endurecimiento (security.py) ---
    environment: str = "dev"  # DISCOVERY_DATA_AGENT_ENV: local | dev | qa | prod (la misma variable del gateway de LLM)
    # Primer arranque: con el inventario vacío, quien registre el primer servidor debe presentar este secreto.
    setup_token: str | None = None
    admins_only: bool = False  # `data_admin` solo para los logins de `admins`, no para cualquier sysadmin de un servidor
    visibility_ttl_s: int = 900  # F14: los permisos del usuario se vuelven a leer de SQL Server cada 15 min
    session_max_age_s: int = 12 * 3600  # vida máxima de una sesión aunque siga activa
    max_sessions_per_user: int = 5  # al superarlo se cierra la sesión más antigua del usuario
    login_max_failures: int = 5  # fallos por login en la ventana antes de bloquearlo; 0 = sin bloqueo
    login_ip_max_failures: int = 30  # fallos por origen (cualquier login); mayor porque un proxy comparte IP
    login_window_s: int = 600  # F14: 5 fallos en 10 minutos
    login_lockout_s: int = 900
    trust_proxy: bool = False  # tomar el origen de X-Forwarded-For (solo detrás de un proxy inverso propio)
    max_body_bytes: int = 4 * 1024 * 1024  # el diccionario CSV admite 2 MB de texto
    # Documentación que la web muestra solo a `data_admin` (describe controles y sus puntos débiles): de esta carpeta se
    # sirven únicamente el manual, la wiki y la arquitectura (`documentation.py`).
    docs_dir: Path = DEFAULT_DOCS_DIR

    @property
    def production(self) -> bool:
        """qa y prod manejan datos reales: la API se niega a arrancar con ajustes inseguros (`production_violations`)."""
        return self.environment.strip().lower() in ("qa", "prod")

    @classmethod
    def from_env(cls) -> "ApiSettings":
        models = os.environ.get("DISCOVERY_DATA_AGENT_MODELS")
        return cls(
            data_root=Path(os.environ.get("DISCOVERY_DATA_AGENT_DATA_ROOT", "data/catalog")),
            inventory_path=Path(os.environ.get("DISCOVERY_DATA_AGENT_INVENTORY", "data/inventory.yaml")),
            audit_dir=Path(os.environ.get("DISCOVERY_DATA_AGENT_AUDIT_DIR", "data/audit")),
            db=os.environ.get("DISCOVERY_DATA_AGENT_DB", "").strip() or None,
            curation_dir=Path(os.environ.get("DISCOVERY_DATA_AGENT_CURATION_DIR", "data/curation")),
            log_dir=Path(os.environ.get("DISCOVERY_DATA_AGENT_LOG_DIR", "data/logs")),
            event_log=_flag("DISCOVERY_DATA_AGENT_EVENT_LOG", True),
            models_path=Path(models) if models and Path(models).is_file() else None,
            admins=frozenset(a.strip().lower() for a in os.environ.get("DISCOVERY_DATA_AGENT_ADMINS", "").split(",") if a.strip()),
            session_ttl_s=int(os.environ.get("DISCOVERY_DATA_AGENT_SESSION_TTL_S", 8 * 3600)),
            cookie_secure=_flag("DISCOVERY_DATA_AGENT_COOKIE_SECURE"),
            # Apagado por defecto: usa la cuenta del proceso, no la de quien llama (solo para desarrollo local).
            allow_windows_auth=_flag("DISCOVERY_DATA_AGENT_ALLOW_WINDOWS_AUTH"),
            ask_flow=_flag("DISCOVERY_DATA_AGENT_ASK_FLOW"),
            ask_llm_sql=_flag("DISCOVERY_DATA_AGENT_ASK_LLM_SQL"),
            figures_daily_limit=int(os.environ.get("DISCOVERY_DATA_AGENT_FIGURES_DAILY_LIMIT", 300)),
            demo=_flag("DISCOVERY_DATA_AGENT_DEMO"),
            demo_fixtures=[_installed(p.strip()) for p in os.environ.get("DISCOVERY_DATA_AGENT_DEMO_FIXTURE", ",".join(
                str(f) for f in DEFAULT_DEMO_FIXTURES)).split(",") if p.strip()],
            demo_preload_inventory=_flag("DISCOVERY_DATA_AGENT_DEMO_PRELOAD", True),
            demo_history=_flag("DISCOVERY_DATA_AGENT_DEMO_HISTORY", True),
            cors_origins=[o.strip() for o in os.environ.get("DISCOVERY_DATA_AGENT_CORS_ORIGINS", "http://localhost:3000").split(",")
                          if o.strip()],
            rate_limit_per_minute=int(os.environ.get("DISCOVERY_DATA_AGENT_RATE_LIMIT", 30)),
            notify_webhook=os.environ.get("DISCOVERY_DATA_AGENT_NOTIFY_WEBHOOK") or None,
            public_url=os.environ.get("DISCOVERY_DATA_AGENT_PUBLIC_URL", ""),
            token_limit_daily=int(os.environ.get("DISCOVERY_DATA_AGENT_TOKEN_LIMIT", 0)),
            token_limit_mode="deterministic" if os.environ.get("DISCOVERY_DATA_AGENT_TOKEN_LIMIT_MODE", "").strip().lower() == "deterministic" else "reject",
            mcp_enabled=_flag("DISCOVERY_DATA_AGENT_MCP", True),
            mcp_allowed_hosts=[h.strip() for h in os.environ.get("DISCOVERY_DATA_AGENT_MCP_HOSTS", "").split(",") if h.strip()],
            mcp_allowed_origins=[o.strip() for o in os.environ.get("DISCOVERY_DATA_AGENT_MCP_ORIGINS", "").split(",") if o.strip()],
            environment=os.environ.get("DISCOVERY_DATA_AGENT_ENV", "dev"),
            setup_token=os.environ.get("DISCOVERY_DATA_AGENT_SETUP_TOKEN") or None,
            admins_only=_flag("DISCOVERY_DATA_AGENT_ADMINS_ONLY"),
            visibility_ttl_s=int(os.environ.get("DISCOVERY_DATA_AGENT_VISIBILITY_TTL_S", 900)),
            session_max_age_s=int(os.environ.get("DISCOVERY_DATA_AGENT_SESSION_MAX_AGE_S", 12 * 3600)),
            max_sessions_per_user=int(os.environ.get("DISCOVERY_DATA_AGENT_MAX_SESSIONS", 5)),
            login_max_failures=int(os.environ.get("DISCOVERY_DATA_AGENT_LOGIN_MAX_FAILURES", 5)),
            login_ip_max_failures=int(os.environ.get("DISCOVERY_DATA_AGENT_LOGIN_IP_MAX_FAILURES", 30)),
            login_window_s=int(os.environ.get("DISCOVERY_DATA_AGENT_LOGIN_WINDOW_S", 600)),
            login_lockout_s=int(os.environ.get("DISCOVERY_DATA_AGENT_LOGIN_LOCKOUT_S", 900)),
            trust_proxy=_flag("DISCOVERY_DATA_AGENT_TRUST_PROXY"),
            max_body_bytes=int(os.environ.get("DISCOVERY_DATA_AGENT_MAX_BODY_BYTES", 4 * 1024 * 1024)),
            docs_dir=_installed(os.environ.get("DISCOVERY_DATA_AGENT_DOCS", "").strip() or str(DEFAULT_DOCS_DIR)),
        )
