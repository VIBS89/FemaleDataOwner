"""Comportamiento de chat del DiscoverFlow: preguntas sobre el asistente, seguimientos, cifras, rechazo, aclaración por
área, guía del modelo cuando no hay candidatos y compuerta del set `chat.yaml`.

Todo corre en modo determinista y sin red: el catálogo es el fixture `bancos` (solo metadatos) y la guía del modelo es
un doble que implementa el puerto `Guide`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from discovery_data_agent.bootstrap import build_service, user_with_databases
from discovery_data_agent.discovery import assistant, engine, expansion
from discovery_data_agent.discovery.deterministic import (
    RuleBasedIntentClassifier,
    TemplateNarrator,
    contextualize,
    is_figures_question,
    is_follow_up,
    join_sentence,
)
from discovery_data_agent.discovery.ports import Advice
from discovery_data_agent.evaluation.discovery_eval import evaluate, load_cases

FIXTURES = Path(__file__).parent / "fixtures"
BANCOS = FIXTURES / "bancos"
VBANK = FIXTURES / "vbank"

OTRAS_BASES = ["BancaPrestamos", "BancaTarjetasCredito", "BancaCuentasDebito", "BancaTokenizacion"]


@pytest.fixture(scope="module")
def bancos():
    return build_service(BANCOS)


@pytest.fixture(scope="module")
def todos(bancos):
    return user_with_databases(bancos, "dev", None)


def _claves(env) -> list[str]:
    disc = env.discovery
    return [c.asset_key for c in disc.candidates] + [a.asset_key for a in disc.alternatives]


def _preguntas(ruta: Path) -> list[tuple[str, str]]:
    data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return [(f"{ruta.parent.parent.name}/{ruta.stem}:{c['id']}", c["question"]) for c in data["cases"]]


# --- 1. topic_of ---------------------------------------------------------------------------------------------------

TEMAS = [
    ("hola", "greeting"),
    ("Hola!", "greeting"),
    ("buenos días", "greeting"),
    ("gracias", "thanks"),
    ("muchas gracias, me sirvió bastante", "thanks"),
    ("adiós", "farewell"),
    ("ok listo, hasta luego", "farewell"),
    ("buenas tardes, quien eres?", "identity"),
    ("¿Quién eres?", "identity"),
    ("para que sirves", "identity"),
    ("que puedes hacer y que no?", "capabilities"),
    ("ayuda", "capabilities"),
    ("si agregan tablas o columnas nuevas a la base, como se entera DiscoveryDataAgent?", "freshness"),
    ("cada cuanto se actualiza tu informacion", "freshness"),
    ("de donde sacas la informacion que me respondes", "sources"),
    ("¿Tú ves los datos de los clientes, como nombres y saldos?", "privacy"),
    ("que bases de datos conoces", "databases"),
    ("y si te equivocas en una respuesta que pasa, como se corrige", "corrections"),
    ("todos los usuarios ven lo mismo o hay permisos por rol?", "permissions"),
    ("puedes ejecutar consultas directo en la base y darme el resultado?", "execution"),
    ("como se calcula la confianza", "confidence"),
]


@pytest.mark.parametrize(("pregunta", "tema"), TEMAS)
def test_topic_of_reconoce_cada_tema(pregunta, tema):
    """Un caso por tema de `assistant.TOPICS`."""
    assert assistant.topic_of(pregunta) == tema


def test_los_casos_por_tema_cubren_todos_los_temas():
    assert {tema for _, tema in TEMAS} == set(assistant.TOPICS)


PREGUNTAS_DE_DATOS = (
    _preguntas(BANCOS / "eval" / "discovery.yaml")
    + _preguntas(BANCOS / "eval" / "reportes.yaml")
    + _preguntas(VBANK / "eval" / "discovery.yaml")
)


def test_hay_preguntas_de_datos_que_comprobar():
    assert len(PREGUNTAS_DE_DATOS) > 50


@pytest.mark.parametrize(("caso", "pregunta"), PREGUNTAS_DE_DATOS, ids=[c for c, _ in PREGUNTAS_DE_DATOS])
def test_ninguna_pregunta_de_datos_se_toma_por_pregunta_del_asistente(caso, pregunta):
    """Una pregunta de los sets de evaluación de datos nunca debe desviarse a la ruta del asistente."""
    assert assistant.topic_of(pregunta) is None, f"{caso}: {pregunta!r} → {assistant.topic_of(pregunta)}"


def test_de_donde_sale_un_indicador_es_pregunta_de_datos():
    """«de dónde sale X» sobre un dato del banco no es «de dónde sacas tu información»."""
    assert assistant.topic_of("¿De dónde sale el indicador de transacciones rechazadas por fraude?") is None


def test_saludo_con_pregunta_de_datos_no_es_saludo():
    assert assistant.topic_of("hola, donde esta el DUI del cliente") is None
    assert assistant.topic_of("gracias, y donde esta el DUI del cliente?") is None


def test_strip_greeting_quita_solo_el_saludo():
    assert assistant.strip_greeting("Buenas tardes, ¿dónde está el DUI?") == "¿dónde está el DUI?"
    assert assistant.strip_greeting("hola, donde esta el DUI") == "donde esta el DUI"
    assert assistant.strip_greeting("¿dónde está el DUI?") == "¿dónde está el DUI?"
    assert assistant.strip_greeting("hola") == "hola"  # sin nada detrás se deja tal cual


def test_answer_responde_todos_los_temas_con_texto_fijo(bancos, todos):
    for tema in assistant.TOPICS:
        texto = assistant.answer(tema, bancos.deps.catalog, todos.visible_ids)
        assert texto and texto == assistant.answer(tema, bancos.deps.catalog, todos.visible_ids)


def test_answer_con_askflow_cambia_lo_que_dice_de_las_cifras(bancos, todos):
    cat, vis = bancos.deps.catalog, todos.visible_ids
    assert "Todavía no" in assistant.answer("execution", cat, vis)
    assert "Todavía no" not in assistant.answer("execution", cat, vis, ask_flow=True)
    assert "Todavía no calculo cifras" in assistant.answer("capabilities", cat, vis)
    assert "Todavía no calculo cifras" not in assistant.answer("capabilities", cat, vis, ask_flow=True)


def test_answer_rechaza_un_tema_desconocido(bancos, todos):
    with pytest.raises(ValueError):
        assistant.answer("inventado", bancos.deps.catalog, todos.visible_ids)


# --- 2. Flujo: pregunta sobre el asistente --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pregunta", "tema"),
    [("hola", "greeting"), ("¿cómo te enteras de las tablas nuevas?", "freshness"), ("que puedes hacer?", "capabilities")],
)
def test_pregunta_al_asistente_responde_sin_descubrimiento(bancos, todos, pregunta, tema):
    env = bancos.run(pregunta, todos)
    assert env.status == "ok" and env.flow == "discover"
    assert env.discovery is None
    assert env.answer_text == assistant.answer(tema, bancos.deps.catalog, todos.visible_ids)
    assert not env.assumptions


def test_pregunta_al_asistente_se_audita_con_intent_assistant(bancos, todos):
    """F11: la ruta del asistente también deja su registro, con la intención `assistant`."""
    env = bancos.run("que puedes hacer y que no?", todos)
    registro = bancos.deps.audit.records[-1]
    assert registro.trace_id == env.trace_id
    assert registro.intent == "assistant"
    assert registro.question == "que puedes hacer y que no?"


def test_pregunta_al_asistente_falla_cerrado_si_la_auditoria_falla(bancos, todos, monkeypatch):
    """F11 fail-closed: si el registrador falla no hay respuesta, tampoco en la ruta del asistente."""

    class AuditoriaRota:
        def write(self, record):
            raise RuntimeError("sin disco")

    monkeypatch.setattr(bancos.deps, "audit", AuditoriaRota())
    env = bancos.run("hola", todos)
    assert env.status == "error"
    assert env.discovery is None
    assert "no se entrega" in env.answer_text
    assert assistant.answer("greeting", bancos.deps.catalog, todos.visible_ids) not in env.answer_text


def test_saludo_con_pregunta_de_datos_se_busca_sin_el_saludo(bancos, todos):
    env = bancos.run("buenas tardes, donde esta el DUI del cliente", todos)
    assert env.status == "ok" and env.discovery is not None
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Clientes.DUI"


def test_dos_saludos_seguidos_se_buscan_sin_saludo(bancos, todos):
    env = bancos.run("hola, buenas tardes, donde esta el DUI del cliente", todos)
    assert env.discovery.candidates and env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Clientes.DUI"


def test_strip_greeting_y_topic_of_quitan_varios_saludos_seguidos():
    assert assistant.strip_greeting("hola, buenas tardes, donde esta el DUI") == "donde esta el DUI"
    assert assistant.topic_of("hola, buenas tardes, donde esta el DUI del cliente") is None
    assert assistant.topic_of("hola, buenas tardes") == "greeting"


def test_bases_de_datos_solo_menciona_las_que_el_usuario_ve(bancos):
    """F14: la lista de «qué bases de datos conoces» no nombra las bases que el usuario no puede ver."""
    usuario = user_with_databases(bancos, "leasing", ["BancaLeasing"])
    env = bancos.run("que bases de datos conoces", usuario)
    assert env.status == "ok" and env.discovery is None
    assert "BancaLeasing" in env.answer_text
    dump = env.model_dump_json(by_alias=True)
    for otra in OTRAS_BASES:
        assert otra not in dump
    assert "1 base de datos" in env.answer_text


def test_bases_de_datos_sin_acceso_no_lista_ninguna(bancos):
    sin_acceso = user_with_databases(bancos, "nadie", [])
    env = bancos.run("que bases de datos conoces", sin_acceso)
    dump = env.model_dump_json(by_alias=True)
    assert "ninguna base de datos visible" in env.answer_text
    assert not any(db in dump for db in ["BancaLeasing", *OTRAS_BASES])


def test_bases_de_datos_con_todo_el_acceso_las_lista_todas(bancos, todos):
    env = bancos.run("que bases de datos conoces", todos)
    for db in ["BancaLeasing", *OTRAS_BASES]:
        assert db in env.answer_text


# --- 3. contextualize ----------------------------------------------------------------------------------------------


def test_contextualize_seguimiento_con_conector():
    texto = contextualize("y como los cruzo con los clientes", ["donde estan los prestamos"])
    assert texto == "donde estan los prestamos y como los cruzo con los clientes"


@pytest.mark.parametrize("conector", ["pero", "ahora", "también", "entonces"])
def test_contextualize_otros_conectores(conector):
    texto = contextualize(f"{conector} por agencia", ["cual es el saldo total de la cartera?"])
    assert texto.startswith("cual es el saldo total de la cartera") and texto.endswith(f"{conector} por agencia")


def test_contextualize_seguimiento_con_anafora():
    texto = contextualize("de esos cuantos tienen tarjeta", ["cuantos clientes tienen prestamos?"])
    assert texto == "cuantos clientes tienen prestamos de esos cuantos tienen tarjeta"


def test_contextualize_sin_historial_no_cambia_nada():
    assert contextualize("y como los cruzo con los clientes", []) == "y como los cruzo con los clientes"


def test_contextualize_pregunta_nueva_no_se_toca():
    pregunta = "¿dónde está el DUI del cliente?"
    assert contextualize(pregunta, ["donde estan los prestamos"]) == pregunta


def test_contextualize_ignora_historial_vacio():
    assert contextualize("y por agencia", ["", "   "]) == "y por agencia"


def test_contextualize_cadena_de_dos_seguimientos_llega_a_la_pregunta_original():
    historial = ["donde estan los prestamos", "y como los cruzo con los clientes"]
    texto = contextualize("y de esos cuantos estan en mora", historial)
    assert texto == "donde estan los prestamos y como los cruzo con los clientes y de esos cuantos estan en mora"


def test_contextualize_no_retrocede_mas_de_tres_turnos():
    historial = ["pregunta lejana", "y uno", "y dos", "y tres"]
    texto = contextualize("y cuatro", historial)
    assert "pregunta lejana" not in texto
    assert texto == "y uno y dos y tres y cuatro"


@pytest.mark.parametrize(
    ("pregunta", "esperado"),
    [
        ("y como los cruzo con los clientes", True),
        ("ahora lo mismo pero por agencia", True),
        ("de esos cuantos tienen prestamo", True),
        ("y esa fecha como la uno con el prestamo", True),
        ("¿dónde está el DUI del cliente?", False),
        ("que informacion hay de garantias?", False),
    ],
)
def test_is_follow_up(pregunta, esperado):
    assert is_follow_up(pregunta) is esperado


@pytest.mark.parametrize(
    ("pregunta", "esperado"),
    [
        ("cuantos clientes tienen prestamos activos?", True),
        ("saldo total de la cartera por agencia", True),
        ("donde esta el saldo total de la cuenta", False),  # «dónde está» pide el dato, no la cifra
        ("¿dónde está el DUI del cliente?", False),
    ],
)
def test_is_figures_question(pregunta, esperado):
    assert is_figures_question(pregunta) is esperado


# --- 4. Flujo con historial ----------------------------------------------------------------------------------------


def test_seguimiento_se_entiende_con_la_pregunta_anterior(bancos, todos):
    env = bancos.run("y como los cruzo con los clientes", todos, history=["donde estan los prestamos"])
    assert env.status == "ok"
    disc = env.discovery
    assert disc.candidates[0].asset_key == "BancaPrestamos.dbo.Prestamos"
    destinos = [p.tables for p in disc.join_paths]
    assert any(t[0] == "BancaPrestamos.dbo.Prestamos" and t[-1] == "BancaPrestamos.dbo.Clientes" for t in destinos)


def test_el_mismo_seguimiento_sin_historial_pierde_el_contexto(bancos, todos):
    """Contraste: sin la pregunta anterior el candidato principal ya no es Prestamos con su camino a Clientes."""
    env = bancos.run("y como los cruzo con los clientes", todos)
    ruta = [p.tables for p in env.discovery.join_paths] if env.discovery else []
    assert not any(t[0] == "BancaPrestamos.dbo.Prestamos" and t[-1] == "BancaPrestamos.dbo.Clientes" for t in ruta)


def test_pregunta_nueva_con_historial_no_arrastra_el_contexto(bancos, todos):
    con = bancos.run("donde esta el DUI del cliente", todos, history=["donde estan los prestamos"])
    sin = bancos.run("donde esta el DUI del cliente", todos)
    assert _claves(con) == _claves(sin)
    assert con.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Clientes.DUI"


def test_seguimiento_de_la_auditoria_conserva_la_pregunta_tal_como_se_escribio(bancos, todos):
    bancos.run("y como los cruzo con los clientes", todos, history=["donde estan los prestamos"])
    assert bancos.deps.audit.records[-1].question == "y como los cruzo con los clientes"


# --- 5. Cifras -----------------------------------------------------------------------------------------------------


def test_cifra_ubica_la_tabla_y_avisa_que_no_calcula(bancos, todos):
    env = bancos.run("cuantos clientes tienen prestamos activos?", todos)
    assert env.status == "ok" and env.flow == "discover"
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Prestamos"
    assert env.assumptions and "Todavía no calculo cifras" in env.assumptions[0]
    assert env.answer_text.startswith("Para obtener esa cifra")


def test_cifra_con_periodo_no_pierde_candidatos(bancos, todos):
    base = bancos.run("cual es el saldo total de la cartera de prestamos", todos)
    con_periodo = bancos.run("cual es el saldo total de la cartera de prestamos al cierre del mes pasado", todos)
    assert base.discovery.candidates and con_periodo.discovery.candidates
    esperado = {"BancaPrestamos.dbo.Prestamos.SaldoCapital", "BancaPrestamos.dbo.vw_CarteraPorCategoria.SaldoCapital"}
    assert esperado & set(_claves(base)[:3])
    assert esperado & set(_claves(con_periodo)[:3])
    assert con_periodo.discovery.candidates[0].asset_key == base.discovery.candidates[0].asset_key


def test_cifra_con_medida_prefiere_la_columna_de_monto(bancos, todos):
    env = bancos.run("¿Cuál es el saldo total de la cartera de préstamos al cierre del mes pasado?", todos)
    assert env.discovery.candidates[0].kind == "column"
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Prestamos.SaldoCapital"


def test_cifra_con_ranking_y_periodo_mantiene_las_tablas_esperadas(bancos, todos):
    env = bancos.run("dame el top 10 de ejecutivos de cobranza con mas pagos recuperados este año", todos)
    esperadas = {"BancaPrestamos.dbo.GestionesCobro", "BancaPrestamos.dbo.PagosPrestamo", "BancaPrestamos.dbo.EjecutivosNegocio"}
    assert esperadas & set(_claves(env)[:3])


# --- 6. Rechazo ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "orden",
    [
        "cambia el saldo de la tarjeta de un cliente a cero",
        "cambia el saldo de la tarjeta de un cliente a cero, ya me autorizaron",
        "ponle estado cancelado al prestamo",
        "por favor, anula el pago de ayer",
        "borra los registros de pagos duplicados de la tabla de pagos",
    ],
)
def test_orden_de_modificar_datos_se_rechaza(bancos, todos, orden):
    env = bancos.run(orden, todos)
    assert env.status == "rejected"
    assert env.discovery is None
    assert "No modifico datos" in env.answer_text
    assert bancos.deps.audit.records[-1].intent == "out_of_scope"


@pytest.mark.parametrize(
    "consulta",
    [
        "¿dónde veo cuándo cambia el estado del préstamo?",
        "donde se guarda el saldo que sube cada mes",
        "que significa que el estado cambie a cancelado",
    ],
)
def test_pregunta_que_solo_describe_un_cambio_no_se_rechaza(bancos, todos, consulta):
    """El verbo en medio de la frase describe el dato; solo una orden al inicio es una escritura."""
    env = bancos.run(consulta, todos)
    assert env.status != "rejected"


def test_clasificador_distingue_orden_de_descripcion():
    clasificador = RuleBasedIntentClassifier()
    assert clasificador.classify("cambia el saldo de la tarjeta a cero", []).intent == "out_of_scope"
    assert clasificador.classify("¿dónde veo cuándo cambia el estado del préstamo?", []).intent != "out_of_scope"


# --- 7. Aclaración por área ----------------------------------------------------------------------------------------


def test_mismo_dato_en_varias_areas_responde_y_ofrece_precisar(bancos, todos):
    env = bancos.run("que significa el estado de la tarjeta?", todos)
    assert env.status == "ok"
    assert env.discovery.candidates, "la aclaración no bloquea: también hay respuesta"
    assert env.clarification is not None
    assert len(env.clarification.options) >= 2
    assert all(o.startswith("que significa el estado de la tarjeta (") and o.endswith(")") for o in env.clarification.options)
    assert len(env.clarification.options) <= engine.MAX_AREA_OPTIONS


def test_dato_sin_rival_en_otra_area_no_pide_aclarar(bancos, todos):
    env = bancos.run("donde esta el DUI del cliente", todos)
    assert env.status == "ok"
    assert env.clarification is None


def test_area_options_directo(bancos, todos):
    env = bancos.run("que significa el estado de la tarjeta?", todos)
    opciones = engine.area_options("¿que significa el estado de la tarjeta?", env.discovery, bancos.deps.settings.discovery)
    assert len(opciones) >= 2
    assert opciones[0].startswith("que significa el estado de la tarjeta (")  # sin los signos de la pregunta
    assert len(set(opciones)) == len(opciones)


def test_area_options_vacio_si_no_hay_candidatos(bancos):
    from discovery_data_agent.models.discovery import Discovery

    assert engine.area_options("hola", Discovery(), bancos.deps.settings.discovery) == []


def test_area_options_vacio_si_el_principal_es_una_tabla(bancos, todos):
    env = bancos.run("cuantos clientes tienen prestamos activos?", todos)
    assert env.discovery.candidates[0].kind == "table"
    assert engine.area_options("cuantos clientes tienen prestamos activos?", env.discovery, bancos.deps.settings.discovery) == []


@pytest.mark.parametrize(
    ("nombre", "legible"),
    [("CuotasLeasing", "Cuotas Leasing"), ("vw_CarteraTarjetas", "Cartera Tarjetas"), ("Prestamos", "Prestamos")],
)
def test_humanize(nombre, legible):
    assert engine.humanize(nombre) == legible


def test_la_aclaracion_por_area_respeta_permisos(bancos):
    """F14: las opciones no nombran áreas de bases que el usuario no ve."""
    usuario = user_with_databases(bancos, "tarjetas", ["BancaTarjetasCredito"])
    env = bancos.run("que significa el estado de la tarjeta?", usuario)
    dump = env.model_dump_json(by_alias=True)
    for otra in ("BancaCuentasDebito", "BancaTokenizacion", "BancaPrestamos", "BancaLeasing"):
        assert otra not in dump
    if env.clarification:
        assert not any("debito" in o or "origen" in o or "tokens" in o for o in env.clarification.options)


# --- 8. Guía del modelo cuando no hay candidatos -------------------------------------------------------------------

SIN_RESULTADOS = "oye y quien gano el partido de la selecta ayer"


class GuiaFalsa:
    """Doble del puerto `Guide`: devuelve un consejo fijo, lanza una excepción y cuenta las llamadas."""

    def __init__(self, advice: Advice | None = None, error: Exception | None = None):
        self.advice, self.error, self.calls = advice, error, []

    def advise(self, question: str, history: list[str]) -> Advice:
        self.calls.append((question, list(history)))
        if self.error:
            raise self.error
        return self.advice


def _con_guia(monkeypatch, service, guia):
    monkeypatch.setattr(service.deps, "guide", guia)
    return guia


def test_la_pregunta_de_prueba_no_tiene_candidatos(bancos, todos):
    """Precondición de los casos de guía."""
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.discovery.candidates == [] and env.discovery.knowledge_gap


def test_guia_reconoce_un_tema_del_asistente(bancos, todos, monkeypatch):
    guia = _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="assistant", topic="freshness")))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert len(guia.calls) == 1
    assert env.status == "ok" and env.discovery is None
    assert env.answer_text == assistant.answer("freshness", bancos.deps.catalog, todos.visible_ids)
    assert not env.assumptions


def test_guia_con_tema_inexistente_se_ignora(bancos, todos, monkeypatch):
    _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="assistant", topic="inventado")))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.status == "ok"
    assert env.answer_text.startswith("No encontré datos disponibles para ti")


def test_guia_pasa_la_pregunta_original_y_el_historial(bancos, todos, monkeypatch):
    guia = _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="none")))
    bancos.run(SIN_RESULTADOS, todos, history=["donde estan los prestamos"])
    assert guia.calls == [(SIN_RESULTADOS, ["donde estan los prestamos"])]


def test_guia_que_aclara_deja_la_aclaracion_pendiente(bancos, todos, monkeypatch):
    advice = Advice(kind="clarify", question="¿Qué producto te interesa?",
                    options=["Los préstamos de consumo", "Las tarjetas de crédito"])
    _con_guia(monkeypatch, bancos, GuiaFalsa(advice))
    env = bancos.run(SIN_RESULTADOS, todos)
    # La aclaración acompaña a la respuesta "no encontré": ya no sustituye a la respuesta.
    assert env.status == "ok"
    assert env.discovery is not None and env.discovery.candidates == [] and env.discovery.knowledge_gap
    assert env.confidence == 0.0
    assert env.answer_text.startswith("No encontré datos disponibles para ti")
    assert env.answer_text.endswith("¿Qué producto te interesa?")
    assert env.clarification.options == ["Los préstamos de consumo", "Las tarjetas de crédito"]


@pytest.mark.parametrize(
    "opcion",
    [
        "Los datos de la tabla de préstamos",  # jerga: «tabla»
        "El campo ClienteID",  # CamelCase
        "Mira http://ejemplo.com/ayuda",  # enlace
        "BancaPrestamos.dbo.Clientes",  # referencia con puntos
        "Los datos de cartera_vencida",  # guion bajo
        "Los 3 productos nuevos",  # dígitos
    ],
)
def test_guia_descarta_opciones_con_aspecto_tecnico_o_enlaces(bancos, todos, monkeypatch, opcion):
    """La guarda es `looks_technical` + `unsafe_generated_text`: no depende del catálogo."""
    advice = Advice(kind="clarify", question="¿Cuál de estas?", options=[opcion, "Los pagos de la cartera"])
    _con_guia(monkeypatch, bancos, GuiaFalsa(advice))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.status == "ok"
    assert env.clarification.options == ["Los pagos de la cartera"]


@pytest.mark.parametrize("jerga", ["tabla", "columna", "campo", "base de datos", "esquema", "sql", "llave", "registro"])
def test_guia_descarta_opciones_con_jerga_tecnica(bancos, todos, monkeypatch, jerga):
    advice = Advice(kind="clarify", question="¿Cuál?", options=[f"Quiero ver la {jerga} de pagos", "Los pagos de la cartera"])
    _con_guia(monkeypatch, bancos, GuiaFalsa(advice))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.clarification.options == ["Los pagos de la cartera"]


def test_guia_trata_igual_una_tabla_oculta_que_un_nombre_inventado(bancos, monkeypatch):
    """F14: la guarda no consulta el catálogo. Para quien solo ve BancaLeasing, una opción con el nombre de una tabla
    que existe pero no ve y otra con un nombre inventado reciben el MISMO trato; si no, que una opción aparezca o no
    delataría que la tabla existe."""
    usuario = user_with_databases(bancos, "leasing", ["BancaLeasing"])
    pares = [
        ("Los datos de Prestamos", "Los datos de Zorzales"),  # nombre simple: ninguno es técnico
        ("Los datos de PagosPrestamo", "Los datos de PagosInventado"),  # CamelCase: los dos se descartan
        ("Los datos de vw_CarteraPorCategoria", "Los datos de vw_Inventada"),  # guion bajo: los dos se descartan
        ("Los datos de BancaPrestamos.dbo.Clientes", "Los datos de BancaFantasma.dbo.Nada"),  # referencia con puntos
    ]
    for oculta, inventada in pares:
        assert engine.looks_technical(oculta) == engine.looks_technical(inventada), (oculta, inventada)
        assert engine.unsafe_generated_text(oculta) == engine.unsafe_generated_text(inventada)
        resultados = []
        for opcion in (oculta, inventada):
            _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="clarify", question="¿Cuál?",
                                                          options=[opcion, "Los contratos vigentes"])))
            env = bancos.run(SIN_RESULTADOS, usuario)
            resultados.append(opcion in (env.clarification.options if env.clarification else []))
        assert resultados[0] == resultados[1], (oculta, inventada)


@pytest.mark.parametrize("pregunta", ["¿Hablas de la tabla de préstamos?", "Mira https://ejemplo.com", "¿Es el campo ClienteID?",
                                      "¿Te refieres a BancaPrestamos.dbo.Clientes?"])
def test_guia_descarta_una_aclaracion_cuya_pregunta_es_insegura(bancos, todos, monkeypatch, pregunta):
    _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="clarify", question=pregunta, options=["Los pagos de la cartera"])))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.status == "ok" and env.clarification is None
    assert env.answer_text.startswith("No encontré datos disponibles para ti")


def test_guia_con_todas_las_opciones_inseguras_responde_como_sin_guia(bancos, todos, monkeypatch):
    advice = Advice(kind="clarify", question="¿Cuál?", options=["Mira http://x.com", "La tabla de préstamos", "El campo ClienteID"])
    _con_guia(monkeypatch, bancos, GuiaFalsa(advice))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.status == "ok" and env.clarification is None
    assert env.discovery.candidates == []


def test_guia_que_elige_un_tema_se_audita_con_intent_assistant(bancos, todos, monkeypatch):
    _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="assistant", topic="freshness")))
    env = bancos.run(SIN_RESULTADOS, todos)
    registro = bancos.deps.audit.records[-1]
    assert registro.trace_id == env.trace_id
    assert registro.intent == "assistant"


def test_guia_que_lanza_excepcion_responde_normal_y_lo_registra(bancos, todos, monkeypatch):
    _con_guia(monkeypatch, bancos, GuiaFalsa(error=TimeoutError("sin respuesta")))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.status == "ok"
    assert env.discovery.candidates == [] and env.discovery.knowledge_gap
    assert env.answer_text.startswith("No encontré datos disponibles para ti")
    respond = [s for s in bancos.deps.audit.records[-1].steps if s.step == "respond"][0]
    assert respond.error == "fallback:TimeoutError"


def test_guia_no_se_consulta_si_hay_candidatos(bancos, todos, monkeypatch):
    guia = _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="assistant", topic="freshness")))
    env = bancos.run("donde esta el DUI del cliente", todos)
    assert guia.calls == []
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Clientes.DUI"


def test_guia_no_se_consulta_si_la_pregunta_ya_es_del_asistente(bancos, todos, monkeypatch):
    guia = _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="assistant", topic="identity")))
    env = bancos.run("que puedes hacer?", todos)
    assert guia.calls == []
    assert env.answer_text == assistant.answer("capabilities", bancos.deps.catalog, todos.visible_ids)


def test_guia_tampoco_ve_el_catalogo_de_otros(bancos, monkeypatch):
    """F14: con un usuario sin acceso la guía puede proponer una aclaración, pero nada fuera de su visibilidad aparece."""
    usuario = user_with_databases(bancos, "leasing", ["BancaLeasing"])
    advice = Advice(kind="clarify", question="¿Qué producto?", options=["Los contratos vigentes"])
    _con_guia(monkeypatch, bancos, GuiaFalsa(advice))
    env = bancos.run(SIN_RESULTADOS, usuario)
    dump = env.model_dump_json(by_alias=True)
    assert not any(db in dump for db in OTRAS_BASES)


# --- 9. join_sentence y narrativa de plantilla ---------------------------------------------------------------------


def test_join_sentence_con_llave_foranea():
    assert join_sentence(["BancaPrestamos.dbo.Prestamos → BancaPrestamos.dbo.Clientes (fk: ClienteID)"]) == \
        "Prestamos → Clientes (por ClienteID)"


def test_join_sentence_con_varios_saltos_y_tipos():
    texto = join_sentence([
        "BancaPrestamos.dbo.CuotasPrestamo → BancaPrestamos.dbo.Prestamos (fk: PrestamoID)",
        "BancaPrestamos.dbo.Prestamos → BancaPrestamos.dbo.Clientes (fk: ClienteID)",
        "BancaPrestamos.dbo.Clientes → BancaLeasing.dbo.Clientes (same_entity)",
        "BancaPrestamos.dbo.Prestamos → BancaPrestamos.dbo.vw_CarteraPorCategoria (view)",
    ])
    assert texto == (
        "CuotasPrestamo → Prestamos (por PrestamoID), Prestamos → Clientes (por ClienteID), "
        "Clientes → Clientes (el mismo dato en otro sistema), Prestamos → vw_CarteraPorCategoria (vista que lo resume)"
    )


def test_join_sentence_deja_pasar_un_paso_con_otro_formato():
    assert join_sentence(["un paso raro"]) == "un paso raro"
    assert join_sentence([]) == ""


def test_narrativa_de_plantilla_con_camino_de_union_es_valida(bancos, todos):
    env = bancos.run("y como los cruzo con los clientes", todos, history=["donde estan los prestamos"])
    disc = env.discovery
    assert disc.join_paths
    texto = TemplateNarrator().narrate("como los cruzo con los clientes", disc)
    assert "Se cruza así: Prestamos → Clientes (por ClienteID)" in texto
    assert engine.narrative_mentions_ok(texto, disc, bancos.deps.catalog)
    assert env.answer_text and engine.narrative_mentions_ok(env.answer_text, disc, bancos.deps.catalog)


def test_narrativa_sin_camino_de_union_no_dice_se_cruza(bancos, todos):
    env = bancos.run("donde esta el DUI del cliente", todos)
    if not env.discovery.join_paths:
        assert "Se cruza así" not in env.answer_text


def test_narrativa_de_cifras_empieza_distinto_que_la_de_localizar(bancos, todos):
    cifra = bancos.run("cuantos clientes tienen prestamos activos?", todos)
    dato = bancos.run("donde esta el DUI del cliente", todos)
    assert cifra.answer_text.startswith("Para obtener esa cifra, la información está en")
    assert dato.answer_text.startswith("Lo más cercano a lo que buscas es")


# --- 10. Compuerta del set chat.yaml -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def informe(bancos):
    return evaluate(bancos, load_cases(BANCOS / "eval" / "chat.yaml"))


def test_chat_yaml_hit_at_1(informe):
    """Medido el 2026-11-23: 97,8 % (solo falla L09)."""
    assert informe.metrics["hit@1"] >= 95.0, informe.render()


def test_chat_yaml_hit_at_3(informe):
    """Medido el 2026-11-23: 100 %."""
    assert informe.metrics["hit@3"] >= 97.0, informe.render()


@pytest.mark.parametrize("tipo", ["M", "R", "G", "K", "X"])
def test_chat_yaml_tipos_conductuales_y_de_conversacion_al_cien(informe, tipo):
    fila = informe.by_type()[tipo]
    assert fila["ok"] == 100.0, informe.render()


def test_chat_yaml_los_casos_que_aun_fallan_son_solo_los_conocidos(informe):
    """Solo L09 falla; si falla otro caso, la compuerta de arriba puede seguir en verde y esto avisa."""
    assert informe.by_type()["L"]["ok"] >= 88.0, informe.render()
    assert informe.metrics["hit@1"] >= 97.0, informe.render()


def test_chat_yaml_sin_fugas_ni_inventados(informe):
    assert informe.metrics["leaks"] == 0, informe.render()
    assert informe.metrics["invented"] == 0, informe.render()


def test_chat_yaml_cubre_todos_los_tipos_de_chat(informe):
    assert set(informe.by_type()) >= {"F", "L", "S", "X", "E", "K", "M", "R", "G"}


def test_chat_yaml_los_seguimientos_encuentran_las_tablas_relacionadas(informe):
    fila = informe.by_type()["K"]
    assert fila["related"] == 100.0, informe.render()


@pytest.mark.parametrize("opcion", ["Escríbenos a ayuda@banco.com", "  ", "Visita www.banco.com"])
def test_guia_descarta_correos_vacias_y_dominios(bancos, todos, monkeypatch, opcion):
    advice = Advice(kind="clarify", question="¿Cuál?", options=[opcion, "Los pagos de la cartera"])
    _con_guia(monkeypatch, bancos, GuiaFalsa(advice))
    env = bancos.run(SIN_RESULTADOS, todos)
    assert env.clarification.options == ["Los pagos de la cartera"]


# --- 11. Preguntas de datos que no son del asistente (reglas de segunda persona) -----------------------------------

SON_DE_DATOS = [
    "¿Qué sistemas operativos hay en los dispositivos registrados?",
    "¿Qué fuentes de ingreso hay registradas para los clientes?",
    "¿Qué es el porcentaje de uso de la tarjeta?",
    "¿Qué significa la confianza del dispositivo?",
    "¿Cómo funciona el pago mínimo?",
    "Ok, el email del cliente",
    "Perfecto, ahora necesito el teléfono del arrendatario",
    "¿Cómo se corrige un pago mal aplicado?",
    "¿Dónde puedes ver los datos de contacto de los clientes?",
]


@pytest.mark.parametrize("pregunta", SON_DE_DATOS)
def test_topic_of_no_toma_por_asistente_estas_preguntas_de_datos(pregunta):
    assert assistant.topic_of(pregunta) is None


def test_ok_el_email_del_cliente_encuentra_la_columna_email(bancos, todos):
    env = bancos.run("Ok, el email del cliente", todos)
    assert env.status == "ok" and env.discovery is not None
    claves = [c.asset_key for c in env.discovery.candidates]
    assert "BancaPrestamos.dbo.Clientes.Email" in claves
    assert any(k.endswith(".Clientes.Email") for k in claves[:1])


# --- 12. Seguimiento: el conector solo no basta ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pregunta", "esperado"),
    [
        ("y dónde está el DUI del cliente", False),  # conector + contenido propio: pregunta nueva
        ("¿y en leasing?", True),
        ("ahora por agencia", True),
        ("y de esos cuántos tienen tarjeta", True),  # anáfora
        ("y lo mismo pero por agencia", True),
        ("y cómo los cruzo con los clientes", True),
        # un conector seguido de «qué significa / qué quiere decir» pregunta por algo de lo que se hablaba
        ("y que significa el estado de la gestion", True),
        ("¿Y qué quiere decir la mora?", True),
        ("pero que significa estado de la gestion de cobro", True),
        ("ahora que quiere decir el saldo capital", True),
        # sin conector, la misma frase es una pregunta nueva
        ("que significa el estado de la gestion", False),
        ("¿Qué quiere decir la mora?", False),
        ("y el estado de la gestion de cobro", False),
    ],
)
def test_is_follow_up_conector_solo_no_basta_si_hay_contenido(pregunta, esperado):
    assert is_follow_up(pregunta) is esperado


def test_contextualize_conector_con_contenido_propio_es_pregunta_nueva():
    pregunta = "y dónde está el DUI del cliente"
    assert contextualize(pregunta, ["cuántos contratos de leasing hay"]) == pregunta


def test_contextualize_conector_con_poco_contenido_es_seguimiento():
    texto = contextualize("¿y en leasing?", ["cuantos clientes tienen prestamos"])
    assert texto.startswith("cuantos clientes tienen prestamos") and texto.endswith("¿y en leasing?")


def test_pregunta_con_conector_y_contenido_propio_encuentra_su_dato_tras_leasing(bancos, todos):
    env = bancos.run("y dónde está el DUI del cliente", todos, history=["cuantos contratos de leasing hay"])
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Clientes.DUI"
    detalle = [s.detail for s in bancos.deps.audit.records[-1].steps if s.step == "intent"][0]
    assert not (detalle or "").startswith("seguimiento:")


def test_seguimiento_con_anafora_sigue_siendolo_aunque_traiga_contenido(bancos, todos):
    assert is_follow_up("de esos cuantos tienen tarjeta de credito")
    assert is_follow_up("lo mismo para los contratos de leasing")


def test_el_paso_intent_de_un_seguimiento_lleva_detalle_seguimiento(bancos, todos):
    bancos.run("y como los cruzo con los clientes", todos, history=["donde estan los prestamos"])
    intent = [s for s in bancos.deps.audit.records[-1].steps if s.step == "intent"][0]
    assert intent.detail and intent.detail.startswith("seguimiento:")


def test_el_paso_intent_de_una_pregunta_nueva_no_lleva_detalle_de_seguimiento(bancos, todos):
    bancos.run("donde esta el DUI del cliente", todos, history=["donde estan los prestamos"])
    intent = [s for s in bancos.deps.audit.records[-1].steps if s.step == "intent"][0]
    assert not (intent.detail or "").startswith("seguimiento:")


# --- 13. Rechazo de escrituras con historial ------------------------------------------------------------------------


def test_orden_de_escritura_con_historial_se_rechaza(bancos, todos):
    env = bancos.run("cambia el estado de esos prestamos a cancelado", todos, history=["donde esta el estado del prestamo"])
    assert env.status == "rejected"
    assert env.discovery is None
    assert bancos.deps.audit.records[-1].intent == "out_of_scope"


def test_seguimiento_legitimo_tras_pregunta_de_borrado_no_se_rechaza(bancos, todos):
    """El historial lo envía el cliente: una pregunta sobre «quién puede borrar» no contagia al seguimiento."""
    env = bancos.run("y de esos cual es la fecha", todos, history=["quien puede borrar los pagos"])
    assert env.status != "rejected"


def test_historial_con_orden_de_escritura_no_rechaza_una_pregunta_limpia(bancos, todos):
    env = bancos.run("donde esta el DUI del cliente", todos, history=["borra los pagos duplicados"])
    assert env.status == "ok"


# --- 14. Términos de análisis y conceptos --------------------------------------------------------------------------


def test_kept_analysis_terms_conserva_total_en_monto_total(bancos, todos):
    assert "total" in engine.kept_analysis_terms("monto total del pago", bancos.deps.catalog, todos.visible_ids)


def test_monto_total_del_pago_tiene_como_principal_montototal(bancos, todos):
    env = bancos.run("monto total del pago", todos)
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.PagosPrestamo.MontoTotal"


def test_activo_arrendado_no_se_toma_como_adjetivo_de_estado():
    conceptos = expansion.concepts_of("¿Dónde está el tipo de activo arrendado?", True)
    assert frozenset({"activo"}) in conceptos
    assert not any("estado" in c or "statu" in c for c in conceptos)


def test_activo_como_adjetivo_si_aporta_estado():
    """Contraste: «activos» como situación sí se traduce a estado."""
    conceptos = expansion.concepts_of("cuales son los prestamos activos", True)
    assert any("estado" in c for c in conceptos)


# --- 15. Seguimiento «y qué significa…», pista de tipo y ranking ---------------------------------------------------


def test_y_que_significa_el_estado_se_entiende_con_la_pregunta_anterior():
    texto = contextualize("y que significa el estado de la gestion", ["donde estan las gestiones de cobro"])
    assert texto.startswith("donde estan las gestiones de cobro")
    assert texto.endswith("y que significa el estado de la gestion")


def test_que_significa_sin_conector_no_arrastra_la_pregunta_anterior():
    pregunta = "que significa el estado de la gestion"
    assert contextualize(pregunta, ["donde estan los prestamos"]) == pregunta


def test_el_paso_intent_de_y_que_significa_lleva_detalle_seguimiento(bancos, todos):
    bancos.run("y que significa el estado de la gestion", todos, history=["donde estan las gestiones de cobro"])
    intent = [s for s in bancos.deps.audit.records[-1].steps if s.step == "intent"][0]
    assert intent.detail and intent.detail.startswith("seguimiento:")


@pytest.mark.parametrize(
    ("pregunta", "intencion", "pista"),
    [
        ("que es la fecha de corte en las tablas de saldos", "discovery", "column"),
        ("que significa el estado de las tablas", "discovery", "column"),
        ("que quiere decir la mora en las tablas de cobro", "discovery", "column"),
        ("que es una tabla", "discovery", "table"),  # sin artículo definido no es un dato concreto
        ("que tablas hay", "discovery", "table"),
        ("que es la fecha en las tablas", "exploration", "table"),  # otra intención no se toca
    ],
)
def test_kind_hint_que_es_el_dato_pide_columna_aunque_diga_tablas(pregunta, intencion, pista):
    from discovery_data_agent.discovery.deterministic import _kind_hint

    assert _kind_hint(pregunta, intencion) == pista


def _borrador(clave, tipo, relevancia, **kw):
    return engine.Draft(asset_key=clave, kind=tipo, relevance=relevancia, **kw)


def _intencion(pista):
    from discovery_data_agent.models.intent import IntentResult

    return IntentResult(intent="discovery", asset_kind_hint=pista, rewritten_question="x", confidence=0.5)


def test_fix_candidate_promueve_la_tabla_del_mejor_dato_si_se_pidio_una_tabla_y_solo_hay_columnas(bancos):
    """Se pidió una tabla y la revisión solo encuentra columnas: la tabla de la mejor columna es el mejor punto de partida."""
    ajustes = bancos.deps.settings.discovery
    columna = _borrador("B.dbo.T.Col", "column", 0.9)
    tabla = _borrador("B.dbo.T", "table", 0.1)  # por debajo de la relevancia mínima: el primer recorrido la salta
    otra = _borrador("B.dbo.U.Otra", "column", 0.8)
    elegido = engine.fix_candidate([columna, otra, tabla], columna.asset_key, _intencion("table"), ajustes)
    assert elegido is tabla


def test_fix_candidate_sin_tabla_en_el_ranking_no_inventa_una(bancos):
    ajustes = bancos.deps.settings.discovery
    columna = _borrador("B.dbo.T.Col", "column", 0.9)
    otra = _borrador("B.dbo.U.Otra", "column", 0.8)
    assert engine.fix_candidate([columna, otra], columna.asset_key, _intencion("table"), ajustes) is None


def test_fix_candidate_si_el_principal_ya_es_tabla_no_promueve_nada(bancos):
    ajustes = bancos.deps.settings.discovery
    tabla = _borrador("B.dbo.T", "table", 0.9)
    columna = _borrador("B.dbo.T.Col", "column", 0.8)
    assert engine.fix_candidate([tabla, columna], tabla.asset_key, _intencion("table"), ajustes) is None


def test_fix_candidate_prefiere_una_tabla_que_si_cumple_antes_que_la_de_la_columna(bancos):
    ajustes = bancos.deps.settings.discovery
    columna = _borrador("B.dbo.T.Col", "column", 0.9)
    buena = _borrador("B.dbo.V", "table", 0.8)
    propia = _borrador("B.dbo.T", "table", 0.1)
    assert engine.fix_candidate([columna, buena, propia], columna.asset_key, _intencion("table"), bancos.deps.settings.discovery) is buena
    assert ajustes.min_relevance > 0.1


def test_promote_deja_primero_al_elegido_por_la_revision_aunque_otro_lo_supere(bancos):
    ajustes = bancos.deps.settings.discovery
    perdedor = _borrador("B.dbo.T.C", "column", 0.9, retrieval_norm=1.0, sources={"catalog", "vector"})
    rival = _borrador("B.dbo.T.F", "column", 0.95, retrieval_norm=1.0, sources={"catalog", "vector", "rerank"})
    ganador = _borrador("B.dbo.T.E", "column", 0.5, retrieval_norm=0.2, sources={"catalog"})
    ranking = engine.rank([perdedor, rival, ganador], ajustes)
    nuevo = engine.promote(ranking, ganador, perdedor, "la revisión lo prefiere", ajustes)
    assert nuevo[0] is ganador
    assert {d.asset_key for d in nuevo} == {"B.dbo.T.C", "B.dbo.T.F", "B.dbo.T.E"}
    assert ganador.confidence <= max(d.confidence for d in nuevo), "nunca con más confianza de la que encabezaba"
    assert ganador.why == "la revisión lo prefiere"
    assert perdedor is not nuevo[0] and perdedor.relevance < 0.9


def test_promote_el_elegido_siempre_alcanza_la_relevancia_minima(bancos):
    ajustes = bancos.deps.settings.discovery
    perdedor = _borrador("B.dbo.T.C", "column", 0.2, retrieval_norm=1.0, sources={"catalog"})
    ganador = _borrador("B.dbo.T", "table", 0.0, sources={"catalog"})
    engine.promote(engine.rank([perdedor, ganador], ajustes), ganador, perdedor, "revision", ajustes)
    assert ganador.relevance >= ajustes.min_relevance


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿Dónde está el saldo del préstamo y el email del cliente?",
        "¿Dónde está el monto de los pagos de préstamo y el nombre del cliente?",
    ],
)
def test_el_destino_de_la_subpregunta_es_la_tabla_que_se_llama_como_lo_pedido(bancos, todos, pregunta):
    """«El cliente» lleva a `Clientes`, no a otra tabla que solo apunta a ella con `ClienteID`."""
    env = bancos.run(pregunta, todos)
    destinos = [p.tables[-1] for p in env.discovery.join_paths]
    assert destinos and destinos[0] == "BancaPrestamos.dbo.Clientes", destinos


# --- 16. Los literales no llegan a los modelos (F17) ---------------------------------------------------------------

DUI = "01234567-8"
CUENTA = "0012345678901"


class ExpansorEspia:
    """Doble del puerto `QueryExpander`: guarda lo que recibe y no propone nada."""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def expand(self, question: str, weak_terms: list[str]) -> list[str]:
        self.calls.append((question, list(weak_terms)))
        return []


def _recibido(llamadas) -> str:
    return " | ".join(str(x) for llamada in llamadas for x in llamada)


def test_el_expansor_no_recibe_el_dui_ni_la_cuenta_de_la_pregunta(bancos, todos, monkeypatch):
    espia = ExpansorEspia()
    monkeypatch.setattr(bancos.deps, "expander", espia)
    pregunta = f"oye y quien gano el partido de la selecta, DUI {DUI} y cuenta {CUENTA}"
    bancos.run(pregunta, todos)
    assert espia.calls, "la precondición: la búsqueda cubrió poco y el expansor fue consultado"
    recibido = _recibido(espia.calls)
    assert DUI not in recibido and CUENTA not in recibido
    assert "01234567" not in recibido and "0012345678" not in recibido


def test_el_expansor_no_recibe_literales_del_historial_en_un_seguimiento(bancos, todos, monkeypatch):
    espia = ExpansorEspia()
    monkeypatch.setattr(bancos.deps, "expander", espia)
    historial = [f"el cliente con DUI {DUI} y la cuenta {CUENTA}"]
    bancos.run("y quien gano el partido de la selecta ayer", todos, history=historial)
    recibido = _recibido(espia.calls)
    assert DUI not in recibido and CUENTA not in recibido


def test_la_guia_no_recibe_el_dui_ni_la_cuenta_de_la_pregunta(bancos, todos, monkeypatch):
    guia = _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="none")))
    pregunta = f"xyzzy plugh DUI {DUI} cuenta {CUENTA}"
    bancos.run(pregunta, todos)
    assert len(guia.calls) == 1, "la precondición: sin candidatos, la guía fue consultada"
    recibido = _recibido(guia.calls)
    assert DUI not in recibido and CUENTA not in recibido
    assert "01234567" not in recibido and "0012345678" not in recibido


def test_la_guia_no_recibe_literales_del_historial(bancos, todos, monkeypatch):
    guia = _con_guia(monkeypatch, bancos, GuiaFalsa(Advice(kind="none")))
    historial = [f"mi DUI es {DUI}", f"la cuenta {CUENTA} del cliente"]
    bancos.run(SIN_RESULTADOS, todos, history=historial)
    [(pregunta, recibido_historial)] = guia.calls
    assert DUI not in pregunta and CUENTA not in pregunta
    assert recibido_historial and not any(DUI in h or CUENTA in h for h in recibido_historial)
    assert recibido_historial[0].startswith("mi DUI es")  # se quita el literal, no el resto del texto


def test_la_pregunta_con_literales_se_audita_tal_como_se_escribio_pero_no_llega_al_modelo(bancos, todos, monkeypatch):
    """El literal vive solo en la auditoría (D2 on-premise); ningún puerto con LLM lo ve."""
    espia, guia = ExpansorEspia(), GuiaFalsa(Advice(kind="none"))
    monkeypatch.setattr(bancos.deps, "expander", espia)
    monkeypatch.setattr(bancos.deps, "guide", guia)
    pregunta = f"xyzzy plugh DUI {DUI} cuenta {CUENTA}"
    bancos.run(pregunta, todos)
    assert bancos.deps.audit.records[-1].question == pregunta
    assert DUI not in _recibido(espia.calls + guia.calls) and CUENTA not in _recibido(espia.calls + guia.calls)
