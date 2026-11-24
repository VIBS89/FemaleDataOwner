"""GraphRAG sobre el catálogo que el agente descubrió de BancosSQL (fixture `tests/fixtures/bancos`, solo metadatos)."""

from pathlib import Path

import pytest

from discovery_data_agent.bootstrap import build_service, build_service_with_knowledge, user_with_databases
from discovery_data_agent.discovery import engine
from discovery_data_agent.discovery.deterministic import RuleBasedIntentClassifier
from discovery_data_agent.discovery.expansion import decompose, plan_query
from discovery_data_agent.evaluation.discovery_eval import evaluate, load_cases
from discovery_data_agent.models.identity import UserContext

BANCOS = Path(__file__).parent / "fixtures" / "bancos"


@pytest.fixture(scope="module")
def bancos():
    return build_service(BANCOS)


@pytest.fixture(scope="module")
def everyone(bancos):
    return user_with_databases(bancos, "dev", None)


def test_entidad_cliente_en_cuatro_bds(bancos, everyone):
    graph = bancos.deps.graph
    copies = graph.copies("BancaTarjetasCredito.dbo.Clientes.DUI", everyone.visible_ids)
    assert copies[0] == "BancaPrestamos.dbo.Clientes.DUI"  # canónica primero
    assert len(copies) == 4


def test_camino_de_union_respeta_permisos(bancos, everyone):
    graph = bancos.deps.graph
    path = graph.join_path("BancaPrestamos.dbo.CuotasPrestamo", "BancaPrestamos.dbo.Clientes", everyone.visible_ids)
    assert [(e.kind, e.detail) for e in path] == [("fk", "PrestamoID"), ("fk", "ClienteID")]
    sin_prestamos = frozenset(i for i in everyone.visible_ids if ".Prestamos" not in i)  # no ve la tabla puente
    assert graph.join_path("BancaPrestamos.dbo.CuotasPrestamo", "BancaPrestamos.dbo.Clientes", sin_prestamos) is None


def test_una_sola_respuesta_por_dato_de_la_entidad(bancos, everyone):
    env = bancos.run("¿Dónde está el DUI del cliente?", everyone)
    top = env.discovery.candidates[0]
    assert top.asset_key == "BancaPrestamos.dbo.Clientes.DUI"
    assert set(top.copies) == {f"Banca{db}.dbo.Clientes.DUI" for db in ("CuentasDebito", "TarjetasCredito", "Tokenizacion")}
    shown = [c.asset_key for c in env.discovery.candidates] + [a.asset_key for a in env.discovery.alternatives]
    assert not [k for k in shown if k.endswith("Clientes.DUI") and k != top.asset_key]


def test_pregunta_compuesta_trae_el_camino(bancos, everyone):
    env = bancos.run("¿Dónde están los días de mora de las cuotas de préstamo y el DUI del cliente?", everyone)
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.CuotasPrestamo.DiasMora"
    path = env.discovery.join_paths[0]
    assert path.tables == ["BancaPrestamos.dbo.CuotasPrestamo", "BancaPrestamos.dbo.Prestamos", "BancaPrestamos.dbo.Clientes"]


def test_descomposicion():
    assert decompose("¿Dónde está el saldo de la cuenta y el nombre de la agencia?") == [
        "donde esta el saldo de la cuenta", "el nombre de la agencia"]
    assert decompose("¿Qué tipo de dispositivo usa el cliente?") == ["¿Qué tipo de dispositivo usa el cliente?"]
    plan = plan_query("¿Dónde están los días de mora de las cuotas y el DUI del cliente?", None, True, 0.8)
    assert plan.primary_concepts and plan.secondary_parts


def test_regresion_por_tipo_de_pregunta(bancos):
    """Umbrales medidos con el catálogo crudo (sin descripciones). Si bajan, algo empeoró."""
    report = evaluate(bancos, load_cases(BANCOS / "eval" / "discovery.yaml"))
    by_type = report.by_type()
    assert by_type["A"]["hit@1"] == 100.0
    assert by_type["D"]["hit@1"] == 100.0 and by_type["D"]["dups"] == 0
    assert by_type["C"]["related"] == 100.0 and by_type["C"]["hit@1"] >= 80.0
    assert by_type["G"]["ok"] == 100.0
    assert report.metrics["leaks"] == 0 and report.metrics["invented"] == 0


def test_sin_grafo_hay_duplicados_y_sin_caminos(bancos):
    """Ablación: el mismo set sin el patrón `graph` muestra para qué sirve el grafo."""
    bancos.deps.settings.patterns.graph = False
    try:
        report = evaluate(bancos, load_cases(BANCOS / "eval" / "discovery.yaml"))
    finally:
        bancos.deps.settings.patterns.graph = True
    assert report.by_type()["D"]["hit@1"] < 100.0
    assert report.by_type()["C"]["related"] < 100.0


