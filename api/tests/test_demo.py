"""Modo demo para inversionistas (CONVERDATA_DEMO=1): el guion completo que muestra la web.

VBank (propuesta: onboarding digital, prod + QA + DWH) y BancosSQL simulados, conocimiento curado del fixture, tres
usuarios demo y el ciclo: pregunta → candidato con 92 % → duda sin respuesta → el responsable la contesta → la siguiente
pregunta equivalente la encuentra como candidato principal.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converdata_api.connector import DemoConnector
from converdata_api.main import create_app
from converdata_api.settings import ApiSettings

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = [ROOT / "tests" / "fixtures" / "vbank", ROOT / "tests" / "fixtures" / "bancos"]
ONBOARDING_Q = "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital."
GAP_Q = "¿Dónde está el puntaje de lealtad del cliente digital?"
ANSWER_ASSET = "VBank_ING.dbo.Users.OnboardingStatus"


@pytest.fixture
def settings(tmp_path):
    return ApiSettings(
        data_root=tmp_path / "catalog", inventory_path=tmp_path / "inventory.yaml", audit_dir=tmp_path / "audit",
        curation_dir=tmp_path / "curation", demo=True, demo_fixtures=FIXTURES, allow_windows_auth=False,
    )


@pytest.fixture
def app(settings):
    return create_app(settings, DemoConnector(FIXTURES))


def client_for(app, user):
    c = TestClient(app)
    r = c.post("/auth/login", json={"login": user, "password": "demo"})
    assert r.status_code == 200, r.text
    return c


def build(c):
    assert c.post("/admin/catalog/build", json={"enrich": False}).status_code == 202
    for _ in range(400):
        job = c.get("/admin/catalog/build").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("la construcción no terminó")


@pytest.fixture
def demo(app):
    admin = client_for(app, "demo")
    job = build(admin)
    assert job["status"] == "ok", job
    return admin


def test_inventario_precargado_con_los_servidores_de_los_fixtures(app):
    status = TestClient(app).get("/setup/status").json()
    aliases = {s["alias"] for s in status["servers"]}
    assert status["has_inventory"] and status["demo"]
    assert aliases == {"SQL Producción Canales", "SQL QA Canales", "SQL Producción DWH", "SQL Express local"}


def test_usuarios_demo_y_sus_roles(app):
    admin = client_for(app, "demo").get("/auth/me").json()
    analyst = client_for(app, "analista").get("/auth/me").json()
    steward = client_for(app, "responsable").get("/auth/me").json()
    assert "data_admin" in admin["roles"] and admin["domains"] == ["*"]
    assert analyst["roles"] == ["consumer"] and analyst["domains"] is None
    assert steward["roles"] == ["consumer", "steward"] and steward["domains"] == ["*"]


def test_catalogo_demo_con_conocimiento_curado(demo, app):
    dbs = {d["database"] for d in demo.get("/catalog/databases").json()}
    assert {"VBank_ING", "Onboarding", "DWH", "RRHH", "BancaPrestamos", "BancaTokenizacion"} <= dbs
    users = demo.get("/assets/VBank_ING.dbo.Users").json()
    client_code = next(c for c in users["columns"] if c["name"] == "ClientCode")
    assert client_code["description_source"] == "human" and client_code["reviewed"]
    assert "BR-ONB-004" in [r["id"] for r in users["business_rules"]]
    assert users["owners"]["business"] == "Producto Banca Digital"
    # las QA y las copias en otros ambientes también están
    assert {c["environment"] for c in users["copies"]} == {"qa"}


def test_analista_no_ve_rrhh(demo, app):
    analyst = client_for(app, "analista")
    dbs = {d["database"] for d in analyst.get("/catalog/databases").json()}
    assert dbs == {"VBank_ING", "Onboarding", "DWH", "BancaPrestamos", "BancaCuentasDebito"}


def test_guion_de_la_demo(demo, app):
    analyst = client_for(app, "analista")
    steward = client_for(app, "responsable")

    # 1. La pregunta de la propuesta: ClientCode con confianza alta y evidencia humana.
    env = analyst.post("/discover", json={"question": ONBOARDING_Q}).json()
    top = env["discovery"]["candidates"][0]
    assert top["asset_key"] == "VBank_ING.dbo.Users.ClientCode" and top["confidence"] >= 0.85
    assert top["description_source"] == "human" and top["locations"]
    assert {loc["environment"] for loc in top["locations"]} == {"produccion", "qa"}

    # 2. Una pregunta sin respuesta en las fuentes: brecha → "Preguntar al responsable".
    gap = analyst.post("/discover", json={"question": GAP_Q}).json()
    assert gap["discovery"]["knowledge_gap"] is True
    req = analyst.post("/curation/requests", json={"trace_id": gap["trace_id"], "note": "Lo necesito para campaña"}).json()
    assert req["status"] == "open"

    # 3. El responsable ve la duda en su bandeja (el analista no puede).
    assert analyst.get("/curation/requests").status_code == 403
    inbox = steward.get("/curation/requests", params={"status": "open"}).json()["items"]
    item = next(i for i in inbox if i["id"] == req["id"])
    assert item["question"] == GAP_Q and item["user_id"] == "analista" and item["note"] == "Lo necesito para campaña"

    # 4. Lo responde con un activo y una descripción.
    r = steward.post(f"/curation/requests/{req['id']}/answer", json={
        "kind": "asset", "asset_key": ANSWER_ASSET,
        "description": "Puntaje de lealtad del cliente digital: estado del onboarding que usa Marketing para segmentar.",
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] and r.json()["request"]["status"] == "answered"

    # 5. El analista ve la respuesta y, al repetir la pregunta, el activo es el candidato principal.
    mine = analyst.get("/me/requests").json()["items"]
    assert mine[0]["status"] == "answered" and mine[0]["answer"]["asset_key"] == ANSWER_ASSET
    again = analyst.post("/discover", json={"question": GAP_Q}).json()
    top = again["discovery"]["candidates"][0]
    assert top["asset_key"] == ANSWER_ASSET and top["confidence"] >= 0.85

    # 6. Impacto: la pantalla de métricas lo refleja.
    metrics = demo.get("/admin/metrics", params={"days": 30}).json()
    assert metrics["questions"] >= 3 and metrics["escalations"] == 1 and metrics["active_users"] >= 1
    assert analyst.get("/admin/metrics").status_code == 403


def test_cola_de_revision_y_edicion_de_descripciones(demo, app):
    analyst = client_for(app, "analista")
    steward = client_for(app, "responsable")
    analyst.post("/discover", json={"question": "¿Cuándo fue el último inicio de sesión del usuario digital?"})
    queue = steward.get("/curation/review", params={"limit": 50}).json()["items"]
    assert queue and all(i["description_source"] == "generated" or not i["description"] for i in queue)
    assert queue == sorted(queue, key=lambda i: -i["demand"])
    first = queue[0]
    assert {"asset_key", "kind", "database", "table", "column", "data_type", "domain", "demand"} <= set(first)

    body = {"asset_key": "VBank_ING.dbo.Users.LastLoginAt", "description": "Fecha y hora del último inicio de sesión."}
    assert analyst.put("/curation/description", json=body).status_code == 403
    r = steward.put("/curation/description", json=body)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["copies"] >= 1
    col = next(c for c in steward.get("/assets/VBank_ING.dbo.Users").json()["columns"] if c["name"] == "LastLoginAt")
    assert col["description_source"] == "human"


def test_historial_simulado_para_el_tablero(settings, tmp_path):
    """CONVERDATA_DEMO_HISTORY: 30 días de actividad simulada, marcada para no confundirla con un piloto real."""
    import json

    settings.demo_history = True
    app = create_app(settings, DemoConnector(FIXTURES))
    admin = client_for(app, "demo")
    assert build(admin)["status"] == "ok"
    rows = [json.loads(line) for p in settings.audit_dir.glob("*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()]
    seeded = [r for r in rows if r.get("simulated")]
    questions = [r for r in seeded if r["type"] == "question"]
    assert questions and all(r["client"] == "demo-seed" for r in seeded)
    days = {r["ts"][:10] for r in questions}
    assert 25 <= len(days) <= 31
    assert 5 <= len({r["user_id"] for r in questions}) <= 8
    assert all(r["discovery"] is not None and r["duration_ms"] > 0 for r in questions)
    feedback = [r for r in seeded if r["type"] == "feedback"]
    confirms = sum(f["verdict"] == "confirm" for f in feedback)
    assert 0.45 <= confirms / len(questions) <= 0.75 and any(f["verdict"] == "reject" for f in feedback)
    requests = json.loads((settings.curation_dir / "requests.json").read_text(encoding="utf-8"))
    simulated = [r for r in requests if r.get("simulated")]
    assert 3 <= len(simulated) <= 6 and any(r["status"] != "open" for r in simulated)

    metrics = admin.get("/admin/metrics", params={"days": 30}).json()
    assert metrics["questions"] >= len(questions) * 0.9 and len(metrics["per_day"]) >= 25
    assert metrics["time_to_confirm_s"]["p50"] is not None and 20 <= metrics["time_to_confirm_s"]["p50"] <= 90

    # Un segundo build no vuelve a sembrar.
    assert build(admin)["status"] == "ok"
    again = [line for p in settings.audit_dir.glob("*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()
             if '"simulated": true' in line]
    assert len(again) == len(seeded)
    # Lo simulado no entra al conocimiento: no hay golden de usuarios ficticios.
    golden = settings.data_root / "knowledge" / "golden" / "confirmaciones_usuarios.yaml"
    assert not golden.exists() or "analista0" not in golden.read_text(encoding="utf-8")
