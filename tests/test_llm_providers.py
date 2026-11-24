"""Proveedores OpenAI y Claude (API de Anthropic) del gateway de LLM (F16): se eligen por configuración."""

from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from discovery_data_agent.llm.factory import ModelsConfig
from discovery_data_agent.llm.gateway import LLMGateway, ResidencyError, classify_error


class Out(BaseModel):
    ok: bool


class FakeModel:
    def __init__(self, provider, model, script, calls):
        self.provider, self.model, self.script, self.calls = provider, model, script, calls

    def invoke(self, messages, **kwargs):
        self.calls.append(f"{self.provider}:{self.model}")
        step = self.script[self.provider].pop(0) if self.script[self.provider] else "ok"
        if isinstance(step, Exception):
            raise step
        return NS(content="respuesta")


def test_openai_y_claude_se_eligen_por_configuracion():
    """Cada rol puede ir a un proveedor distinto y el respaldo a un tercero, sin tocar código."""
    cfg = {"providers": {"openai": {}, "anthropic": {}, "nvidia_nim": {}},
           "roles": {"planner": {"provider": "anthropic", "model": "claude-opus-5-5", "effort": "low"},
                     "fast": {"provider": "openai", "model": "modelo-pequeno"}},
           "fallback": {"provider": "nvidia_nim", "models": {"planner": "nvidia/nemotron-3.5-bolt-e4b"}}}
    script = {"anthropic": [TimeoutError("read timeout")], "openai": [], "nvidia_nim": []}
    calls: list[str] = []
    builders = {(p, "chat"): (lambda p: lambda role, prov: FakeModel(p, role.model, script, calls))(p) for p in script}
    gw = LLMGateway(ModelsConfig.model_validate(cfg), builders=builders)
    assert gw.labels["planner"] == "anthropic:claude-opus-5-5" and gw.labels["fast"] == "openai:modelo-pequeno"
    gw.chat("fast").invoke([])
    gw.chat("planner").invoke([])
    assert calls == ["openai:modelo-pequeno", "anthropic:claude-opus-5-5", "nvidia_nim:nvidia/nemotron-3.5-bolt-e4b"]
    assert gw.labels["planner"] == "nvidia_nim:nvidia/nemotron-3.5-bolt-e4b (respaldo)"


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_openai_y_claude_son_terceros_y_no_reciben_datos_reales_por_defecto(provider):
    cfg = {"data_mode": "real", "providers": {provider: {}}, "roles": {"planner": {"provider": provider, "model": "m"}}}
    with pytest.raises(ResidencyError):
        LLMGateway(ModelsConfig.model_validate(cfg), builders={})


def test_un_proveedor_desconocido_no_carga():
    with pytest.raises(ValueError):
        ModelsConfig.model_validate({"roles": {"planner": {"provider": "otro", "model": "m"}}})


def test_el_constructor_de_openai_recibe_modelo_clave_y_limites(monkeypatch):
    import langchain_openai

    from discovery_data_agent.llm.factory import MissingCredential, ProviderConfig, RoleConfig, build_openai_chat

    seen = {}
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: seen.update(kw))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    role = RoleConfig(provider="openai", model="m", max_tokens=500, effort="low")
    with pytest.raises(MissingCredential, match="OPENAI_API_KEY"):
        build_openai_chat(role, ProviderConfig())
    monkeypatch.setenv("MI_CLAVE", "sk-prueba")
    build_openai_chat(role, ProviderConfig(api_key_env="MI_CLAVE", timeout_s=12))
    # `base_url` siempre explícita: una variable OPENAI_BASE_URL del entorno no puede desviar las peticiones.
    assert seen == {"model": "m", "api_key": "sk-prueba", "base_url": "https://api.openai.com/v1", "timeout": 12,
                    "max_retries": 1, "max_completion_tokens": 500, "reasoning_effort": "low"}  # sin `temperature`
    seen.clear()
    build_openai_chat(role, ProviderConfig(base_url="http://llm.corp.local/v1"))  # servidor compatible sin clave
    assert seen["base_url"] == "http://llm.corp.local/v1" and seen["api_key"] == "sin-clave"
    monkeypatch.delenv("MI_CLAVE")
    with pytest.raises(MissingCredential, match="MI_CLAVE"):  # clave declarada pero ausente: no pasa por "sin clave"
        build_openai_chat(role, ProviderConfig(base_url="http://llm.corp.local/v1", api_key_env="MI_CLAVE"))


