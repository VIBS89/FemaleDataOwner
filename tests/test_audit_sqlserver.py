"""HU-20 · Auditoría fail-closed en el esquema `audit` de la BD DiscoveryDataAgent (F11, OP-05)."""

import pytest

from discovery_data_agent.audit.recorder import FeedbackRecord
from discovery_data_agent.audit.sqlserver import SqlServerAuditSink
from discovery_data_agent.bootstrap import build_service
from conftest import FIXTURE, ONBOARDING_Q
from fakes import FakeDb


@pytest.fixture
def db():
    return FakeDb()


def _run(service, analyst):
    return service.run(ONBOARDING_Q, analyst, client="api")


def test_una_pregunta_deja_una_fila_por_tabla_en_una_sola_transaccion(db):
    from discovery_data_agent.bootstrap import user_with_databases

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


def test_si_falla_la_escritura_hace_rollback_y_no_entrega_la_respuesta(db, caplog):
    from discovery_data_agent.bootstrap import user_with_databases

    failing = FakeDb(fail_on=r"audit\.audit_discovery\b")
    service = build_service(FIXTURE, audit=SqlServerAuditSink(failing.connect))
    analyst = user_with_databases(service, "analista", ["VBank_ING"])
    with caplog.at_level("ERROR"):
        env = _run(service, analyst)
    assert env.status == "error" and env.discovery is None  # F11 CA4: fail-closed
    assert failing.rollbacks == 1 and failing.commits == 0 and failing.closed == 1
    # OP-05: el fallo deja un evento operativo (sin la pregunta) para la alerta "Fallo de escritura de auditoría".
    [event] = [r for r in caplog.records if r.getMessage() == "audit.write_failed"]
    assert event.error_type == "RuntimeError" and event.trace_id == env.trace_id
    assert ONBOARDING_Q not in caplog.text


def test_no_guarda_contrasenas_ni_valores_en_los_parametros(db):
    from discovery_data_agent.bootstrap import user_with_databases

    service = build_service(FIXTURE, audit=SqlServerAuditSink(db.connect))
    user = user_with_databases(service, "analista", None)
    service.run("¿dónde está el DUI? mi clave es S3cr3t0!", user, client="cli")
    # La pregunta se audita tal cual (D2 on-prem), pero nunca credenciales de la sesión: el sink no las recibe.
    assert "password" not in db.text().lower()


def test_cliente_desconocido_se_normaliza_a_api(db):
    from discovery_data_agent.bootstrap import user_with_databases

    service = build_service(FIXTURE, audit=SqlServerAuditSink(db.connect))
    user = user_with_databases(service, "u", None)
    service.run(ONBOARDING_Q, user, client="streamlit")
    assert db.inserts_into("audit.audit_question")[0][2] == "api"  # los clientes desconocidos se registran como "api"


def test_feedback_se_inserta_con_su_veredicto(db):
    sink = SqlServerAuditSink(db.connect)
    sink.write_feedback(FeedbackRecord(trace_id="00000000-0000-0000-0000-000000000001", asset_key="A.dbo.T.C",
                                       verdict="confirm", actor_role="consumer", time_to_verdict_ms=4200))
    [row] = db.inserts_into("audit.audit_discovery_feedback")
    assert row == ("00000000-0000-0000-0000-000000000001", "A.dbo.T.C", "confirm", None, "consumer", 4200, None, None)
    assert db.commits == 1


def test_feedback_rechaza_veredictos_invalidos(db):
    with pytest.raises(ValueError):
        FeedbackRecord(trace_id="t", asset_key="A", verdict="maybe", actor_role="consumer")


def test_un_evento_con_trace_id_invalido_no_rompe_la_escritura(db):
    """`trace_id` llega del cliente en algunas rutas: si no es un GUID, se guarda dentro de los datos del evento."""
    sink = SqlServerAuditSink(db.connect)
    sink.event("curation_request", "analista", trace_id="'; DROP TABLE audit.audit_event;--", domain="clientes")
    [(kind, user, trace_id, data, ts)] = db.inserts_into("audit.audit_event")
    assert (kind, user, trace_id, ts) == ("curation_request", "analista", None, None)
    assert "DROP TABLE" in data and '"domain": "clientes"' in data


