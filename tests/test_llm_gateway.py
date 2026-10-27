"""Gateway de LLM (F16): enrutamiento por rol, respaldo, circuit breaker, guarda de residencia y auditoría."""

import pytest
from pydantic import BaseModel

from converdata.bootstrap import build_service, user_with_databases
from converdata.llm.factory import ModelsConfig
from converdata.llm.gateway import (
    AllProvidersFailed,
    GatewayConfigError,
    LLMGateway,
    ResidencyError,
    classify_error,
)
from converdata.models.intent import IntentResult
from conftest import FIXTURE, ONBOARDING_Q


class FakeModel:
    """Chat model falso: registra llamadas y responde o falla según el guion del proveedor."""

    def __init__(self, provider, model, script, calls, schema=None):
        self.provider, self.model, self.script, self.calls, self.schema = provider, model, script, calls, schema

    def with_structured_output(self, schema, **kwargs):
        return FakeModel(self.provider, self.model, self.script, self.calls, schema)

    def invoke(self, messages, **kwargs):
        self.calls.append(f"{self.provider}:{self.model}")
        step = self.script[self.provider].pop(0) if self.script[self.provider] else "ok"
        if isinstance(step, Exception):
            raise step
        if self.schema is IntentResult:
            return IntentResult(intent="discovery", rewritten_question=ONBOARDING_Q, business_context="onboarding digital",
                                asset_kind_hint="column", confidence=0.95)
        if self.schema is not None:
            return self.schema.model_validate({"ok": True})
        return type("Msg", (), {"content": f"respuesta de {self.provider}"})()


class FakeEmbeddings:
    def __init__(self, dim):
        self.dim = dim

    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text):
        return [float(len(text) % 7 + 1)] * self.dim


def make_gateway(config: dict, script=None, clock=None):
    script = {"nvidia_nim": [], "bedrock": [], **(script or {})}
    calls: list[str] = []

    def chat_builder(provider):
        return lambda role, prov: FakeModel(provider, role.model, script, calls)

    builders = {
        ("nvidia_nim", "chat"): chat_builder("nvidia_nim"),
        ("bedrock", "chat"): chat_builder("bedrock"),
        ("nvidia_nim", "embed"): lambda role, prov: FakeEmbeddings(role.dimensions or 8),
        ("bedrock", "embed"): lambda role, prov: FakeEmbeddings(1024),
    }
    kwargs = {"clock": clock} if clock else {}
    return LLMGateway(ModelsConfig.model_validate(config), builders=builders, **kwargs), calls


NIM_ONLY = {
    "data_mode": "test",
    "providers": {"nvidia_nim": {"allowed_data": "test"}, "bedrock": {"enabled": False}},
    "roles": {
        "planner": {"provider": "nvidia_nim", "model": "meta/llama-3.3-70b-instruct"},
        "fast": {"provider": "nvidia_nim", "model": "meta/llama-3.1-8b-instruct"},
        "embed": {"provider": "nvidia_nim", "model": "nvidia/llama-nemotron-embed-1b-v2", "dimensions": 16},
    },
}

BEDROCK_WITH_NIM_FALLBACK = {
    "data_mode": "test",
    "providers": {"nvidia_nim": {}, "bedrock": {"enabled": True, "allowed_data": "real"}},
    "roles": {"planner": {"provider": "bedrock", "model": "sonnet"}},
    "fallback": {"provider": "nvidia_nim", "models": {"planner": "meta/llama-3.3-70b-instruct"}},
}


class Out(BaseModel):
    ok: bool


def test_enruta_cada_rol_a_nim():
    gw, calls = make_gateway(NIM_ONLY)
    assert gw.chat("planner").with_structured_output(Out).invoke([]).ok
    gw.chat("fast").invoke([])
    assert calls == ["nvidia_nim:meta/llama-3.3-70b-instruct", "nvidia_nim:meta/llama-3.1-8b-instruct"]
    assert gw.labels["planner"] == "nvidia_nim:meta/llama-3.3-70b-instruct"
    assert gw.embed_model == "nvidia_nim:nvidia/llama-nemotron-embed-1b-v2@16"
    assert len(gw.embeddings().embed_query("x")) == 16


def test_pasar_a_bedrock_es_solo_configuracion():
    """F16-CA1: el mismo código atiende Bedrock al cambiar `provider` en la configuración."""
    cfg = {**NIM_ONLY, "providers": {"bedrock": {"enabled": True}, "nvidia_nim": {"enabled": False}},
           "roles": {"planner": {"provider": "bedrock", "model": "sonnet"}}}
    gw, calls = make_gateway(cfg)
    gw.chat("planner").invoke([])
    assert calls == ["bedrock:sonnet"]


