"""Configuración de modelos (`config/models.yaml`, F16) y constructores por proveedor.

Proveedores:
- ``nvidia_nim``: NVIDIA NIM vía `langchain-nvidia-ai-endpoints` (API alojada de NVIDIA o NIM autoalojado en la red del banco).
- ``bedrock``: Amazon Bedrock vía `langchain-aws` (Converse). Se activa cambiando solo este archivo.
- ``ollama``: modelos locales vía `langchain-ollama`, **solo con `environment: local`** (la máquina del desarrollador).

Los imports de cada SDK son perezosos: solo se carga el del proveedor que se usa.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Provider = Literal["nvidia_nim", "bedrock", "ollama"]
DataClass = Literal["test", "real"]
Environment = Literal["local", "dev", "qa", "prod"]

# Proveedores que solo pueden usarse en la máquina del desarrollador. Es una regla de código, no de configuración.
LOCAL_ONLY_PROVIDERS = {"ollama"}
ENV_VAR = "CONVERDATA_ENV"  # sobrescribe `environment` del archivo (el servidor fija dev/qa/prod)


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
    dimensions: int | None = None  # solo `embed`: debe coincidir con VECTOR(n) de la BD ConverData
    reasoning: bool = False  # F16: modelos con razonamiento extendido se usan con él desactivado
    num_ctx: int | None = None  # Ollama: ventana de contexto


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


class ModelsConfig(BaseModel):
    environment: Environment | None = None  # sin definir = no local (Ollama queda bloqueado)
    data_mode: DataClass = "test"  # qué datos maneja este despliegue; "real" exige proveedores con allowed_data: real
    providers: dict[Provider, ProviderConfig] = Field(default_factory=dict)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    fallback: FallbackConfig | None = None
    circuit: CircuitConfig = Field(default_factory=CircuitConfig)

    def provider(self, name: str) -> ProviderConfig:
        return self.providers.get(name) or ProviderConfig()


def load_models(path: str | Path) -> ModelsConfig:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if os.environ.get(ENV_VAR):
        data["environment"] = os.environ[ENV_VAR]
    return ModelsConfig.model_validate(data)


class MissingCredential(RuntimeError):
    pass


def _api_key(provider: ProviderConfig, default_env: str) -> str | None:
    env = provider.api_key_env or default_env
    key = os.environ.get(env)
    if not key and provider.base_url is None:
        # La API alojada exige clave; un NIM autoalojado puede no tenerla.
        raise MissingCredential(f"Falta la variable de entorno {env} para NVIDIA NIM")
    return key


# --- constructores: (rol, proveedor) → modelo de LangChain -----------------------------------------
def build_nim_chat(role: RoleConfig, provider: ProviderConfig):
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    kwargs = {"model": role.model, "api_key": _api_key(provider, "NVIDIA_API_KEY"), "usage_telemetry_enabled": False}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    if role.temperature is not None:
        kwargs["temperature"] = role.temperature
    if role.max_tokens is not None:
        kwargs["max_completion_tokens"] = role.max_tokens
    return ChatNVIDIA(**kwargs)


def build_nim_embeddings(role: RoleConfig, provider: ProviderConfig):
    from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

    kwargs = {"model": role.model, "api_key": _api_key(provider, "NVIDIA_API_KEY"), "truncate": "END",
              "usage_telemetry_enabled": False}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    if role.dimensions:
        kwargs["dimensions"] = role.dimensions
    return NVIDIAEmbeddings(**kwargs)


def build_bedrock_chat(role: RoleConfig, provider: ProviderConfig):
    from langchain_aws import ChatBedrockConverse

    kwargs = {"model": role.model, "region_name": provider.region or "us-east-1"}
    if role.temperature is not None:
        kwargs["temperature"] = role.temperature
    if role.max_tokens is not None:
        kwargs["max_tokens"] = role.max_tokens
    return ChatBedrockConverse(**kwargs)


def build_bedrock_embeddings(role: RoleConfig, provider: ProviderConfig):
    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(model_id=role.model, region_name=provider.region or "us-east-1")


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


def build_ollama_embeddings(role: RoleConfig, provider: ProviderConfig):
    from langchain_ollama import OllamaEmbeddings

    kwargs = {"model": role.model, "base_url": provider.base_url or OLLAMA_URL}
    if role.dimensions:
        kwargs["dimensions"] = role.dimensions
    return OllamaEmbeddings(**kwargs)


BUILDERS = {
    ("nvidia_nim", "chat"): build_nim_chat,
    ("nvidia_nim", "embed"): build_nim_embeddings,
    ("bedrock", "chat"): build_bedrock_chat,
    ("bedrock", "embed"): build_bedrock_embeddings,
    ("ollama", "chat"): build_ollama_chat,
    ("ollama", "embed"): build_ollama_embeddings,
}