def test_el_cliente_real_de_openai_acepta_los_parametros_del_constructor(monkeypatch):
    from discovery_data_agent.llm.factory import ProviderConfig, RoleConfig, build_openai_chat

    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    chat = build_openai_chat(RoleConfig(provider="openai", model="m", temperature=0.0, max_tokens=500, effort="low"),
                             ProviderConfig(timeout_s=12))
    assert (chat.model_name, chat.max_tokens, chat.reasoning_effort, chat.request_timeout) == ("m", 500, "low", 12)


class FakeAnthropic:
    """Cliente falso del SDK de Anthropic: guarda cada petición y devuelve la respuesta guionizada."""

    def __init__(self, response):
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class Messages:
            def __init__(self, name):
                self.name = name

            def create(self, **kw):
                outer.requests.append((f"{self.name}.create", kw))
                return response

            def parse(self, **kw):
                outer.requests.append((f"{self.name}.parse", kw))
                return response

        self.messages = Messages("messages")
        self.beta = NS(messages=Messages("beta.messages"))


def claude_response(text="hola", parsed=None, stop_reason="end_turn", category=None):
    return NS(content=[NS(type="thinking", thinking=""), NS(type="text", text=text)], parsed_output=parsed,
              stop_reason=stop_reason, stop_details=NS(category=category) if category else None,
              usage=NS(input_tokens=120, output_tokens=30))


def test_claude_texto_separa_el_system_y_devuelve_el_uso_real():
    from langchain_core.messages import HumanMessage, SystemMessage

    from discovery_data_agent.llm.anthropic_chat import ClaudeChat

    client = FakeAnthropic(claude_response("El DUI está en Solicitudes."))
    msg = ClaudeChat(client, "claude-opus-5-5", max_tokens=4000, effort="low").invoke(
        [SystemMessage("Eres un analista."), HumanMessage("¿Dónde está el DUI?")])
    assert msg.content == "El DUI está en Solicitudes."  # el bloque de pensamiento no se mezcla con la respuesta
    assert msg.usage_metadata["input_tokens"] == 120 and msg.usage_metadata["output_tokens"] == 30
    (call, sent), = client.requests
    assert call == "messages.create"
    assert sent == {"model": "claude-opus-5-5", "max_tokens": 4000, "system": "Eres un analista.",
                    "messages": [{"role": "user", "content": "¿Dónde está el DUI?"}],
                    "output_config": {"effort": "low"}}  # ni `temperature` ni `thinking`: el modelo los rechaza


def test_claude_salida_estructurada_y_respaldo_ante_rechazo():
    from discovery_data_agent.llm.anthropic_chat import DEFAULT_MAX_TOKENS, ClaudeChat

    client = FakeAnthropic(claude_response(parsed=Out(ok=True)))
    assert ClaudeChat(client, "claude-opus-5-5").with_structured_output(Out).invoke("ping").ok
    call, sent = client.requests[0]
    assert call == "messages.parse" and sent["output_format"] is Out and sent["max_tokens"] == DEFAULT_MAX_TOKENS
    assert "fallbacks" not in sent and "output_config" not in sent

    client = FakeAnthropic(claude_response(parsed=Out(ok=True)))
    ClaudeChat(client, "claude-opus-5-5", refusal_fallback=True).with_structured_output(Out).invoke("ping")
    call, sent = client.requests[0]
    assert call == "beta.messages.parse" and sent["fallbacks"] == "default" and sent["betas"]


def test_claude_un_rechazo_o_una_salida_cortada_son_errores_de_contenido():
    """No son transitorios: el gateway no salta a otro proveedor y el flujo cae al modo determinista."""
    from discovery_data_agent.llm.anthropic_chat import ClaudeChat, LLMRefused

    refused = ClaudeChat(FakeAnthropic(claude_response(stop_reason="refusal", category="cyber")), "claude-opus-5-5")
    with pytest.raises(LLMRefused, match="cyber") as err:
        refused.invoke("x")
    assert classify_error(err.value) is None
    cut = ClaudeChat(FakeAnthropic(claude_response(stop_reason="max_tokens")), "claude-opus-5-5")
    for chat in (cut, cut.with_structured_output(Out)):  # ni la narrativa ni la salida estructurada se entregan cortadas
        with pytest.raises(ValueError, match="max_tokens") as err:
            chat.invoke("x")
        assert classify_error(err.value) is None


