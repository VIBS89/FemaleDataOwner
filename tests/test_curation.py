"""Bloque C2 · Reglas de la curación (F24) y sus dos almacenamientos: archivos (desarrollo) y la BD `ConverData`.

Las pruebas marcadas `sqlserver` necesitan `CONVERDATA_TEST_DB` (ver `conftest.py` de la raíz).
"""

import uuid

import pytest

from converdata.catalog.store import KnowledgeBase, load_snapshot
from converdata.curation import (DescriptionEdit, golden_id, has_literals, human_edits, plan_dictionary,
                                 question_template, resolve_golden, steward_rules)
from converdata.config import ServerConfig
from converdata.models.knowledge import BusinessRule, GoldenDiscovery, KnowledgeItem
from converdata.storage.curation_repository import SqlServerCurationRepository
from converdata.storage.files import FileCurationRepository, FileInventoryStore, FileKnowledgeWriter
from converdata.builder.catalog_builder import write_snapshot
from conftest import FIXTURE

USERS = "VBank_ING.dbo.Users"
BANCOS = FIXTURE.parent / "bancos"


# --- plantilla anónima ---------------------------------------------------------------------------------
@pytest.mark.parametrize("question, template", [
    ("¿Dónde está el DUI del cliente 01234567-8?", "donde esta el dui del cliente"),
    ("¿Dónde está el DUI del cliente?", "donde esta el dui del cliente"),
    ("Saldo de la cuenta 1234 5678 9012 al 31/12/2025", "saldo de la cuenta al"),
    ("¿Quién es el dueño de juan.perez@banco.com.sv?", "quien es el dueno de"),
    ("Clientes con mora mayor a 90 días", "clientes con mora mayor a dias"),
    ("¿De quién es el pasaporte A01234567?", "de quien es el pasaporte"),
    ("Movimientos de la cuenta CA00123456789", "movimientos de la cuenta"),
    # Formas que una lista de formatos concretos deja pasar (revisión de seguridad del 2026-11-17)
    ("¿Dónde está el DUI del cliente ACME090?", "donde esta el dui del cliente"),  # alfanumérico corto: código, placa
    ("Saldo del cliente ⁷⁷³¹⁰⁰²⁴", "saldo del cliente"),  # dígitos en superíndice
    ("Saldo del cliente ＣＴＡ７７３１０００１", "saldo del cliente"),  # ancho completo
    ("Pedido ACME-TEST-001- del cliente", "pedido del cliente"),  # guion final
    ("Pedido ACME–TEST–001 del cliente", "pedido del cliente"),  # raya en vez de guion
    ("Expediente ACME_TEST_123 y CLI_0042", "expediente y"),
    ("Códigos AB12CD34, 7731A, 1500USD y sqlprod01", "codigos y"),
    ("Escribe a josé@correo.com o a juan＠correo.com", "escribe a o a"),
    ("Escribe a juan.perez @ banco.com", "escribe a"),
    ("Referencias ACME.TEST.123, ACME:TEST:123 y ACME#123", "referencias y"),
])
def test_la_plantilla_no_conserva_literales(question, template):
    assert question_template(question) == template


def test_dos_preguntas_que_solo_difieren_en_el_literal_son_la_misma_confirmacion():
    a = question_template("¿Dónde está el DUI del cliente 01234567-8?")
    b = question_template("¿dónde está el DUI del cliente 98765432-1?")
    assert golden_id(a, USERS) == golden_id(b, USERS)
    assert golden_id(a, USERS) != golden_id(a, "Otra.dbo.Tabla")


@pytest.mark.parametrize("question, literal", [
    ("¿Dónde está el DUI del cliente 71234567?", True),  # un documento sin guion: ningún detector lo reconoce
    ("¿De quién es el pasaporte A01234567?", True),
    ("escríbeme a ana@banco.com.sv", True),
    ("¿Dónde está el DUI del cliente ACME090?", True),
    ("Saldo del cliente ⁷⁷³¹⁰⁰²⁴", True),
    ("Escribe a josé@correo.com", True),
    ("¿Dónde está el DUI del cliente?", False),
    ("¿Dónde están los   consentimientos\naceptados?", False),  # los espacios no son literales
])
def test_una_pregunta_con_literales_se_reconoce_para_no_guardar_su_texto(question, literal):
    assert has_literals(question) is literal