def test_proveedor_desactivado_no_arranca():
    cfg = {**NIM_ONLY, "roles": {"planner": {"provider": "bedrock", "model": "sonnet"}}}
    with pytest.raises(GatewayConfigError, match="desactivado"):
        make_gateway(cfg)


def test_guarda_de_residencia_con_datos_reales():
    """F17/OP-06: con data_mode=real no se puede usar la API alojada de NVIDIA (allowed_data: test)."""
    with pytest.raises(ResidencyError):
        make_gateway({**NIM_ONLY, "data_mode": "real"})
    with pytest.raises(ResidencyError):  # tampoco como respaldo
        make_gateway({**BEDROCK_WITH_NIM_FALLBACK, "data_mode": "real"})
    # Un NIM autoalojado en la red del banco puede declararse apto para datos reales.
    self_hosted = {**NIM_ONLY, "data_mode": "real",
                   "providers": {"nvidia_nim": {"base_url": "http://nim.corp.local:8000/v1", "allowed_data": "real"}}}
    make_gateway(self_hosted)


def test_respaldo_solo_ante_errores_transitorios():
    gw, calls = make_gateway(BEDROCK_WITH_NIM_FALLBACK, {"bedrock": [TimeoutError("read timeout")]})
    gw.chat("planner").invoke([])
    assert calls == ["bedrock:sonnet", "nvidia_nim:meta/llama-3.3-70b-instruct"]
    assert gw.labels["planner"] == "nvidia_nim:meta/llama-3.3-70b-instruct (respaldo)"

    gw, calls = make_gateway(BEDROCK_WITH_NIM_FALLBACK, {"bedrock": [ValueError("ValidationException: prompt inválido")]})
    with pytest.raises(ValueError):
        gw.chat("planner").invoke([])
    assert calls == ["bedrock:sonnet"]  # un error de contenido no salta de proveedor


def test_sin_respaldo_el_error_transitorio_se_propaga():
    gw, _ = make_gateway(NIM_ONLY, {"nvidia_nim": [Exception("[429] Too Many Requests")]})
    with pytest.raises(AllProvidersFailed, match="nvidia_nim:throttling"):
        gw.chat("planner").invoke([])


def test_circuit_breaker_abre_tras_tres_errores():
    now = [0.0]
    errors = [Exception("[503] Service Unavailable") for _ in range(3)]
    gw, calls = make_gateway(BEDROCK_WITH_NIM_FALLBACK, {"bedrock": errors}, clock=lambda: now[0])
    for _ in range(3):
        gw.chat("planner").invoke([])
    calls.clear()
    gw.chat("planner").invoke([])
    assert calls == ["nvidia_nim:meta/llama-3.3-70b-instruct"]  # Bedrock ni se intenta: circuito abierto
    now[0] = 301.0
    calls.clear()
    gw.chat("planner").invoke([])
    assert calls == ["bedrock:sonnet"]  # pasados 5 min se vuelve a intentar


@pytest.mark.parametrize(
    "exc,kind",
    [
        (TimeoutError(), "timeout"),
        (Exception("[429] Too Many Requests for url"), "throttling"),
        (Exception("[503] Service Unavailable"), "service_unavailable"),
        (ConnectionError("reset"), "service_unavailable"),
        (Exception("An error occurred (ThrottlingException) when calling Converse"), "throttling"),
        (ValueError("max_tokens debe ser menor que 500"), None),
        (Exception("[400] Bad Request: invalid schema"), None),
    ],
)
def test_clasificacion_de_errores(exc, kind):
    assert classify_error(exc) == kind


def test_discover_flow_con_el_gateway(analyst):
    """El grafo usa el gateway sin saber el proveedor; la auditoría registra proveedor:modelo por paso."""
    gw, calls = make_gateway(NIM_ONLY)
    service = build_service(FIXTURE, gateway=gw)
    user = user_with_databases(service, "analista", ["VBank_ING", "Onboarding", "DWH"])
    env = service.run(ONBOARDING_Q, user)
    assert env.status == "ok"
    assert env.discovery.candidates[0].asset_key == "VBank_ING.dbo.Users.ClientCode"
    steps = {s.step: s for s in service.deps.audit.records[-1].steps}
    assert steps["intent"].model == "nvidia_nim:meta/llama-3.3-70b-instruct" and steps["intent"].ok
    assert steps["respond"].model == "nvidia_nim:meta/llama-3.1-8b-instruct"
    assert "nvidia_nim:meta/llama-3.3-70b-instruct" in calls
    assert service.deps.store.embed_model == "nvidia_nim:nvidia/llama-nemotron-embed-1b-v2@16"


