"""Reformulación del expansor (LLM) sobre `grade_node`: cuando la búsqueda cubre poco, la primera variante pasa a ser
lo que se mide para decidir si un activo responde. Todo en modo determinista, con un doble del puerto `QueryExpander`
sobre el fixture `bancos` (solo metadatos). También `is_join_question` y la intención de los prompts del modelo."""

from __future__ import annotations

from pathlib import Path

import pytest

from discovery_data_agent.bootstrap import build_service, user_with_databases
from discovery_data_agent.discovery.deterministic import is_join_question
from discovery_data_agent.llm import nodes

BANCOS = Path(__file__).parent / "fixtures" / "bancos"
REPORTE = "¿Qué datos necesito para el reporte de cartera en mora mayor a 90 días que pide la Superintendencia?"
CRUCE = "¿Cómo se cruzan los movimientos de cuenta con las agencias?"
COMPUESTA = "¿Dónde está el valor de avalúo de las garantías y el nombre del cliente?"
BRECHA = "¿Dónde están las inversiones en bolsa del cliente?"
MORA = ["días de mora del préstamo", "saldo capital préstamo"]
NOTA = "Entendí que necesitas"


class Expansor:
    def __init__(self, variantes=None, error: Exception | None = None):
        self.variantes, self.error, self.calls = variantes or [], error, []

    def expand(self, question: str, weak_terms: list[str]) -> list[str]:
        self.calls.append((question, list(weak_terms)))
        if self.error:
            raise self.error
        return list(self.variantes)


@pytest.fixture
def servicio():
    return build_service(BANCOS)


@pytest.fixture
def todos(servicio):
    return user_with_databases(servicio, "dev", None)


def _con(servicio, expansor):
    servicio.deps.expander = expansor
    return expansor


def _claves(env) -> list[str]:
    return [c.asset_key for c in env.discovery.candidates]


def _caminos(env) -> list:
    return [(p.purpose, tuple(p.tables)) for p in env.discovery.join_paths]


def _nota(env) -> bool:
    return any(NOTA in a for a in env.assumptions)


# --- 1. Reformulación que sustituye a los conceptos --------------------------------------------------------------

def test_sin_expansor_el_reporte_no_da_candidatos(servicio, todos):
    """Modo determinista: nada cambia, la pregunta sobre un reporte no nombra ningún dato."""
    _con(servicio, None)
    env = servicio.run(REPORTE, todos)
    assert _claves(env) == [] and env.discovery.knowledge_gap and not _nota(env)


def test_con_expansor_el_reporte_encuentra_dias_de_mora_y_lo_dice(servicio, todos):
    _con(servicio, Expansor(MORA))
    env = servicio.run(REPORTE, todos)
    assert _claves(env), "la reformulación debe producir candidatos"
    principal = env.discovery.candidates[0].asset_key
    assert principal.startswith("BancaPrestamos.") and principal.endswith(".DiasMora")
    assert _nota(env)
    nota = next(a for a in env.assumptions if NOTA in a)
    assert "días de mora del préstamo" in nota


@pytest.mark.parametrize("pregunta", [CRUCE, COMPUESTA], ids=["cruce", "compuesta"])
def test_cruce_y_compuesta_conservan_sus_caminos_de_union(servicio, todos, pregunta):
    _con(servicio, None)
    sin = servicio.run(pregunta, todos)
    assert sin.discovery.join_paths, "precondición: la pregunta tiene camino de unión"
    _con(servicio, Expansor(MORA))
    con = servicio.run(pregunta, todos)
    assert _caminos(con) == _caminos(sin)
    assert _claves(con) == _claves(sin)
    assert not _nota(con), "una pregunta de cruce o compuesta no se reescribe con la variante"


def test_una_brecha_sigue_siendolo_si_el_expansor_no_propone_nada(servicio, todos):
    _con(servicio, Expansor([]))
    env = servicio.run(BRECHA, todos)
    assert _claves(env) == [] and env.discovery.knowledge_gap and not _nota(env)


# --- 2. F14: la reformulación no abre lo que el usuario no ve ----------------------------------------------------

def test_f14_un_usuario_de_leasing_no_ve_prestamos_por_la_reformulacion(servicio):
    solo_leasing = user_with_databases(servicio, "leasing", ["BancaLeasing"])
    _con(servicio, Expansor(MORA))
    env = servicio.run(REPORTE, solo_leasing)
    assert "BancaPrestamos" not in env.model_dump_json()
    assert all(k.startswith("BancaLeasing.") for k in _claves(env))


# --- 3. Expansor hostil -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("variante", [
    "revisa http://malo.example/mora", "https://malo.example", "<b>días de mora</b>", "escribe a x@malo.example",
], ids=["http", "https", "html", "correo"])
def test_una_variante_con_enlace_html_o_correo_se_descarta(servicio, todos, variante):
    _con(servicio, None)
    base = servicio.run(REPORTE, todos)
    _con(servicio, Expansor([variante]))
    env = servicio.run(REPORTE, todos)
    assert _claves(env) == _claves(base) and not _nota(env)
    assert "malo.example" not in env.model_dump_json()


def test_un_expansor_que_lanza_excepcion_no_rompe_ni_cambia_la_respuesta(servicio, todos):
    _con(servicio, None)
    base = servicio.run(REPORTE, todos)
    espia = _con(servicio, Expansor(error=RuntimeError("caído")))
    env = servicio.run(REPORTE, todos)
    assert espia.calls, "precondición: el expansor fue consultado"
    assert env.status == base.status and _claves(env) == _claves(base) and not _nota(env)


# --- 4. is_join_question ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pregunta", [
    CRUCE, "¿Cómo relaciono pagos con préstamos?", "¿Cómo se unen las cuentas con los clientes?",
])
def test_is_join_question_detecta_preguntas_de_cruce(pregunta):
    assert is_join_question(pregunta)


@pytest.mark.parametrize("pregunta", [REPORTE, BRECHA, "¿Dónde está el DUI del cliente?", "hola"])
def test_is_join_question_no_marca_preguntas_de_ubicacion(pregunta):
    assert not is_join_question(pregunta)


# --- 5. Intención de los prompts ----------------------------------------------------------------------------------

def test_el_prompt_del_expansor_prohibe_cambiar_de_tema_e_inventar_tablas():
    t = " ".join(nodes.EXPAND_SYSTEM.lower().split())
    assert "no cambies de tema" in t and "no inventes" in t and "tablas" in t


def test_el_prompt_del_narrador_prohibe_suponer_el_significado_sin_descripcion_confirmada():
    t = " ".join(nodes.RESPOND_SYSTEM.lower().split())
    assert "no supongas" in t and "no está confirmada" in t
    assert "sin revisar" in t