def test_el_vocabulario_del_banco_no_es_un_literal(catalog):
    """Una palabra con dígitos es un literal salvo que sea un nombre del catálogo o un código del glosario."""
    question = "¿Qué columna Ultimos4 exige la norma NCB-022 en T24 para el cliente 4111?"
    assert question_template(question) == "que columna exige la norma en para el cliente"
    known = frozenset({"ultimos4", "ncb-022", "t24"})
    assert question_template(question, known) == "que columna ultimos4 exige la norma ncb 022 en t24 para el cliente"
    assert has_literals("¿Dónde está Ultimos4?", known) is False and has_literals("¿Dónde está Ultimos4?") is True
    assert question_template("¿Dónde está BancaTarjetasCredito.dbo.TarjetasCredito.Ultimos4?", known).endswith("ultimos4")
    # El vocabulario sale del catálogo y del conocimiento, no de una lista escrita a mano.
    assert "ultimos4" in load_snapshot(BANCOS).catalog().names_with_digits()
    assert catalog.names_with_digits(frozenset()) == frozenset()  # sin objetos visibles, ningún nombre
    kb = KnowledgeBase(
        items=[KnowledgeItem(id="g1", kind="glossary", source="glosario", text="Categoría de riesgo según la NCB-022. Ver cuenta 0012345678.")],
        rules=[BusinessRule(id="BR-ONB-004", text="Solo clientes activos", applies_to=[USERS])])
    assert kb.codes() == {"ncb-022", "br-onb-004"}  # un número suelto de un fragmento no se vuelve vocabulario


# --- regla de votos ------------------------------------------------------------------------------------
def _resolve(votes, steward=False, verdict="confirm", current=None):
    return resolve_golden("plantilla", USERS, votes, steward=steward, verdict=verdict, current=current)


def test_los_usuarios_cuentan_confirmaciones_netas():
    assert _resolve({"ana": "confirm"}).confirmations == 1  # una sola no pesa todavía en la confianza (F22: ≥ 2)
    two = _resolve({"ana": "confirm", "luis": "confirm"})
    assert (two.confirmed_by, two.confirmations, two.rejected) == ("users", 2, False)


def test_un_solo_rechazo_no_retira_lo_que_confirmaron_varios():
    kept = _resolve({"ana": "confirm", "luis": "confirm", "eva": "confirm", "raul": "reject"}, verdict="reject")
    assert (kept.confirmations, kept.rejected) == (2, False)
    weaker = _resolve({"ana": "confirm", "luis": "confirm", "raul": "reject"}, verdict="reject")
    assert (weaker.confirmations, weaker.rejected) == (1, False)  # sigue en el índice, pero ya sin el peso de 2
    retired = _resolve({"ana": "confirm", "raul": "reject"}, verdict="reject")
    assert retired.rejected is True
    assert _resolve({"raul": "reject"}, verdict="reject").rejected is True


def test_el_responsable_manda_sobre_los_usuarios():
    approved = _resolve({"resp": "confirm"}, steward=True)
    assert (approved.confirmed_by, approved.rejected) == ("steward", False)
    # Un "✖" de un usuario no cambia lo que confirmó el responsable.
    after = _resolve({"resp": "confirm", "raul": "reject"}, verdict="reject", current=approved)
    assert (after.confirmed_by, after.rejected) == ("steward", False)
    # El "✖" del responsable sí retira la pareja, aunque la hayan confirmado usuarios (F24 CA2).
    retired = _resolve({"ana": "confirm", "luis": "confirm", "resp": "reject"}, steward=True, verdict="reject")
    assert retired.rejected is True


# --- ediciones de descripciones ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def catalog():
    return load_snapshot(FIXTURE).catalog()


def test_una_edicion_humana_va_a_todas_las_copias_fisicas(catalog):
    copies = catalog.copies(USERS)
    edits = human_edits(catalog, USERS, "  Usuarios de banca digital ", ["clientes", "clientes", " "])
    assert {e.physical_id for e in edits} == {o.id for o in copies} and len(copies) > 1
    assert all((e.description, e.source, e.reviewed, e.synonyms, e.column) ==
               ("Usuarios de banca digital", "human", True, ("clientes",), None) for e in edits)
    column = copies[0].columns[0].name
    by_column = human_edits(catalog, f"{USERS}.{column.upper()}", "Identificador", None)
    assert by_column and all(e.column == column and e.synonyms is None for e in by_column)
    assert human_edits(catalog, f"{USERS}.NoExiste", "x", None) == []