def test_dos_roles_con_el_mismo_modelo_no_comparten_ajustes():
    built = []
    cfg = {"providers": {"anthropic": {}},
           "roles": {"planner": {"provider": "anthropic", "model": "claude-opus-5-5", "max_tokens": 8000, "refusal_fallback": True},
                     "fast": {"provider": "anthropic", "model": "claude-opus-5-5", "max_tokens": 4000}}}
    builders = {("anthropic", "chat"): lambda role, prov: built.append(role) or FakeModel("anthropic", role.model, {"anthropic": []}, [])}
    gw = LLMGateway(ModelsConfig.model_validate(cfg), builders=builders)
    for role in ("planner", "fast", "planner"):
        gw.chat(role).invoke([])
    assert [(r.max_tokens, r.refusal_fallback) for r in built] == [(8000, True), (4000, False)]


def test_el_respaldo_no_hereda_ajustes_propios_del_proveedor_primario():
    cfg = {"providers": {"anthropic": {}, "openai": {}},
           "roles": {"planner": {"provider": "anthropic", "model": "claude-opus-5-5", "effort": "max",
                                 "refusal_fallback": True, "max_tokens": 8000}},
           "fallback": {"provider": "openai", "models": {"planner": "m"}}}
    backup = LLMGateway(ModelsConfig.model_validate(cfg), builders={}).routes("planner")[1].role
    assert (backup.provider, backup.model, backup.effort, backup.refusal_fallback, backup.max_tokens) == ("openai", "m", None, False, 8000)


def test_con_datos_reales_no_se_admite_el_respaldo_ante_rechazo():
    """La petición podría atenderla un modelo que la configuración no nombra."""
    cfg = {"data_mode": "real", "providers": {"anthropic": {"allowed_data": "real"}},
           "roles": {"planner": {"provider": "anthropic", "model": "claude-opus-5-5", "refusal_fallback": True}}}
    with pytest.raises(ResidencyError, match="refusal_fallback"):
        LLMGateway(ModelsConfig.model_validate(cfg), builders={})


def test_un_4xx_no_es_transitorio_aunque_su_texto_hable_de_limites():
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.example/v1/messages")
    exc = anthropic.AuthenticationError("clave inválida; rate limit del plan", response=httpx2.Response(401, request=request), body=None)
    assert classify_error(exc) is None