# --- preguntas compuestas a medio responder ---------------------------------------------------------

CARDS_Q = "¿Cómo relaciono los clientes con sus tarjetas de crédito?"


def test_parte_sin_resolver_baja_la_confianza_a_brecha(service, analyst):
    """VBank no tiene tarjetas: "clientes" se encuentra, "sus tarjetas de crédito" no. No puede salir con 85 %."""
    env = service.run(CARDS_Q, analyst)
    disc = env.discovery
    assert disc.knowledge_gap is True
    assert all(c.confidence < 0.6 for c in disc.candidates)
    assert any("tarjetas" in a for a in env.assumptions)


def test_parte_resuelta_por_el_grafo_conserva_la_confianza(bancos, everyone):
    env = bancos.run(CARDS_Q, everyone)
    assert env.discovery.join_paths and env.discovery.join_paths[0].tables[-1] == "BancaTarjetasCredito.dbo.TarjetasCredito"
    assert env.discovery.knowledge_gap is False


# --- preguntas por una entidad y preguntas de cruce (2026-11-17) -----------------------------------------
def _hint(service, user, question):
    intent = service.deps.intent_classifier.classify(question, [])
    return engine.entity_kind_hint(question, intent, service.deps.catalog, user.visible_ids) or intent.asset_kind_hint


def test_un_plural_que_nombra_una_tabla_pide_la_tabla(bancos, everyone):
    assert _hint(bancos, everyone, "¿Dónde están los arrendamientos financieros de vehículos?") == "table"
    assert _hint(bancos, everyone, "¿Dónde están los cajeros automáticos de San Salvador?") == "table"
    # El plural no basta: "días" o "montos" no son tablas, y lo que no existe en el catálogo no se adivina.
    assert _hint(bancos, everyone, "¿Dónde están los días de mora del préstamo?") is None
    assert _hint(bancos, everyone, "¿Dónde están las inversiones en bolsa del cliente?") is None
    # Tampoco si una columna se llama así ("pagos mínimos" es `PagoMinimo`, no la tabla de pagos), ni en una pregunta
    # compuesta, que además pide un dato concreto.
    assert _hint(bancos, everyone, "¿Dónde están los pagos mínimos de las tarjetas de crédito?") is None
    assert _hint(bancos, everyone, "¿Dónde están las cuotas mensuales de los préstamos?") is None
    assert _hint(bancos, everyone, "¿Dónde están las transacciones rechazadas y su motivo?") is None
    # Lo decide lo que el usuario ve (F14): sin acceso a BancaLeasing, "arrendamientos" no nombra ninguna tabla suya.
    only_loans = user_with_databases(bancos, "prestamos", ["BancaPrestamos"])
    assert _hint(bancos, only_loans, "¿Dónde están los arrendamientos financieros de vehículos?") is None


def test_una_pregunta_de_cruce_pide_tablas():
    classify = RuleBasedIntentClassifier().classify
    for question in ("¿Cómo relaciono las transacciones de tarjeta con el DUI del cliente?",
                     "¿Cómo cruzo los préstamos con sus garantías?", "¿Cómo se relacionan los tokens con los dispositivos?",
                     "¿Cómo uno las cuotas con los arrendatarios?"):
        assert classify(question, []).asset_kind_hint == "table", question
    assert classify("¿Dónde está el saldo de la cuenta?", []).asset_kind_hint == "column"
    # "Cada uno de" no es un cruce, y quien pregunta con qué campo se cruza pide la columna.
    assert classify("¿Dónde está el saldo de cada uno de los clientes?", []).asset_kind_hint == "column"
    assert classify("¿Con qué campo cruzo las tarjetas de crédito con los clientes?", []).asset_kind_hint == "column"


def test_un_calificativo_que_nadie_conoce_pesa_menos_pero_la_entidad_no():
    leasing, financ, vehiculo = frozenset({"leasin"}), frozenset({"financ"}), frozenset({"vehicu"})
    known = [{"leasin", "contra"}, {"financ", "monto"}]
    assert engine.qualifier_weights([leasing, financ, vehiculo], known) == [1.0, 1.0, engine.UNKNOWN_QUALIFIER_WEIGHT]
    # La entidad que se pide nunca se descuenta: si nadie la conoce, es una brecha y no una respuesta segura.
    assert engine.qualifier_weights([vehiculo, leasing], known) == [1.0, 1.0]
    weights = [1.0, 1.0, 0.25]
    assert engine.weighted_coverage([leasing, financ, vehiculo], {"leasin"}, {"financ"}, weights) == pytest.approx(1.5 / 2.25)
    assert engine.weighted_coverage([leasing, financ, vehiculo], {"leasin"}, set()) == pytest.approx(1 / 3)


