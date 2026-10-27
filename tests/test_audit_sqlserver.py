"""HU-20 · Auditoría fail-closed en el esquema `audit` de la BD ConverData (F11, OP-05)."""

import pytest

from converdata.audit.recorder import FeedbackRecord
from converdata.audit.sqlserver import SqlServerAuditSink
from converdata.bootstrap import build_service
from conftest import FIXTURE, ONBOARDING_Q
from fakes import FakeDb


@pytest.fixture
def db():
    return FakeDb()


def _run(service, analyst):
    return service.run(ONBOARDING_Q, analyst, client="api")


def test_una_pregunta_deja_una_fila_por_tabla_en_una_sola_transaccion(db):
    from converdata.bootstrap import user_with_databases

    service = build_service(FIXTURE, audit=SqlServerAuditSink(db.connect))
    analyst = user_with_databases(service, "analista", ["VBank_ING", "Onboarding", "DWH"])
    env = _run(service, analyst)
    assert env.status == "ok"
    [question] = db.inserts_into("audit.audit_question")
    assert question[0] == env.trace_id and question[1] == "analista" and question[2] == "api"
    steps = db.inserts_into("audit.audit_step")
    assert {s[1] for s in steps} >= {"intent", "retrieve", "rerank", "expand", "respond"}
    discovery = db.inserts_into("audit.audit_discovery")
    kinds = [d[-1] for d in discovery]
    assert kinds.count("candidate") == len(env.discovery.candidates)
    assert db.commits == 1 and db.rollbacks == 0 and db.closed == 1


def test_si_falla_la_escritura_hace_rollback_y_no_entrega_la_respuesta(db):
    from converdata.bootstrap import user_with_databases

    failing = FakeDb(fail_on=r"audit\.audit_discovery\b")
    service = build_service(FIXTURE, audit=SqlServerAuditSink(failing.connect))
    analyst = user_with_databases(service, "analista", ["VBank_ING"])
    env = _run(service, analyst)
    assert env.status == "error" and env.discovery is None  # F11 CA4: fail-closed
    assert failing.rollbacks == 1 and failing.commits == 0 and failing.closed == 1


def test_no_guarda_contrasenas_ni_valores_en_los_parametros(db):
    from converdata.bootstrap import user_with_databases

    service = build_service(FIXTURE, audit=SqlServerAuditSink(db.connect))
    user = user_with_databases(service, "analista", None)
    service.run("¿dónde está el DUI? mi clave es S3cr3t0!", user, client="cli")
    # La pregunta se audita tal cual (D2 on-prem), pero nunca credenciales de la sesión: el sink no las recibe.
    assert "password" not in db.text().lower()


def test_cliente_desconocido_se_normaliza_a_api(db):
    from converdata.bootstrap import user_with_databases

    service = build_service(FIXTURE, audit=SqlServerAuditSink(db.connect))
    user = user_with_databases(service, "u", None)
    service.run(ONBOARDING_Q, user, client="streamlit")
    assert db.inserts_into("audit.audit_question")[0][2] == "api"  # CHECK (client IN ('ui','api','mcp','cli'))


def test_feedback_se_inserta_con_su_veredicto(db):
    sink = SqlServerAuditSink(db.connect)
    sink.write_feedback(FeedbackRecord(trace_id="00000000-0000-0000-0000-000000000001", asset_key="A.dbo.T.C",
                                       verdict="confirm", actor_role="consumer", time_to_verdict_ms=4200))
    [row] = db.inserts_into("audit.audit_discovery_feedback")
    assert row == ("00000000-0000-0000-0000-000000000001", "A.dbo.T.C", "confirm", None, "consumer", 4200)
    assert db.commits == 1


def test_feedback_rechaza_veredictos_invalidos(db):
    with pytest.raises(ValueError):
        FeedbackRecord(trace_id="t", asset_key="A", verdict="maybe", actor_role="consumer")
