"""Configuración de modelos (`config/models.yaml`, F16) y constructores por proveedor.

Proveedores:
- ``nvidia_nim``: NVIDIA NIM vía `langchain-nvidia-ai-endpoints` (API alojada de NVIDIA o NIM autoalojado en la red del banco).
- ``bedrock``: Amazon Bedrock vía `langchain-aws` (Converse). Se activa cambiando solo este archivo.
- ``openai``: API de OpenAI vía `langchain-openai`; con `base_url` sirve cualquier servidor compatible.
- ``anthropic``: Claude por la API de Anthropic, con su SDK oficial (`converdata.llm.anthropic_chat`).
- ``ollama``: modelos locales vía `langchain-ollama`, **solo con `environment: local`** (la máquina del desarrollador).

Los imports de cada SDK son perezosos: solo se carga el del proveedor que se usa.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

Provider = Literal["nvidia_nim", "bedrock", "openai", "anthropic", "ollama"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
DataClass = Literal["test", "real"]
Environment = Literal["local", "dev", "qa", "prod"]

# Proveedores que solo pueden usarse en la máquina del desarrollador. Es una regla de código, no de configuración.
LOCAL_ONLY_PROVIDERS = {"ollama"}
ENV_VAR = "CONVERDATA_ENV"  # sobrescribe `environment` del archivo (el servidor fija dev/qa/prod)
RETIRED_ROLES = frozenset({"embed"})  # roles que ya no existen: se ignoran al cargar la configuración


class ProviderConfig(BaseModel):
    enabled: bool = True
    # NIM: None = API alojada de NVIDIA (https://integrate.api.nvidia.com/v1); http://<host>:8000/v1 = NIM autoalojado.
    base_url: str | None = None
    api_key_env: str | None = None  # variable de entorno con la clave (on-premise: se cargará desde DPAPI)
    region: str | None = None  # Bedrock
    # Qué datos puede recibir (F16, F17, OP-06): la API alojada de NVIDIA solo datos de prueba; Bedrock sin
    # invocation logging, o un NIM autoalojado en la red del banco, pueden recibir datos reales.
    allowed_data: DataClass = "test"
    timeout_s: float = 30.0


class RoleConfig(BaseModel):
    provider: Provider
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning: bool = False  # F16: modelos con razonamiento extendido se usan con él desactivado
    num_ctx: int | None = None  # Ollama: ventana de contexto
    # OpenAI (`reasoning_effort`) y Claude (`output_config.effort`): cuánto razona el modelo. Los niveles válidos
    # dependen del modelo; None = el valor por defecto del proveedor.
    effort: Effort | None = None
    # Claude: ante un rechazo por política, la API repite la petición en otro modelo de Claude (beta). Solo lo
    # admiten algunos modelos (Opus 5.5, Sonnet 5.5, Fable); con otro la petición falla.
    refusal_fallback: bool = False


class FallbackConfig(BaseModel):
    provider: Provider
    on: list[Literal["throttling", "service_unavailable", "timeout"]] = Field(
        default_factory=lambda: ["throttling", "service_unavailable", "timeout"]
    )
    models: dict[str, str] = Field(default_factory=dict)  # rol → modelo en el proveedor de respaldo


class CircuitConfig(BaseModel):
    errors: int = 3  # F16: 3 errores en 60 s abren el circuito 5 min
    window_s: float = 60.0
    open_s: float = 300.0


class ProfileConfig(BaseModel):
    """Un juego completo de roles con nombre ("NVIDIA", "Claude") que un administrador puede elegir en pantalla."""

    label: str
    description: str | None = None
    roles: dict[str, RoleConfig] = Field(default_factory=dict)


NO_MODEL = "none"  # elección "sin modelo": todo el flujo corre en modo determinista


class ModelsConfig(BaseModel):
    environment: Environment | None = None  # sin definir = no local (Ollama queda bloqueado)
    # Perfiles elegibles desde Administración → Modelos de IA. El activo sustituye a `roles`. Sin perfiles, mandan
    # los `roles` del archivo, como siempre.
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    active_profile: str | None = None
    data_mode: DataClass = "test"  # qué datos maneja este despliegue; "real" exige proveedores con allowed_data: real
    providers: dict[Provider, ProviderConfig] = Field(default_factory=dict)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    fallback: FallbackConfig | None = None
    circuit: CircuitConfig = Field(default_factory=CircuitConfig)

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_roles(cls, data):
        """Un `models.yaml` antiguo puede declarar el rol `embed`: ya no existe (la búsqueda es léxica; PRD §13,
        decisión 9). Se ignora con un aviso en lugar de romper la carga."""
        if isinstance(data, dict) and isinstance(data.get("roles"), dict) and RETIRED_ROLES & set(data["roles"]):
            retired = sorted(RETIRED_ROLES & set(data["roles"]))
            log.warning("models.yaml declara roles retirados que se ignoran: %s (la búsqueda es léxica)", ", ".join(retired))
            data = {**data, "roles": {k: v for k, v in data["roles"].items() if k not in RETIRED_ROLES}}
        return data

    def provider(self, name: str) -> ProviderConfig:
        return self.providers.get(name) or ProviderConfig()


def selection_path(path: str | Path) -> Path:
    """Dónde se guarda el perfil elegido en pantalla: junto al archivo de modelos, que no se reescribe (conserva sus
    comentarios y lo que el instalador dejó). Solo guarda el nombre de un perfil; nunca claves."""
    return Path(str(path) + ".active")


def read_selection(path: str | Path) -> str | None:
    try:
        return selection_path(path).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_selection(path: str | Path, profile: str) -> None:
    selection_path(path).write_text(profile + "\n", encoding="utf-8")


def apply_profile(config: ModelsConfig, name: str | None) -> ModelsConfig:
    """La configuración con los roles del perfil `name`. `NO_MODEL` deja el flujo sin roles (determinista). Elegir un
    perfil activa los proveedores que usa: quien lo definió en el archivo ya decidió que se puede usar. Las guardas de
    residencia (`data_mode` frente a `allowed_data`) las sigue aplicando el gateway al validar."""
    if name is None or not config.profiles:
        return config
    if name == NO_MODEL:
        return config.model_copy(update={"roles": {}, "fallback": None, "active_profile": NO_MODEL})
    if name not in config.profiles:
        raise ValueError(f"Perfil de modelos desconocido: {name!r}")
    roles = config.profiles[name].roles
    providers = dict(config.providers)
    for role in roles.values():
        providers[role.provider] = providers.get(role.provider, ProviderConfig()).model_copy(update={"enabled": True})
    return config.model_copy(update={"roles": dict(roles), "providers": providers, "active_profile": name})


def load_models(path: str | Path, apply_selection: bool = True) -> ModelsConfig:
    """`apply_selection=False` devuelve el archivo tal cual, sin aplicar el perfil activo (para listar los perfiles)."""
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if os.environ.get(ENV_VAR):
        data["environment"] = os.environ[ENV_VAR]
    config = ModelsConfig.model_validate(data)
    if not apply_selection or not config.profiles:
        return config
    chosen = read_selection(path) or config.active_profile
    if chosen not in config.profiles and chosen != NO_MODEL:
        chosen = config.active_profile if config.active_profile in config.profiles else None
    return apply_profile(config, chosen)


class MissingCredential(RuntimeError):
    pass


def _api_key(provider: ProviderConfig, default_env: str, name: str = "NVIDIA NIM") -> str | None:
    env = provider.api_key_env or default_env
    key = os.environ.get(env)
    if not key and provider.base_url is None:
        # La API alojada exige clave; un servidor autoalojado (NIM, compatible con OpenAI) puede no tenerla.
        raise MissingCredential(f"Falta la variable de entorno {env} para {name}")
    return key


# --- constructores: (rol, proveedor) → modelo de LangChain -----------------------------------------
def build_nim_chat(role: RoleConfig, provider: ProviderConfig):
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    # timeout: tope por petición HTTP (y por la espera de un 202).
    kwargs = {"model": role.model, "api_key": _api_key(provider, "NVIDIA_API_KEY"), "usage_telemetry_enabled": False,
              "timeout": provider.timeout_s}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    if role.temperature is not None:
        kwargs["temperature"] = role.temperature
    if role.max_tokens is not None:
        kwargs["max_completion_tokens"] = role.max_tokens
    return ChatNVIDIA(**kwargs)


def build_bedrock_chat(role: RoleConfig, provider: ProviderConfig):
    from langchain_aws import ChatBedrockConverse

    kwargs = {"model": role.model, "region_name": provider.region or "us-east-1"}
    if role.temperature is not None:
        kwargs["temperature"] = role.temperature
    if role.max_tokens is not None:
        kwargs["max_tokens"] = role.max_tokens
    return ChatBedrockConverse(**kwargs)


OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com"


def build_openai_chat(role: RoleConfig, provider: ProviderConfig):
    from langchain_openai import ChatOpenAI

    key = _api_key(provider, "OPENAI_API_KEY", "OpenAI")
    if not key and provider.api_key_env:
        raise MissingCredential(f"Falta la variable de entorno {provider.api_key_env} para OpenAI")
    # Un servidor compatible sin autenticación no tiene clave, pero el SDK exige un valor. `base_url` va siempre
    # explícita: así una variable OPENAI_BASE_URL del entorno no desvía las peticiones a otro host.
    kwargs = {"model": role.model, "api_key": key or "sin-clave", "base_url": provider.base_url or OPENAI_URL,
              "timeout": provider.timeout_s, "max_retries": 1}
    if role.temperature is not None:  # los modelos de razonamiento de OpenAI solo admiten el valor por defecto
        kwargs["temperature"] = role.temperature
    if role.max_tokens is not None:
        kwargs["max_completion_tokens"] = role.max_tokens
    if role.effort is not None:
        kwargs["reasoning_effort"] = role.effort
    return ChatOpenAI(**kwargs)


def build_anthropic_chat(role: RoleConfig, provider: ProviderConfig):
    import anthropic

    from converdata.llm.anthropic_chat import ClaudeChat

    # `base_url` explícita: una variable ANTHROPIC_BASE_URL del entorno no desvía las peticiones a otro host.
    kwargs = {"timeout": provider.timeout_s, "max_retries": 1, "base_url": provider.base_url or ANTHROPIC_URL}
    if provider.api_key_env:
        key = os.environ.get(provider.api_key_env)
        if not key:
            raise MissingCredential(f"Falta la variable de entorno {provider.api_key_env} para Anthropic")
        kwargs["api_key"] = key
    # Sin `api_key_env`, el SDK resuelve la credencial: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN o un perfil.
    # `temperature` no se envía: los modelos actuales de Claude la rechazan.
    return ClaudeChat(anthropic.Anthropic(**kwargs), role.model, role.max_tokens, role.effort, role.refusal_fallback)


OLLAMA_URL = "http://localhost:11434"


def build_ollama_chat(role: RoleConfig, provider: ProviderConfig):
    from langchain_ollama import ChatOllama

    kwargs = {"model": role.model, "base_url": provider.base_url or OLLAMA_URL, "reasoning": role.reasoning}
    if role.temperature is not None:
        kwargs["temperature"] = role.temperature
    if role.max_tokens is not None:
        kwargs["num_predict"] = role.max_tokens
    if role.num_ctx is not None:
        kwargs["num_ctx"] = role.num_ctx
    return ChatOllama(**kwargs)


BUILDERS = {
    ("nvidia_nim", "chat"): build_nim_chat,
    ("bedrock", "chat"): build_bedrock_chat,
    ("openai", "chat"): build_openai_chat,
    ("anthropic", "chat"): build_anthropic_chat,
    ("ollama", "chat"): build_ollama_chat,
}
