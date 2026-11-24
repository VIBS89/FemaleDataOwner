"""Guardas sobre la salida de los nodos con LLM: el modelo razona dentro del nodo, pero no puede inventar ni saltarse pasos."""

import pytest

from discovery_data_agent.discovery.ports import RerankScore
from discovery_data_agent.flows.discover import DiscoverService
from discovery_data_agent.models.intent import IntentResult
from conftest import ONBOARDING_Q


class InventingReranker:
    """Devuelve un id que no está en la lista y pone UserId primero."""

    def rerank(self, question, items):
        return [
            RerankScore(id="Core.dbo.Secreto.Columna", relevance=1.0, why="inventado"),
            RerankScore(id="VBank_ING.dbo.Users.UserId", relevance=1.0, why="Identificador técnico de la app."),
        ]


class InventingNarrator:
    def narrate(self, question, discovery):
        return "Usa la columna Salario de Empleado."  # objetos que no están en la respuesta


class FailingClassifier:
    def classify(self, question, history):
        raise TimeoutError("Bedrock throttling")


class FixedClassifier:
    def classify(self, question, history):
        return IntentResult(
            intent="discovery", rewritten_question=question, business_context="onboarding digital",
            asset_kind_hint="column", confidence=0.9,
        )


def test_reranker_no_puede_anadir_candidatos(service, analyst):
    service.deps.settings.patterns.cascade = False  # forzar la llamada al reranker
    service.deps.reranker = InventingReranker()
    env = DiscoverService(service.deps).run(ONBOARDING_Q, analyst)
    keys = [c.asset_key for c in env.discovery.candidates] + [a.asset_key for a in env.discovery.alternatives]
    assert "Core.dbo.Secreto.Columna" not in keys
    rerank_step = next(s for s in service.deps.audit.records[-1].steps if s.step == "rerank")
    assert rerank_step.error == "ids_descartados:1"


def test_narrativa_con_objetos_ajenos_se_reemplaza(service, analyst):
    service.deps.narrator = InventingNarrator()
    env = DiscoverService(service.deps).run(ONBOARDING_Q, analyst)
    assert "Salario" not in env.answer_text and "ClientCode" in env.answer_text
    respond = next(s for s in service.deps.audit.records[-1].steps if s.step == "respond")
    assert respond.error.startswith("narrativa_rechazada")


class EmptyNarrator:
    """Un modelo de razonamiento que gasta `max_tokens` pensando devuelve el contenido vacío."""

    def __init__(self, text):
        self.text = text

    def narrate(self, question, discovery):
        return self.text


@pytest.mark.parametrize("text", ["", "   \n "])
def test_narrativa_vacia_usa_el_texto_determinista(service, analyst, text):
    service.deps.narrator = EmptyNarrator(text)
    env = DiscoverService(service.deps).run(ONBOARDING_Q, analyst)
    assert "ClientCode" in env.answer_text  # el usuario nunca recibe una respuesta sin texto
    respond = next(s for s in service.deps.audit.records[-1].steps if s.step == "respond")
    assert respond.error == "narrativa_vacia"


def test_narrativa_del_modelo_llega_como_texto_plano():
    """La web muestra `answer_text` tal cual: sin Markdown, el usuario vería los asteriscos."""
    from types import SimpleNamespace as NS

    from discovery_data_agent.llm.nodes import LlmNarrator
    from discovery_data_agent.models.discovery import Discovery

    class MarkdownLlm:
        def invoke(self, messages):
            return NS(content="## Resultado\nEncontré el **DUI** en la tabla __Clientes__ de `BancaPrestamos`.")

    text = LlmNarrator(MarkdownLlm()).narrate("¿Dónde está el DUI?", Discovery(question="¿Dónde está el DUI?"))
    assert text == "Resultado\nEncontré el DUI en la tabla Clientes de BancaPrestamos."


def test_fallo_del_modelo_usa_el_respaldo_determinista(service, analyst):
    service.deps.intent_classifier = FailingClassifier()
    env = DiscoverService(service.deps).run(ONBOARDING_Q, analyst)
    assert env.status == "ok"
    assert env.discovery.candidates[0].asset_key == "VBank_ING.dbo.Users.ClientCode"
    intent_step = service.deps.audit.records[-1].steps[0]
    assert intent_step.error == "fallback:TimeoutError"


def test_clasificador_inyectado_mismo_grafo(service, analyst):
    service.deps.intent_classifier = FixedClassifier()
    env = DiscoverService(service.deps).run(ONBOARDING_Q, analyst)
    assert env.discovery.candidates[0].asset_key == "VBank_ING.dbo.Users.ClientCode"


def test_flows_es_la_unica_capa_con_langgraph():
    """PRD §8: herramientas, VectorStore, motor y modelos no importan LangGraph."""
    import pathlib

    src = pathlib.Path(__file__).parents[1] / "src" / "discovery_data_agent"
    offenders = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if "langgraph" in p.read_text(encoding="utf-8") and p.parent.name != "flows"
    ]
    assert offenders == []
