"""ConverData-API de punta a punta con el servidor simulado (`DemoConnector` sobre tests/fixtures/bancos).

Primer arranque sin catálogo → login del admin con su usuario de BD → descubrimiento de esquemas → chat, explorador,
retroalimentación y auditoría; y la herencia de permisos con un login que solo lee dos BDs (F14).
"""

import json
import logging
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converdata_api.connector import DemoConnector
from converdata_api.main import create_app
from converdata_api.settings import ApiSettings

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "bancos"


@pytest.fixture
def settings(tmp_path):
    return ApiSettings(
        data_root=tmp_path / "catalog", inventory_path=tmp_path / "inventory.yaml", audit_dir=tmp_path / "audit",
        curation_dir=tmp_path / "curation", demo=True, demo_fixtures=[FIXTURE], demo_preload_inventory=False,
        allow_windows_auth=False,
    )


def make_client(settings):
    return TestClient(create_app(settings, DemoConnector(FIXTURE)))


def login(client, user="demo", **extra):
    body = {"login": user, "password": "demo", **extra}
    r = client.post("/auth/login", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def build(client):
    r = client.post("/admin/catalog/build", json={"enrich": False})
    assert r.status_code == 202, r.text
    for _ in range(200):
        job = client.get("/admin/catalog/build").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("la construcción no terminó")


@pytest.fixture
def ready(settings):
    """API con catálogo construido por el admin `demo`."""
    client = make_client(settings)
    login(client, host="demo-sql", alias="SQL demo")
    job = build(client)
    assert job["status"] == "ok", job
    return client


def test_first_run_without_catalog(settings):
    client = make_client(settings)
    status = client.get("/setup/status").json()
    assert status["has_inventory"] is False and status["has_catalog"] is False

    r = client.post("/auth/login", json={"login": "demo", "password": "demo"})
    assert r.status_code == 400  # sin inventario hay que indicar el servidor
    r = client.post("/auth/login", json={"login": "demo", "password": "mala", "host": "demo-sql"})
    assert r.status_code == 401
    # un login sin permisos de metadatos no puede registrar el primer servidor
    r = client.post("/auth/login", json={"login": "analista", "password": "demo", "host": "demo-sql"})
    assert r.status_code == 403

    data = login(client, host="demo-sql", alias="SQL demo")
    assert "data_admin" in data["user"]["roles"]
    assert client.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"}).status_code == 409
    status = client.get("/setup/status").json()
    assert status["servers"] == [{"id": "DEMO_SQL", "alias": "SQL demo", "environment": "desarrollo"}]
    assert "host" not in json.dumps(status["servers"])  # el host nunca se publica

    job = build(client)
    assert job["status"] == "ok" and job["report"]["objects"] > 0
    status = client.get("/setup/status").json()
    assert status["has_catalog"] and status["catalog"]["databases"] == 5
    assert (settings.data_root / "config" / "databases.yaml").is_file()
    assert "*" in settings.inventory_path.read_text(encoding="utf-8")  # el inventario guardado conserva "*"


def test_discover_feedback_and_audit(ready, settings):
    r = ready.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["status"] == "ok" and env["discovery"]["candidates"]
    top = env["discovery"]["candidates"][0]

    r = ready.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": top["asset_key"], "verdict": "confirm"})
    assert r.status_code == 200 and r.json()["confirmations"] == 1
    # solo se califican activos mostrados en esa respuesta
    r = ready.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": "X.dbo.Y", "verdict": "confirm"})
    assert r.status_code == 404
    golden = settings.data_root / "knowledge" / "golden" / "confirmaciones_usuarios.yaml"
    assert top["asset_key"] in golden.read_text(encoding="utf-8")

    kinds = [row["type"] for row in ready.get("/admin/audit").json()["items"]]
    assert {"login", "question", "feedback", "catalog_build_finished"} <= set(kinds)
    raw = "".join(p.read_text(encoding="utf-8") for p in settings.audit_dir.glob("*.jsonl"))
    assert '"demo"' in raw and "password" not in raw
    assert ready.get("/me/history").json()["items"][0]["trace_id"] == env["trace_id"]


def test_catalog_explorer(ready):
    dbs = ready.get("/catalog/databases").json()
    assert {d["database"] for d in dbs} >= {"BancaPrestamos", "BancaLeasing"}
    page = ready.get("/catalog/objects", params={"database": "BancaPrestamos"}).json()
    assert page["total"] > 0
    obj = ready.get("/catalog/object", params={"id": page["items"][0]["id"]}).json()
    assert obj["columns"] and obj["server_alias"] == "SQL demo"
    by_key = ready.get(f"/assets/{page['items'][0]['asset_key']}.ColumnaX").json()
    assert by_key["id"] == obj["id"]


def test_permissions_are_inherited(ready, settings):
    analyst = make_client(settings)
    analyst.app = ready.app  # mismo proceso, otra sesión
    data = login(analyst, user="analista")
    assert "data_admin" not in data["user"]["roles"]
    dbs = {d["database"] for d in analyst.get("/catalog/databases").json()}
    assert dbs == {"BancaPrestamos", "BancaCuentasDebito"}
    hidden = ready.get("/catalog/objects", params={"database": "BancaLeasing"}).json()["items"][0]["id"]
    assert analyst.get("/catalog/object", params={"id": hidden}).status_code == 404
    env = analyst.post("/discover", json={"question": "¿Dónde está el contrato de leasing?"}).json()
    shown = [c["database"] for c in (env.get("discovery") or {}).get("candidates", [])]
    assert "BancaLeasing" not in shown
    assert analyst.post("/admin/catalog/build", json={}).status_code == 403
    assert analyst.get("/admin/audit").status_code == 403


def test_session_required_and_logout(ready):
    anon = TestClient(ready.app)
    assert anon.post("/discover", json={"question": "hola mundo"}).status_code == 401
    assert ready.post("/auth/logout").status_code == 200
    assert ready.get("/auth/me").status_code == 401


def test_stream_escalation_and_rate_limit(ready, settings):
    with ready.stream("POST", "/discover/stream", json={"question": "¿Dónde está el DUI del cliente?"}) as r:
        body = "".join(r.iter_text())
    assert "event: step" in body and "event: answer" in body
    answer = json.loads(body.split("event: answer\ndata: ")[1].split("\n")[0])
    req = ready.post("/curation/requests", json={"trace_id": answer["trace_id"]})
    assert req.status_code == 200 and req.json()["status"] == "open"
    mine = ready.get("/me/requests").json()["items"]
    assert mine[0]["id"] == req.json()["id"] and mine[0]["answer"] is None
    login_resp = ready.post("/login", json={"login": "demo", "password": "demo"}).json()  # alias OP-04
    assert login_resp["servers"] == [{"alias": "SQL demo", "ok": True}] and "BancaLeasing" in login_resp["databases"]
    for _ in range(30):
        ready.post("/discover", json={"question": "clientes"})
    assert ready.post("/discover", json={"question": "clientes"}).status_code == 429


def test_health_metrics_cuenta_sin_contenido_y_solo_para_admin(ready, settings):
    secret = "pregunta-secreta-sobre-el-dui-del-cliente"
    ready.post("/discover", json={"question": secret})
    ready.post("/auth/login", json={"login": "nadie", "password": "mal", "host": "demo-sql"})
    snap = ready.get("/health/metrics")
    assert snap.status_code == 200
    data = snap.json()
    assert data["routes"]["discover"]["requests"] >= 1 and data["routes"]["discover"]["p95_ms"] is not None
    assert data["counters"].get("login_failed", 0) >= 1
    assert secret not in snap.text  # D5: ningún contenido de preguntas
    analyst = TestClient(ready.app)
    login(analyst, user="analista")
    assert analyst.get("/health/metrics").status_code == 403
    assert TestClient(ready.app).get("/health/metrics").status_code == 401


def test_logs_json_sin_contenido(settings, tmp_path):
    settings.log_dir, settings.event_log = tmp_path / "logs", False
    client = make_client(settings)
    login(client, host="demo-sql", alias="SQL demo")
    build(client)
    secret = "pregunta-secreta-sobre-el-dui-del-cliente"
    r = client.post("/discover", json={"question": secret}, headers={"Authorization": "Bearer token-que-no-debe-salir"})
    client.get("/catalog/objects", params={"q": "termino-de-busqueda-privado"})
    for handler in logging.getLogger("converdata").handlers:
        handler.flush()
    text = (tmp_path / "logs" / "converdata.log").read_text(encoding="utf-8")
    events = [json.loads(line) for line in text.splitlines()]
    assert any(e["event"] == "http.request" and e["route"] == "discover" and e["http_status"] == r.status_code for e in events)
    for forbidden in (secret, "token-que-no-debe-salir", "Authorization", "Bearer", "termino-de-busqueda-privado", "demo"):
        assert forbidden not in text, forbidden


def test_reglas_de_negocio_gestionadas_por_el_steward(ready, settings):
    asset = "BancaPrestamos.dbo.Prestamos.CategoriaRiesgo"
    hidden = "BancaLeasing.dbo.Activos.TipoActivo"  # el analista no lee BancaLeasing
    steward = TestClient(ready.app)
    login(steward, user="responsable")
    analyst = TestClient(ready.app)
    login(analyst, user="analista")

    assert analyst.put("/curation/rules", json={"id": "BR-PRE-001", "text": "Regla que no debe guardarse", "applies_to": [asset]}).status_code == 403
    ok = steward.put("/curation/rules", json={"id": "BR-PRE-001", "applies_to": [asset], "domain": "prestamos",
                                              "text": "La categoría de riesgo se recalcula cada mes con la mora vigente."})
    assert ok.status_code == 200 and ok.json()["rule"]["reviewed"] is True
    steward.put("/curation/rules", json={"id": "BR-LEA-001", "applies_to": [hidden], "text": "Regla de leasing solo para quien lo ve."})

    assert steward.put("/curation/rules", json={"id": "BR-X-001", "applies_to": ["Nada.dbo.No.existe"], "text": "Activo inexistente aquí"}).status_code == 404
    assert [r["id"] for r in steward.get("/curation/rules").json()["items"]] == ["BR-PRE-001", "BR-LEA-001"]

    env = analyst.post("/discover", json={"question": "¿Qué reglas aplican a la categoría de riesgo del préstamo?"}).json()
    shown = {r["id"] for c in env["discovery"]["candidates"] for r in c["business_rules"]}
    assert "BR-PRE-001" in shown and "BR-LEA-001" not in shown  # con su fuente; sin fugas (F14)
    card = analyst.get(f"/assets/{asset}").json()
    assert any(r["id"] == "BR-PRE-001" for r in card["business_rules"])

    assert steward.delete("/curation/rules/BR-PRE-001").status_code == 200
    assert steward.delete("/curation/rules/BR-PRE-001").status_code == 404


def test_tope_diario_de_tokens_por_usuario(settings):
    settings.token_limit_daily = 1000
    client = make_client(settings)
    login(client, host="demo-sql", alias="SQL demo")
    build(client)
    ledger = client.app.state.tokens
    analyst = TestClient(client.app)
    login(analyst, user="analista")

    assert analyst.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"}).status_code == 200
    ledger.add("analista", 1500)  # lo que gastarían varias consultas con IA
    blocked = analyst.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"})
    assert blocked.status_code == 429 and "tope diario" in blocked.json()["detail"]
    assert analyst.post("/discover/stream", json={"question": "¿Dónde está el DUI?"}).status_code == 429
    assert client.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"}).status_code == 200  # otro usuario
    assert analyst.get("/catalog/databases").status_code == 200  # explorar el catálogo sigue disponible
    assert client.get("/health/metrics").json()["counters"]["token_limit"] == 2


def test_el_tope_se_restablece_al_cambiar_de_dia():
    import datetime as dt
    from converdata_api.tokens import TokenLedger

    now = [dt.datetime(2026, 10, 27, 23, 0, tzinfo=dt.timezone.utc)]
    ledger = TokenLedger(100, clock=lambda: now[0])
    ledger.add("ana", 120)
    assert ledger.exceeded("ana")
    now[0] += dt.timedelta(hours=2)
    assert not ledger.exceeded("ana") and ledger.used("ana") == 0


def test_el_uso_del_gateway_se_atribuye_al_usuario_y_a_las_metricas(settings):
    client = make_client(settings)
    login(client, host="demo-sql", alias="SQL demo")
    runtime, ledger = client.app.state.runtime, client.app.state.tokens
    with ledger.as_user("analista"):
        runtime._on_usage("planner", 300, 120)  # lo que el gateway informa tras cada llamada al LLM
    runtime._on_usage("planner", 50, 10)  # sin usuario en contexto (p. ej. indexación): solo cuenta en métricas
    assert ledger.used("analista") == 420
    assert client.get("/health/metrics").json()["tokens"] == {"in": 350, "out": 130}


def test_tope_agotado_en_modo_determinista_responde_sin_ia(settings):
    settings.token_limit_daily, settings.token_limit_mode = 1000, "deterministic"
    client = make_client(settings)
    login(client, host="demo-sql", alias="SQL demo")
    build(client)
    analyst = TestClient(client.app)
    login(analyst, user="analista")
    client.app.state.tokens.add("analista", 5000)
    r = analyst.post("/discover", json={"question": "¿Dónde está el puntaje de riesgo crediticio del cliente?"})
    assert r.status_code == 200 and any("sin IA generativa" in a for a in r.json()["assumptions"])
    assert r.json()["discovery"]["candidates"]  # sigue encontrando el dato
    streamed = analyst.post("/discover/stream", json={"question": "¿Dónde está el puntaje de riesgo crediticio del cliente?"})
    assert streamed.status_code == 200 and "sin IA generativa" in streamed.text
    assert client.get("/health/metrics").json()["counters"]["token_limit_deterministic"] == 2


def test_ingesta_de_diccionario_no_pisa_lo_humano_y_es_idempotente(ready):
    steward = TestClient(ready.app)
    login(steward, user="responsable")
    analyst = TestClient(ready.app)
    login(analyst, user="analista")
    human = "BancaPrestamos.dbo.Prestamos.CategoriaRiesgo"
    other = "BancaPrestamos.dbo.Prestamos.MontoDesembolsado"
    steward.put("/curation/description", json={"asset_key": human, "description": "Descripción escrita por una persona."})
    csv_text = (
        "asset_key,description,synonyms\n"
        f"{human},Texto del diccionario que no debe pisar lo humano,riesgo\n"
        f"{other},Monto oficial desembolsado al cliente según el core,desembolso;monto entregado\n"
        "Nada.dbo.No.existe,Fila que no corresponde a ningún activo,\n"
    )
    first = steward.post("/curation/dictionary", json={"csv": csv_text})
    assert first.status_code == 200
    report = first.json()
    assert report["applied"] >= 1 and report["skipped_human"] >= 1 and report["unknown"] == ["Nada.dbo.No.existe"]

    def column(key):
        table = analyst.get(f"/assets/{key.rsplit('.', 1)[0]}").json()
        return next(c for c in table["columns"] if c["name"] == key.rsplit(".", 1)[1])

    assert column(human)["description"] == "Descripción escrita por una persona."
    assert column(human)["description_source"] == "human"
    assert column(other)["description"].startswith("Monto oficial") and column(other)["description_source"] == "data_dictionary"

    again = steward.post("/curation/dictionary", json={"csv": csv_text}).json()
    assert again["unchanged"] is True and again["applied"] == 0  # mismo hash: sin trabajo ni reindexado
    assert analyst.post("/curation/dictionary", json={"csv": csv_text}).status_code == 403