def test_caida_total_del_proveedor_usa_el_modo_determinista(analyst):
    gw, _ = make_gateway(NIM_ONLY, {"nvidia_nim": [Exception("[503] Service Unavailable")] * 10})
    service = build_service(FIXTURE, gateway=gw)
    user = user_with_databases(service, "analista", ["VBank_ING", "Onboarding", "DWH"])
    env = service.run(ONBOARDING_Q, user)
    assert env.status == "ok" and env.discovery.candidates[0].asset_key == "VBank_ING.dbo.Users.ClientCode"
    assert service.deps.audit.records[-1].steps[0].error == "fallback:AllProvidersFailed"


def test_smoke_cli(capsys):
    from converdata.cli import llm_smoke

    gw, _ = make_gateway({**NIM_ONLY, "roles": {"embed": NIM_ONLY["roles"]["embed"]}})
    assert llm_smoke("unused", gateway=gw) == 0
    assert "OK  embed" in capsys.readouterr().out


def test_timeout_del_proveedor_llega_al_cliente_de_nim(monkeypatch):
    import langchain_nvidia_ai_endpoints

    from converdata.llm.factory import ProviderConfig, RoleConfig, build_nim_chat

    seen = {}
    monkeypatch.setattr(langchain_nvidia_ai_endpoints, "ChatNVIDIA", lambda **kw: seen.update(kw))
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    role = RoleConfig(provider="nvidia_nim", model="openai/gpt-oss-20b")
    build_nim_chat(role, ProviderConfig(timeout_s=12.5))
    assert seen["timeout"] == 12.5
    build_nim_chat(role, ProviderConfig())
    assert seen["timeout"] == 30.0  # valor por defecto de ProviderConfig


def test_ejemplo_de_configuracion_es_valido():
    """config/models.example.yaml carga y valida (sin construir modelos reales)."""
    from pathlib import Path

    from converdata.llm.factory import load_models

    cfg = load_models(Path(__file__).parents[1] / "config" / "models.example.yaml")
    gw = LLMGateway(cfg, builders={})
    assert {r.provider for r in cfg.roles.values()} == {"nvidia_nim"}
    assert cfg.roles["embed"].dimensions == 1024
    assert gw.labels["planner"].startswith("nvidia_nim:")


OLLAMA_LOCAL = {
    "environment": "local",
    "providers": {"ollama": {}},
    "roles": {"planner": {"provider": "ollama", "model": "qwen3.6:35b-a3b"}},
}


def test_ollama_permitido_en_local():
    calls = []
    builders = {("ollama", "chat"): lambda role, prov: FakeModel("ollama", role.model, {"ollama": []}, calls)}
    gw = LLMGateway(ModelsConfig.model_validate(OLLAMA_LOCAL), builders=builders)
    gw.chat("planner").invoke([])
    assert calls == ["ollama:qwen3.6:35b-a3b"] and gw.labels["planner"] == "ollama:qwen3.6:35b-a3b"


@pytest.mark.parametrize("env", [None, "dev", "qa", "prod"])
def test_ollama_bloqueado_fuera_de_local(env):
    with pytest.raises(GatewayConfigError, match="solo se permite con environment: local"):
        LLMGateway(ModelsConfig.model_validate({**OLLAMA_LOCAL, "environment": env}), builders={})


def test_ollama_tampoco_como_respaldo_fuera_de_local():
    cfg = {**BEDROCK_WITH_NIM_FALLBACK, "environment": "prod", "providers": {"bedrock": {"enabled": True}, "ollama": {}},
           "fallback": {"provider": "ollama", "models": {"planner": "qwen3.6:35b-a3b"}}}
    with pytest.raises(GatewayConfigError):
        LLMGateway(ModelsConfig.model_validate(cfg), builders={})


def test_variable_de_entorno_del_servidor_gana_al_archivo(monkeypatch, tmp_path):
    """El archivo dice local, pero el servidor fija CONVERDATA_ENV=prod: Ollama queda bloqueado."""
    from pathlib import Path

    from converdata.llm.factory import load_models

    example = Path(__file__).parents[1] / "config" / "models.local.example.yaml"
    assert LLMGateway(load_models(example), builders={}).labels["planner"] == "ollama:qwen3.6:35b-a3b"
    monkeypatch.setenv("CONVERDATA_ENV", "prod")
    with pytest.raises(GatewayConfigError):
        LLMGateway(load_models(example), builders={})


def test_error_de_conexion_a_ollama_es_transitorio():
    class ConnectError(Exception):  # httpx.ConnectError cuando Ollama no está corriendo
        pass

    assert classify_error(ConnectError("[WinError 10061] conexión rechazada")) == "service_unavailable"