def test_el_voto_se_guarda_como_evento_y_como_feedback_en_la_misma_transaccion(db):
    sink = SqlServerAuditSink(db.connect)
    trace = "00000000-0000-0000-0000-0000000000aa"
    sink.event("feedback", "analista", trace_id=trace, asset_key="A.dbo.T.C", verdict="reject", steward=True,
               time_to_verdict_ms=900)
    assert len(db.inserts_into("audit.audit_event")) == 1
    [row] = db.inserts_into("audit.audit_discovery_feedback")
    assert row[:7] == (trace, "A.dbo.T.C", "reject", None, "steward", 900, "analista")
    assert db.commits == 1


# --- contra SQL Server real (HU-05, HU-20) ------------------------------------------------------------
@pytest.mark.sqlserver
def test_auditoria_real_escribe_lee_y_filtra(db_connect):
    from discovery_data_agent.bootstrap import user_with_databases

    sink = SqlServerAuditSink(db_connect)
    service = build_service(FIXTURE, audit=sink)
    analyst = user_with_databases(service, "analista_sql", ["VBank_ING", "Onboarding", "DWH"])
    env = service.run(ONBOARDING_Q, analyst, client="web")
    assert env.status == "ok"
    sink.event("feedback", "analista_sql", trace_id=env.trace_id, asset_key=env.discovery.candidates[0].asset_key,
               verdict="confirm", steward=False, time_to_verdict_ms=1500)
    sink.event("login", "otro_usuario", servers=["S1"], roles=["consumer"])

    mine = sink.recent(50, user_id="analista_sql")
    assert {r["type"] for r in mine} == {"question", "feedback"}
    [question] = [r for r in mine if r["type"] == "question"]
    assert question["trace_id"] == env.trace_id and question["client"] == "web" and question["status"] == "ok"
    assert question["question"] == ONBOARDING_Q and question["duration_ms"] is not None
    candidates = [d for d in question["discovery"] if d["kind"] == "candidate"]
    assert [d["asset_key"] for d in candidates] == [c.asset_key for c in env.discovery.candidates]
    assert {s["step"] for s in question["steps"]} >= {"intent", "retrieve", "respond"}
    [feedback] = [r for r in mine if r["type"] == "feedback"]
    assert feedback["trace_id"] == env.trace_id and feedback["verdict"] == "confirm"
    assert sink.recent(50, user_id="analista_sql", kind="question") == [question]
    assert [r["type"] for r in sink.recent(50, user_id="otro_usuario")] == ["login"]
    assert all(r["type"] == "login" for r in sink.recent(50, kind="login"))

    conn = db_connect()
    row = conn.cursor().execute(
        "SELECT user_id, verdict, actor_role, time_to_verdict_ms FROM audit.audit_discovery_feedback WHERE trace_id = ?",
        env.trace_id).fetchone()
    conn.close()
    assert tuple(row) == ("analista_sql", "confirm", "consumer", 1500)


@pytest.mark.sqlserver
def test_auditoria_real_si_falla_un_insert_no_queda_nada(db_connect):
    """Una sola transacción: una fila inválida de candidatos deja la pregunta sin registrar (y sin respuesta)."""
    sink = SqlServerAuditSink(db_connect)
    trace = "11111111-2222-3333-4444-555555555555"
    row = {"type": "question", "trace_id": trace, "user_id": "u", "client": "api", "question": "q", "status": "ok",
           "discovery": [{"rank": 1, "asset_key": "A.dbo.T", "environment": None, "confidence": 0.9,
                          "description_source": None, "kind": "no_permitido"}]}
    with pytest.raises(Exception):
        sink.append(row)
    conn = db_connect()
    count = conn.cursor().execute("SELECT COUNT(*) FROM audit.audit_question WHERE trace_id = ?", trace).fetchone()[0]
    conn.close()
    assert count == 0


@pytest.mark.sqlserver
def test_verify_real_avisa_si_la_cuenta_puede_modificar_la_auditoria(db_connect):
    """Las pruebas corren como dueño de la BD: `verify` debe decir que esa cuenta no sirve para producción."""
    report = SqlServerAuditSink(db_connect).verify()
    assert not report.ok and any("discovery_data_agent_app" in e for e in report.files[0].errors)


@pytest.mark.sqlserver
def test_cada_usuario_ve_solo_lo_suyo_aunque_la_colacion_no_distinga_mayusculas(db_connect):
    """`/me/history`: `Ana` no ve lo de `ANA` (logins distintos en un servidor con colación sensible)."""
    sink = SqlServerAuditSink(db_connect)
    sink.event("login", "Ana_Colacion", servers=["S1"])
    sink.event("login", "ANA_COLACION", servers=["S1"])
    assert [r["user_id"] for r in sink.recent(50, user_id="Ana_Colacion", kind="login")] == ["Ana_Colacion"]