def test_el_sdk_real_de_anthropic_acepta_la_peticion_que_arma_el_adaptador(monkeypatch):
    """Sin red: el transporte responde en local. Comprueba la forma de la petición y que los esquemas del flujo
    (intención, orden) pasan por `messages.parse` del SDK instalado."""
    import json

    import anthropic
    import httpx2

    from discovery_data_agent.discovery.ports import RerankResult
    from discovery_data_agent.llm.anthropic_chat import ClaudeChat
    from discovery_data_agent.models.intent import IntentResult

    sent: list[dict] = []
    answers = {"IntentResult": {"intent": "discovery", "rewritten_question": "¿dónde está el DUI?", "confidence": 0.9},
               "RerankResult": {"items": [{"id": "a1", "relevance": 0.8, "why": "coincide"}]}}

    def handler(request):
        body = json.loads(request.content)
        sent.append({"path": request.url.path, "beta": request.headers.get("anthropic-beta"), **body})
        answer = answers[body["system"]]
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "stop_reason": "end_turn",
            "stop_sequence": None, "content": [{"type": "text", "text": json.dumps(answer)}],
            "usage": {"input_tokens": 10, "output_tokens": 5}})

    client = anthropic.Anthropic(api_key="sk-ant-prueba", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    from langchain_core.messages import HumanMessage, SystemMessage

    chat = ClaudeChat(client, "claude-opus-5-5", max_tokens=8000, effort="low", refusal_fallback=True)
    intent = chat.with_structured_output(IntentResult).invoke([SystemMessage("IntentResult"), HumanMessage("p")])
    assert isinstance(intent, IntentResult) and intent.intent == "discovery"
    order = chat.with_structured_output(RerankResult).invoke([SystemMessage("RerankResult"), HumanMessage("p")])
    assert order.items[0].id == "a1"
    first = sent[0]
    assert first["path"] == "/v1/messages" and first["model"] == "claude-opus-5-5" and first["max_tokens"] == 8000
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["beta"]
    assert first["output_config"]["effort"] == "low" and first["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in first and "thinking" not in first


def test_el_constructor_de_claude_usa_el_sdk_oficial(monkeypatch):
    import anthropic

    from discovery_data_agent.llm.anthropic_chat import ClaudeChat
    from discovery_data_agent.llm.factory import MissingCredential, ProviderConfig, RoleConfig, build_anthropic_chat

    seen = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: seen.update(kw) or "cliente")
    monkeypatch.delenv("MI_CLAVE", raising=False)
    role = RoleConfig(provider="anthropic", model="claude-opus-5-5", temperature=0.0, effort="low", refusal_fallback=True)
    with pytest.raises(MissingCredential, match="MI_CLAVE"):
        build_anthropic_chat(role, ProviderConfig(api_key_env="MI_CLAVE"))
    monkeypatch.setenv("MI_CLAVE", "sk-ant-prueba")
    chat = build_anthropic_chat(role, ProviderConfig(api_key_env="MI_CLAVE", timeout_s=60))
    assert isinstance(chat, ClaudeChat) and chat.model == "claude-opus-5-5"
    assert seen == {"timeout": 60, "max_retries": 1, "api_key": "sk-ant-prueba", "base_url": "https://api.anthropic.com"}
    seen.clear()
    build_anthropic_chat(role, ProviderConfig())  # sin `api_key_env` el SDK resuelve la credencial del entorno
    assert "api_key" not in seen


def test_claude_en_bedrock_usa_el_cliente_mantle_del_sdk_oficial(monkeypatch):
    """`anthropic.claude-*` en Bedrock va por la Messages API (bedrock-mantle) con el rol de la tarea: salida
    estructurada sin forzar una herramienta (Claude Sonnet 5.5 lo rechaza) y sin `temperature`. Bedrock no tiene el
    respaldo de servidor (`fallbacks`), así que no se pide aunque el rol lo declare."""
    import anthropic
    import langchain_aws

    from discovery_data_agent.llm.anthropic_chat import ClaudeChat
    from discovery_data_agent.llm.factory import ProviderConfig, RoleConfig, build_bedrock_chat

    seen = {}
    monkeypatch.setattr(anthropic, "AnthropicBedrockMantle", lambda **kw: seen.update(kw) or "cliente")
    role = RoleConfig(provider="bedrock", model="anthropic.claude-haiku-5-5", temperature=0.0, max_tokens=800,
                      effort="low", refusal_fallback=True)
    chat = build_bedrock_chat(role, ProviderConfig(region="us-east-2", timeout_s=45))
    assert isinstance(chat, ClaudeChat) and chat.model == "anthropic.claude-haiku-5-5"
    assert seen == {"aws_region": "us-east-2", "timeout": 45, "max_retries": 1}
    assert chat._refusal_fallback is False and chat._effort == "low" and chat._max_tokens == 800

    # Los demás modelos de Bedrock siguen por Converse.
    monkeypatch.setattr(langchain_aws, "ChatBedrockConverse", lambda **kw: ("converse", kw))
    other = build_bedrock_chat(RoleConfig(provider="bedrock", model="amazon.nova-pro-v1:0"), ProviderConfig())
    assert other[0] == "converse" and other[1]["model"] == "amazon.nova-pro-v1:0"


def test_los_errores_reales_de_los_sdk_se_clasifican():
    """Las excepciones de `anthropic` y `openai` llevan el código HTTP: con él el gateway decide si salta de proveedor."""
    import anthropic
    import httpx
    import httpx2
    import openai

    def http(lib, cls, status):
        request = lib.Request("POST", "https://api.example/v1/messages")
        return cls("fallo", response=lib.Response(status, request=request), body=None)

    assert classify_error(http(httpx2, anthropic.RateLimitError, 429)) == "throttling"
    assert classify_error(http(httpx2, anthropic.InternalServerError, 529)) == "service_unavailable"
    assert classify_error(http(httpx2, anthropic.BadRequestError, 400)) is None
    assert classify_error(http(httpx2, anthropic.AuthenticationError, 401)) is None
    assert classify_error(anthropic.APITimeoutError(httpx2.Request("POST", "https://api.example"))) == "timeout"
    assert classify_error(http(httpx, openai.RateLimitError, 429)) == "throttling"
    assert classify_error(http(httpx, openai.BadRequestError, 400)) is None
    assert classify_error(openai.APITimeoutError(httpx.Request("POST", "https://api.example"))) == "timeout"
