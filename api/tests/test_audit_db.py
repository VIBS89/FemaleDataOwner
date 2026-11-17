"""HU-20 · ConverData-API con la auditoría en la BD `ConverData` real (esquema `audit`, OP-05).

Necesita `CONVERDATA_TEST_DB` (ver `conftest.py` de la raíz); sin ella se omite. El resto de `api/tests` cubre los mismos
flujos con la auditoría en archivos: aquí se comprueba que el destino de SQL Server los sostiene igual y que es fail-closed.
"""

import pytest
from fastapi.testclient import TestClient

from converdata.audit.sqlserver import SqlServerAuditSink
from converdata_api.connector import DemoConnector
from converdata_api.main import create_app

from test_api import FIXTURE, build, login, settings  # noqa: F401  (fixtures de la API)

pytestmark = pytest.mark.sqlserver
QUESTION = "¿Dónde está el DUI del cliente?"


@pytest.fixture
def client(settings, empty_catalog_db):  # noqa: F811
    settings.db = empty_catalog_db
    api = TestClient(create_app(settings, DemoConnector(FIXTURE)))
    login(api, host="demo-sql", alias="SQL demo")
    assert build(api)["status"] == "ok"
    yield api
    api.app.state.runtime.drain()  # ninguna publicación en segundo plano sobrevive a la prueba (la BD es compartida)


def _count(db_connect, sql, *params):
    conn = db_connect()
    try:
        return conn.cursor().execute(sql, *params).fetchone()[0]
    finally:
        conn.close()


def test_la_api_usa_el_destino_de_sql_server_y_no_escribe_archivos(client, settings):  # noqa: F811
    assert isinstance(client.app.state.runtime.audit, SqlServerAuditSink)
    assert not settings.audit_dir.exists()


def test_pregunta_voto_y_lecturas_quedan_en_el_esquema_audit(client, db_connect):
    r = client.post("/discover", json={"question": QUESTION})
    assert r.status_code == 200, r.text
    env = r.json()
    trace = env["trace_id"]
    assert r.headers["X-Trace-Id"] == trace
    top = env["discovery"]["candidates"][0]

    # OP-05 CA1: exactamente una fila por pregunta, y una por candidato mostrado
    assert _count(db_connect, "SELECT COUNT(*) FROM audit.audit_question WHERE trace_id = ?", trace) == 1
    assert _count(db_connect, "SELECT COUNT(*) FROM audit.audit_discovery WHERE trace_id = ? AND kind = 'candidate'",
                  trace) == len(env["discovery"]["candidates"])
    assert _count(db_connect, "SELECT COUNT(*) FROM audit.audit_step WHERE trace_id = ?", trace) >= 5

    # OP-04 CA6: "✔ Es este" deja su fila con el tiempo hasta el veredicto
    r = client.post("/discover/feedback", json={"trace_id": trace, "asset_key": top["asset_key"], "verdict": "confirm"})
    assert r.status_code == 200, r.text
    conn = db_connect()
    row = conn.cursor().execute(
        "SELECT user_id, asset_key, verdict, actor_role, time_to_verdict_ms FROM audit.audit_discovery_feedback "
        "WHERE trace_id = ?", trace).fetchone()
    conn.close()
    assert tuple(row[:4]) == ("demo", top["asset_key"], "confirm", "steward") and row[4] is not None  # el admin de la demo es responsable

    # Las lecturas de la web salen de las mismas tablas
    assert client.get("/me/history").json()["items"][0]["trace_id"] == trace
    kinds = {row["type"] for row in client.get("/admin/audit?limit=500").json()["items"]}
    assert {"login", "question", "feedback", "catalog_build_finished", "audit_read"} <= kinds
    report = client.get("/admin/metrics?days=1").json()
    assert report["questions"] >= 1 and report["active_users"] >= 1 and report["confirmed_rate"] is not None
    assert client.get("/curation/review").status_code in (200, 403)


def test_ninguna_fila_de_auditoria_contiene_la_contrasena(client, db_connect):
    client.post("/auth/login", json={"login": "demo", "password": "Clave-Secreta-9731"})  # falla: queda login_failed
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT data_json FROM audit.audit_event")
    text = "\n".join(r[0] for r in cur.fetchall())
    cur.execute("SELECT question FROM audit.audit_question")
    text += "\n".join(r[0] for r in cur.fetchall())
    conn.close()
    assert "login_failed" in "".join(k for (k,) in db_connect().cursor().execute(
        "SELECT DISTINCT kind FROM audit.audit_event").fetchall())
    assert "Clave-Secreta-9731" not in text and '"demo"' not in text.replace('"user_id"', "")


def test_si_la_bd_no_responde_no_hay_respuesta_ni_cambios(client, db_connect, monkeypatch):
    """F11 CA4 y OP-05 CA6: fail-closed. Tampoco se aplica un cambio de curación que no se pudo auditar."""
    before = _count(db_connect, "SELECT COUNT(*) FROM audit.audit_question")
    sink = client.app.state.runtime.audit

    def down():
        raise ConnectionError("BD ConverData inaccesible")

    monkeypatch.setattr(sink, "_connect", down)
    r = client.post("/discover", json={"question": QUESTION})
    assert r.status_code == 200
    env = r.json()
    assert env["status"] == "error" and env["discovery"] is None

    quiet = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    r = quiet.put("/curation/description", json={"asset_key": "BancaPrestamos.dbo.Clientes", "description": "No debe quedar"})
    assert r.status_code == 500
    monkeypatch.undo()
    assert _count(db_connect, "SELECT COUNT(*) FROM audit.audit_question") == before
    detail = client.get("/assets/BancaPrestamos.dbo.Clientes")
    assert detail.status_code == 200 and detail.json()["description"] != "No debe quedar"