def test_el_diccionario_no_pisa_lo_humano_ni_sale_del_dominio(catalog):
    human = next(o for o in catalog.objects if o.description_source == "human")
    other = next(o for o in catalog.objects if o.description_source != "human" and o.asset_key != human.asset_key)
    text = ("asset_key,description,synonyms\n"
            f"{human.asset_key},Texto del diccionario,\n"
            f"{other.asset_key},Descripción del diccionario,alias uno;alias dos\n"
            "No.Existe.Tabla,Algo,\n"
            f"{USERS},Fuera del dominio,\n")
    plan = plan_dictionary(catalog, text, lambda key: not key.startswith(USERS))
    assert plan.unknown == ["No.Existe.Tabla"] and plan.forbidden == [USERS] and plan.rows == 4
    assert plan.skipped_human == len(catalog.copies(human.asset_key))
    assert {e.physical_id for e in plan.edits} == {o.id for o in catalog.copies(other.asset_key)}
    assert all(e.source == "data_dictionary" and e.keep_human and "alias dos" in e.synonyms for e in plan.edits)
    assert plan.report(2) == {"unchanged": False, "applied": 2, "skipped_human": plan.skipped_human, "same": 0,
                              "unknown": ["No.Existe.Tabla"], "forbidden": [USERS], "rows": 4}
    # Sin nada que escribir y con filas ya iguales, el informe dice que el diccionario ya estaba aplicado (F23 CA5).
    done = plan_dictionary(catalog, f"asset_key,description\n{human.asset_key},{human.description}\n", lambda key: True)
    assert done.edits == [] and done.report(0)["unchanged"] is False  # lo humano se respeta: no es "ya aplicado"


def test_solo_las_reglas_de_responsables_se_gestionan_en_curacion():
    rules = [BusinessRule(id="A", text="importada", applies_to=[USERS], source="knowledge/rules"),
             BusinessRule(id="B", text="curada", applies_to=[USERS], source="steward:ana"),
             BusinessRule(id="C", text="sin origen", applies_to=[USERS])]
    assert [r.id for r in steward_rules(rules)] == ["B"]


# --- almacenamiento en archivos (desarrollo) -----------------------------------------------------------
def test_el_escritor_de_archivos_edita_el_directorio_del_catalogo(tmp_path):
    write_snapshot(tmp_path, load_snapshot(FIXTURE))
    writer = FileKnowledgeWriter(tmp_path)
    catalog = load_snapshot(tmp_path).catalog()
    assert writer.write_descriptions(human_edits(catalog, USERS, "Editada en archivos", None), by="ana",
                                     reason="curation") == len(catalog.copies(USERS))
    writer.upsert_rule(BusinessRule(id="BR-ARCHIVO", text="Regla", applies_to=[USERS], source="steward:ana"), by="ana")
    writer.upsert_golden(GoldenDiscovery(id="u-archivo", template="plantilla", asset_keys=[USERS], confirmed_by="users"),
                         by="ana", question="la pregunta original no se guarda en archivos")
    after = load_snapshot(tmp_path)
    assert {o.description for o in after.catalog().copies(USERS)} == {"Editada en archivos"}
    assert "BR-ARCHIVO" in {r.id for r in after.knowledge.rules} and "u-archivo" in {g.id for g in after.knowledge.golden}
    assert "pregunta original" not in "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.yaml"))
    assert writer.delete_rule("BR-ARCHIVO", by="ana") and not writer.delete_rule("BR-ARCHIVO", by="ana")


# --- el mismo contrato en archivos y en la BD ----------------------------------------------------------
@pytest.fixture(params=["archivos", pytest.param("sqlserver", marks=pytest.mark.sqlserver)])
def curation(request, tmp_path):
    if request.param == "archivos":
        return FileCurationRepository(tmp_path / "curation")
    return SqlServerCurationRepository(request.getfixturevalue("db_connect"))


def _request(trace: str, user: str = "ana", **extra) -> dict:
    return {"id": uuid.uuid4().hex[:10], "created_at": "2026-11-17T10:00:00+00:00", "status": "open", "user_id": user,
            "trace_id": trace, "question": "¿Dónde está el saldo del préstamo?", "domain": "prestamos",
            "shown": ["BancaPrestamos.dbo.Prestamos.Saldo"], "note": None, "answer": None, **extra}


