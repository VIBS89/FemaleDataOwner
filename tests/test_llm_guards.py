"""Guardas sobre la salida de los nodos con LLM: el modelo razona dentro del nodo, pero no puede inventar ni saltarse pasos."""

from converdata.discovery.ports import RerankScore
from converdata.flows.discover import DiscoverService
from converdata.models.intent import IntentResult
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

    src = pathlib.Path(__file__).parents[1] / "src" / "converdata"
    offenders = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if "langgraph" in p.read_text(encoding="utf-8") and p.parent.name != "flows"
    ]
    assert offenders == []