def test_una_entidad_con_calificativos_desconocidos_se_responde_con_confianza_baja(bancos, everyone):
    """El catálogo no guarda valores (F1): no puede conocer "de vehículos". Muestra la tabla, sin presumir."""
    env = bancos.run("¿Dónde están los arrendamientos financieros de vehículos?", everyone, client="api")
    top = env.discovery.candidates[0]
    assert top.asset_key in ("BancaLeasing.dbo.ContratosLeasing", "BancaLeasing.dbo.vw_CarteraLeasing")
    assert all(c.kind != "column" for c in env.discovery.candidates)
    assert top.confidence < 0.6 and env.discovery.knowledge_gap  # se ofrece preguntar al responsable


def test_lo_que_el_banco_no_tiene_nunca_sale_como_respuesta_segura(bancos, everyone):
    """"Tarjetas de regalo": hay tarjetas, pero no de regalo. El catálogo no distingue ese caso del anterior, así que
    una respuesta que descontó calificativos queda siempre bajo el umbral de brecha, con la confirmación que tenga."""
    env = bancos.run("¿Dónde están las tarjetas de regalo?", everyone, client="api")
    assert env.discovery.knowledge_gap and all(c.confidence < 0.6 for c in env.discovery.candidates)
    settings = bancos.deps.settings.discovery
    confirmed = engine.Draft("X.dbo.T", "table", relevance=1.0, retrieval_norm=1.0, description_source="human",
                             golden_confirmation=1.0, sources={"catalog", "golden", "data_dictionary"})
    assert engine.compute_confidence(confirmed, settings) == 1.0
    confirmed.unknown_qualifiers = True
    assert engine.compute_confidence(confirmed, settings) < settings.gap_threshold


def test_las_fuentes_de_conocimiento_mueven_las_preguntas_de_reporte():
    """Medición reproducible que sustituye a la del set de 25 preguntas que no estaba versionado: las mismas preguntas
    normativas, de tablero y de estudio, con el catálogo solo y con un glosario y un manual de indicadores."""
    cases = load_cases(BANCOS / "eval" / "reportes.yaml")
    assert len(cases) == 25
    alone = evaluate(build_service(BANCOS), cases).metrics
    informed = evaluate(build_service_with_knowledge(BANCOS, BANCOS / "eval" / "conocimiento"), cases).metrics
    # Medido el 2026-11-23: 28 % → 64 % (el 2026-11-17 era 16 % → 60 %; subió al entender mejor la redacción de chat).
    assert alone["hit@1"] <= 35.0 and informed["hit@1"] >= 60.0 and informed["hit@1"] - alone["hit@1"] >= 30.0
    assert informed["leaks"] == 0 and informed["invented"] == 0
    # El catálogo de la línea base sigue crudo: el glosario solo entra cuando se pide.
    assert build_service(BANCOS).deps.knowledge.items == []


def test_la_cli_mide_con_y_sin_conocimiento(capsys):
    from discovery_data_agent import cli

    base = ["eval", "discovery", "--root", str(BANCOS), "--cases", str(BANCOS / "eval" / "reportes.yaml")]
    assert cli.main(base) == 0
    alone = capsys.readouterr().out
    assert cli.main([*base, "--knowledge", str(BANCOS / "eval" / "conocimiento")]) == 0
    informed = capsys.readouterr().out
    assert "Casos: 25 · Hit@1 28.0 %" in alone and "Casos: 25 · Hit@1 64.0 %" in informed
    with pytest.raises(SystemExit, match="--knowledge"):
        cli.main([*base, "--knowledge", str(BANCOS / "eval" / "conocimiento"), "--db"])


def test_el_nombre_de_una_tabla_que_no_se_ve_no_mueve_la_confianza(bancos):
    """F14: `Prestamos` tiene una llave foránea a `EjecutivosNegocio`. Quien no ve esa tabla no puede averiguar su
    nombre probando palabras: "de negocio" pesa igual que cualquier otra palabra que el catálogo no conoce."""
    catalog = bancos.deps.catalog
    hidden = "BancaPrestamos.dbo.EjecutivosNegocio"
    visible = frozenset(o.id for o in catalog.objects if o.database == "BancaPrestamos" and o.asset_key != hidden)
    user = UserContext(user_id="sin_ejecutivos", visible_ids=visible)

    def top(question):
        candidate = bancos.run(question, user, client="api").discovery.candidates[0]
        return candidate.asset_key, candidate.confidence

    assert top("¿Dónde están los préstamos de negocio?") == top("¿Dónde están los préstamos de zanahorias?")
    everyone = user_with_databases(bancos, "todo", None)
    seen = bancos.run("¿Dónde están los préstamos de negocio?", everyone, client="api").discovery.candidates[0]
    assert seen.confidence > top("¿Dónde están los préstamos de negocio?")[1]  # a quien sí la ve, sí le cuenta