def test_los_responsables_se_reemplazan_enteros(curation):
    curation.save_stewards([{"login": "ana", "domains": ["prestamos"]}, {"login": "luis", "domains": ["*"]}], by="admin")
    curation.save_stewards([{"login": "ana", "domains": ["prestamos", "tarjetas"]}], by="admin")
    assert curation.stewards() == [{"login": "ana", "domains": ["prestamos", "tarjetas"]}]
    curation.save_stewards([], by="admin")
    assert curation.stewards() == []


def test_una_duda_escalada_se_guarda_una_vez_y_se_responde(curation):
    trace = uuid.uuid4().hex
    first = curation.add_requests([_request(trace)])[0]
    again = curation.add_requests([_request(trace)])[0]  # misma respuesta y mismo usuario: no se duplica
    assert again["id"] == first["id"]
    other = curation.add_requests([_request(trace, user="luis", simulated=True)])[0]
    assert other["id"] != first["id"] and other.get("simulated") is True
    mine = [r for r in curation.requests() if r["trace_id"] == trace]
    assert [r["user_id"] for r in mine] == ["ana", "luis"]  # en orden de creación
    assert mine[0]["shown"] == ["BancaPrestamos.dbo.Prestamos.Saldo"] and mine[0]["answer"] is None
    answer = {"by": "resp", "at": "2026-11-17T11:00:00+00:00", "kind": "asset",
              "asset_key": "BancaPrestamos.dbo.Prestamos.Saldo", "note": None}
    answered = curation.answer_request(first["id"], "answered", answer)
    assert (answered["status"], answered["answer"]) == ("answered", answer)
    assert next(r for r in curation.requests() if r["id"] == first["id"])["answer"]["by"] == "resp"
    with pytest.raises(KeyError):
        curation.answer_request("no-existe", "answered", answer)


def test_el_recuento_usa_el_ultimo_voto_de_cada_usuario(curation):
    gid = "u-" + uuid.uuid4().hex[:12]

    def vote(user, verdict):
        return curation.add_vote({"golden_id": gid, "user_id": user, "trace_id": "t1", "asset_key": USERS,
                                  "verdict": verdict, "steward": False})

    assert vote("ana", "confirm") == {"ana": "confirm"}
    assert vote("luis", "confirm") == {"ana": "confirm", "luis": "confirm"}
    assert vote("ana", "reject") == {"ana": "reject", "luis": "confirm"}  # cambió de opinión
    other = curation.add_vote({"golden_id": gid + "x", "user_id": "eva", "trace_id": "t2", "asset_key": USERS,
                               "verdict": "confirm"})
    assert other == {"eva": "confirm"}  # los votos de otra pareja no se mezclan


def test_el_inventario_en_archivos_guarda_los_hosts(tmp_path):
    store = FileInventoryStore(tmp_path / "datos" / "inventory.yaml")
    assert store.inventory() == []
    servers = [ServerConfig(id="S1", host="sql01.banco.local", alias="SQL 1", environment="produccion", databases=["*"])]
    store.save_inventory(servers, by="admin")
    assert [(s.id, s.host, s.databases) for s in store.inventory()] == [("S1", "sql01.banco.local", ["*"])]


def test_quitar_literales_no_se_cuelga_con_una_palabra_enorme():
    """El patrón del correo con espacios se intentaba en cada carácter: 20 000 letras seguidas tardaban segundos."""
    import re
    import time

    from converdata.memory.text import strip_literals

    old = re.compile(r"\S+\s+@\s+\S+")
    for text in ("escribe a juan.perez @ banco.com hoy", "a @ b", "@ solo", "sin arroba", "x @", "uno dos @ tres cuatro"):
        assert strip_literals(text) == " ".join(w for w in old.sub(" ", text).split() if "@" not in w)
    start = time.perf_counter()
    assert strip_literals("x" * 20000 + " @ banco.com") == ""
    assert strip_literals("x" * 20000) == "x" * 20000
    assert time.perf_counter() - start < 0.5


def test_figures_del_servidor_se_conserva_al_guardar_y_leer_el_inventario(tmp_path):
    """`ServerConfig.figures` (None / True / False) sobrevive al ciclo del inventario en archivos."""
    from converdata.config import ServerConfig

    servers = [ServerConfig(id=f"S{i}", alias=f"s{i}", environment="produccion", figures=f)
               for i, f in enumerate([None, True, False])]
    store = FileInventoryStore(tmp_path / "inventory.yaml")
    store.save_inventory(servers, by="admin")
    assert [s.figures for s in store.inventory()] == [None, True, False]
