"""HU-06 y HU-09 · DiscoveryDataAgent-API con todo su estado en la BD `DiscoveryDataAgent` real (OP-02).

Catálogo, conocimiento, curación e inventario viven en la BD; el servidor de aplicación no guarda archivos. Necesita
`DISCOVERY_DATA_AGENT_TEST_DB` (ver `conftest.py` de la raíz); sin ella se omite.
"""

import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from discovery_data_agent.models.knowledge import BusinessRule
from discovery_data_agent.storage.catalog_repository import SqlServerCatalogRepository
from discovery_data_agent_api.connector import DemoConnector
from discovery_data_agent_api.main import create_app
from discovery_data_agent_api.settings import ApiSettings

from test_api import FIXTURE, build, login, settings  # noqa: F401  (fixtures de la API)

pytestmark = pytest.mark.sqlserver
CLIENTES = "BancaPrestamos.dbo.Clientes"


def start(settings) -> TestClient:  # noqa: F811
    return TestClient(create_app(settings, DemoConnector(FIXTURE)))


@pytest.fixture
def client(settings, empty_catalog_db, db_connect):  # noqa: F811
    settings.db = empty_catalog_db
    conn = db_connect()  # cada prueba parte de un primer arranque: sin inventario, responsables ni dudas
    conn.cursor().execute("DELETE FROM catalog.inventory_server; DELETE FROM curation.steward; "
                          "DELETE FROM curation.request; DELETE FROM curation.vote")
    conn.commit()
    conn.close()
    api = start(settings)
    login(api, host="demo-sql", alias="SQL demo")
    assert build(api)["status"] == "ok"
    yield api
    api.app.state.runtime.drain()  # ninguna publicación en segundo plano sobrevive a la prueba (la BD es compartida)


@pytest.fixture
def repo(db_connect):
    return SqlServerCatalogRepository(db_connect)


def describe(api, text: str, asset_key: str = CLIENTES):
    return api.put("/curation/description", json={"asset_key": asset_key, "description": text})


def description_of(api, asset_key: str = CLIENTES) -> str:
    r = api.get(f"/assets/{asset_key}")
    assert r.status_code == 200, r.text
    return r.json()["description"]


def rows(db_connect, sql, *params):
    conn = db_connect()
    try:
        return [tuple(r) for r in conn.cursor().execute(sql, *params).fetchall()]
    finally:
        conn.close()


def ask(api, question="¿Dónde está el DUI del cliente?"):
    env = api.post("/discover", json={"question": question}).json()
    return env, env["discovery"]["candidates"][0]["asset_key"]


def vote(api, env, asset_key, verdict="confirm"):
    r = api.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": asset_key, "verdict": verdict})
    assert r.status_code == 200, r.text
    api.app.state.runtime.drain()
    return r.json()


def test_el_build_publica_el_catalogo_en_la_bd(client, repo):
    loaded, version = repo.load()
    runtime = client.app.state.runtime
    assert runtime.db_version == version
    assert {o.id for o in loaded.objects} == {o.id for o in runtime.service.deps.catalog.objects}
    assert len(loaded.objects) > 30 and loaded.knowledge.entities


def test_el_servidor_no_guarda_estado_en_disco(client, settings, repo, monkeypatch):  # noqa: F811
    """HU-09: catálogo, inventario y curación viven en la BD; el build usa un directorio temporal que se borra."""
    made, real = [], tempfile.mkdtemp

    def recording(*args, **kwargs):
        made.append(Path(real(*args, **kwargs)))
        return str(made[-1])

    monkeypatch.setattr("discovery_data_agent_api.runtime.tempfile.mkdtemp", recording)
    assert describe(client, "Clientes del banco").status_code == 200
    env, top = ask(client)
    vote(client, env, top)
    assert client.post("/curation/requests", json={"trace_id": env["trace_id"]}).status_code == 200
    csv = "asset_key,description\nBancaPrestamos.dbo.Clientes.DUI,Documento único de identidad del cliente\n"
    assert client.post("/curation/dictionary", json={"csv": csv}).json()["applied"] == 1
    assert build(client)["status"] == "ok"
    for path in (settings.data_root, settings.inventory_path, settings.curation_dir):
        assert not path.exists(), path
    assert len(made) == 1 and made[0].name.startswith("discovery-data-agent-build-") and not made[0].exists()
    assert [s.host for s in repo.inventory()] == ["demo-sql"]  # el inventario, con su host, está en la BD


def test_una_edicion_de_curacion_queda_en_la_bd_con_su_autor(client, repo):
    time.sleep(0.05)
    before = repo.version()
    assert describe(client, "Clientes del banco con préstamos vigentes").status_code == 200
    assert description_of(client) == "Clientes del banco con préstamos vigentes"
    assert repo.version() == before + 1  # escribe sus filas: no publica todo el catálogo
    last = repo.description_history(CLIENTES)[-1]
    assert (last["description"], last["description_source"], last["modified_by"]) == (
        "Clientes del banco con préstamos vigentes", "human", "demo")


def test_el_historial_de_descripciones_se_ve_en_curacion(client):
    time.sleep(0.05)
    assert describe(client, "Primera versión").status_code == 200
    time.sleep(0.05)
    assert describe(client, "Segunda versión").status_code == 200
    data = client.get("/curation/history", params={"asset_key": CLIENTES}).json()
    assert data["available"] is True
    newest, previous = data["items"][0], data["items"][1]
    assert (newest["description"], newest["modified_by"], newest["valid_to"]) == ("Segunda versión", "demo", None)
    assert previous["description"] == "Primera versión" and previous["valid_to"] is not None
    assert newest["server_alias"] == "SQL demo" and "demo-sql" not in str(data)  # nunca el host
    assert client.get("/curation/history", params={"asset_key": "No.Existe.Tabla"}).status_code == 404
    analyst = TestClient(client.app)
    login(analyst, user="analista")
    assert analyst.get("/curation/history", params={"asset_key": CLIENTES}).status_code == 403


def test_otra_instancia_arranca_con_lo_publicado_sin_archivos_previos(client, settings, tmp_path):  # noqa: F811
    """HU-09: el servidor no depende de ningún archivo; otro servidor con el disco vacío arranca desde la BD."""
    assert describe(client, "Descripción que debe sobrevivir al servidor").status_code == 200
    put = client.put("/admin/stewards", json={"stewards": [{"login": "Responsable", "domains": ["prestamos"]}]})
    assert put.status_code == 200 and put.json()["stewards"] == [{"login": "responsable", "domains": ["prestamos"]}]
    other = ApiSettings(
        data_root=tmp_path / "otro" / "catalog", inventory_path=tmp_path / "otro" / "inventory.yaml",
        audit_dir=tmp_path / "otro" / "audit", curation_dir=tmp_path / "otro" / "curation", demo=True,
        demo_fixtures=[FIXTURE], demo_preload_inventory=False, allow_windows_auth=False, db=settings.db)
    second = start(other)
    status = second.get("/setup/status").json()
    assert status["has_catalog"] is True and status["has_inventory"] is True
    assert "steward" in login(second, user="responsable")["user"]["roles"]  # el rol también sale de la BD
    assert description_of(second) == "Descripción que debe sobrevivir al servidor"
    r = second.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert not (tmp_path / "otro").exists()


def test_la_api_carga_lo_que_publica_el_builder_sin_reiniciar(client, repo):
    """Decisión 12: el Builder es otro proceso; la API detecta la versión nueva y recarga."""
    runtime = client.app.state.runtime
    before = runtime.db_version
    snapshot, _ = repo.load("build")
    next(o for o in snapshot.objects if o.asset_key == CLIENTES).row_count = 987654
    assert repo.publish(snapshot, published_by="builder", reason="build", scope="build").version > before
    runtime._db_checked = 0.0  # como si hubieran pasado los 15 s entre comprobaciones
    assert client.get(f"/assets/{CLIENTES}").json()["row_count"] == 987654
    assert runtime.db_version > before


def test_el_refresco_del_builder_no_pisa_lo_que_edito_el_responsable(client, repo):
    stale, _ = repo.load("build")  # copia del Builder anterior a la edición
    assert describe(client, "Texto del responsable").status_code == 200
    repo.publish(stale, published_by="builder", reason="build", scope="build")
    client.app.state.runtime._db_checked = 0.0
    assert description_of(client) == "Texto del responsable"


def publish_rule_elsewhere(repo, rule_id: str) -> None:
    """Otro proceso (otra instancia de la API) escribe en la BD sin que esta instancia se entere."""
    repo.upsert_rule(BusinessRule(id=rule_id, text="Regla escrita por otro proceso", applies_to=[CLIENTES],
                                  source="steward:otro"), by="otro")


def test_una_edicion_no_pisa_lo_que_escribio_otro_proceso(client, repo):
    """Cada edición escribe solo sus filas: no hay foto que publicar ni conflicto que repetir."""
    runtime = client.app.state.runtime
    publish_rule_elsewhere(repo, "BR-OTRO-PROCESO")
    runtime._db_checked = time.monotonic()  # la comprobación periódica todavía no toca
    real, raced = runtime.writer.write_descriptions, []

    def racing(edits, **kwargs):  # y otro más escribe justo entre la comprobación y la escritura
        if not raced:
            raced.append(True)
            publish_rule_elsewhere(repo, "BR-CARRERA")
        return real(edits, **kwargs)

    runtime.writer.write_descriptions = racing
    try:
        assert describe(client, "Edición sobre el catálogo vigente").status_code == 200
    finally:
        del runtime.writer.write_descriptions
    loaded, _ = repo.load()
    assert {"BR-OTRO-PROCESO", "BR-CARRERA"} <= {r.id for r in loaded.knowledge.rules}
    assert description_of(client) == "Edición sobre el catálogo vigente"
    listed = {r["id"] for r in client.get("/curation/rules").json()["items"]}
    assert {"BR-OTRO-PROCESO", "BR-CARRERA"} <= listed  # y esta instancia ya las ve


def test_si_la_escritura_falla_no_queda_nada_a_medias(client, repo):
    """La BD cae al escribir: quien editaba recibe un error, nada cambia y el mismo diccionario se puede repetir."""
    runtime = client.app.state.runtime
    csv = "asset_key,description\nBancaPrestamos.dbo.Clientes.DUI,Documento único de identidad del cliente\n"

    def broken(edits, **kwargs):
        raise ConnectionError("BD DiscoveryDataAgent inaccesible")

    runtime.writer.write_descriptions = broken
    quiet = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    try:
        assert describe(quiet, "Edición huérfana").status_code == 500
        assert quiet.post("/curation/dictionary", json={"csv": csv}).status_code == 500
    finally:
        del runtime.writer.write_descriptions
    assert description_of(client) != "Edición huérfana"
    assert "Edición huérfana" not in {o.description for o in repo.load()[0].objects}
    again = client.post("/curation/dictionary", json={"csv": csv})
    assert again.status_code == 200 and again.json()["applied"] == 1 and again.json()["unchanged"] is False
    assert client.post("/curation/dictionary", json={"csv": csv}).json()["unchanged"] is True  # ya aplicado: no hace nada


def test_dos_ediciones_a_la_vez_quedan_las_dos_y_cada_una_a_su_nombre(client, repo):
    """RF-34: cada edición es atómica y queda a nombre de quien la hizo."""
    import threading

    assert client.put("/admin/stewards", json={"stewards": [{"login": "responsable", "domains": ["*"]}]}).status_code == 200
    other = TestClient(client.app)
    login(other, user="responsable")
    results = {}

    def edit(name, api, asset, text):
        results[name] = describe(api, text, asset).status_code

    threads = [threading.Thread(target=edit, args=("a", client, CLIENTES, "Clientes, por la primera sesión")),
               threading.Thread(target=edit, args=("b", other, "BancaPrestamos.dbo.Prestamos", "Préstamos, por la segunda"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert results == {"a": 200, "b": 200}
    first, second = repo.description_history(CLIENTES)[-1], repo.description_history("BancaPrestamos.dbo.Prestamos")[-1]
    assert (first["description"], first["modified_by"]) == ("Clientes, por la primera sesión", "demo")
    assert (second["description"], second["modified_by"]) == ("Préstamos, por la segunda", "responsable")


def test_la_confirmacion_guarda_una_plantilla_sin_literales(client, repo, db_connect):
    """F17: lo que entra al índice es la plantilla anónima; el documento del cliente no sale de la auditoría."""
    assert client.put("/admin/stewards", json={"stewards": []}).status_code == 200  # dos usuarios de consulta
    first = TestClient(client.app)
    login(first, user="responsable")
    env, top = ask(first, "¿Dónde está el DUI del cliente 01234567-8?")
    assert vote(first, env, top)["learned"] is True
    [golden] = repo.load()[0].knowledge.golden
    assert golden.template == "donde esta el dui del cliente" and golden.asset_keys == [top]
    # El original llevaba un dato personal: no se guarda fuera de la auditoría (que tiene su retención).
    assert rows(db_connect, "SELECT COUNT(*) FROM golden.golden_discovery_original") == [(0,)]
    assert rows(db_connect, "SELECT COUNT(*) FROM curation.vote WHERE golden_id = ?", golden.id) == [(1,)]
    assert rows(db_connect, "SELECT COUNT(*) FROM audit.audit_discovery_feedback WHERE trace_id = ?", env["trace_id"]) == [(1,)]
    stored = str(rows(db_connect, "SELECT template FROM knowledge.golden_discovery")) + str(
        rows(db_connect, "SELECT * FROM curation.vote"))
    assert "01234567" not in stored
    # La misma pregunta con otro documento es la misma confirmación: con la segunda ya pesa en la confianza.
    other = TestClient(client.app)
    login(other, user="analista")
    env2, top2 = ask(other, "¿dónde está el DUI del cliente 98765432-1?")
    assert top2 == top and vote(other, env2, top2)["confirmations"] == 2
    [golden] = repo.load()[0].knowledge.golden
    assert (golden.confirmations, golden.confirmed_by) == (2, "users")


def test_un_identificador_alfanumerico_tampoco_llega_a_la_plantilla(client, repo, db_connect):
    """Una cuenta o un pasaporte mezclan letras y dígitos: se quitan igual, y el texto original no se guarda."""
    env, top = ask(client, "¿Dónde está el DUI del cliente? Su cuenta es SV62CENT00000000000700025")
    result = vote(client, env, top)
    assert result["learned"] is True and result["confirmations"] == 1
    [golden] = repo.load()[0].knowledge.golden
    assert golden.template == "donde esta el dui del cliente su cuenta es"
    assert rows(db_connect, "SELECT COUNT(*) FROM golden.golden_discovery_original") == [(0,)]
    assert rows(db_connect, "SELECT COUNT(*) FROM audit.audit_discovery_feedback WHERE trace_id = ?", env["trace_id"]) == [(1,)]


def test_una_regla_curada_y_una_confirmacion_llegan_a_la_bd(client, repo, db_connect):
    rule = {"id": "BR-PRUEBA-API", "text": "Solo clientes con préstamo activo", "applies_to": [CLIENTES]}
    assert client.put("/curation/rules", json=rule).status_code == 200
    env, top = ask(client)
    vote(client, env, top)
    loaded, _version = repo.load()
    assert "BR-PRUEBA-API" in {r.id for r in loaded.knowledge.rules}
    assert [g.asset_keys for g in loaded.knowledge.golden] == [[top]]
    assert rows(db_connect, "SELECT question FROM golden.golden_discovery_original") == [("¿Dónde está el DUI del cliente?",)]
    assert client.delete("/curation/rules/BR-PRUEBA-API").status_code == 200
    assert "BR-PRUEBA-API" not in {r.id for r in repo.load()[0].knowledge.rules}


def test_una_duda_escalada_vive_en_la_bd_y_su_respuesta_entra_al_indice(client, repo, db_connect):
    """F24 CA1: la respuesta del responsable queda como conocimiento y la siguiente pregunta equivalente la encuentra."""
    question = "¿En qué tabla está el saldo insoluto del préstamo?"
    env, _top = ask(client, question)
    created = client.post("/curation/requests", json={"trace_id": env["trace_id"], "note": "urgente"})
    assert created.status_code == 200
    request_id = created.json()["id"]
    assert client.post("/curation/requests", json={"trace_id": env["trace_id"]}).json()["id"] == request_id  # una sola
    assert rows(db_connect, "SELECT status, user_id, note FROM curation.request") == [("open", "demo", "urgente")]
    [inbox] = client.get("/curation/requests").json()["items"]
    assert inbox["question"] == question
    target = "BancaPrestamos.dbo.Prestamos"
    answer = client.post(f"/curation/requests/{request_id}/answer", json={
        "kind": "asset", "asset_key": target, "description": "Préstamos vigentes y su saldo"})
    assert answer.status_code == 200, answer.text
    assert rows(db_connect, "SELECT status FROM curation.request") == [("answered",)]
    [mine] = client.get("/me/requests").json()["items"]
    assert mine["status"] == "answered" and mine["answer"]["asset_key"] == target
    assert description_of(client, target) == "Préstamos vigentes y su saldo"
    golden = next(g for g in repo.load()[0].knowledge.golden if g.asset_keys == [target])
    assert golden.confirmed_by == "steward"
    again = client.post("/discover", json={"question": question}).json()
    assert target in [c["asset_key"] for c in again["discovery"]["candidates"]]


def test_los_responsables_se_administran_desde_la_api_y_quedan_auditados(client, db_connect):
    count = "SELECT COUNT(*) FROM audit.audit_event WHERE kind = 'stewards_updated' AND user_id = 'demo'"
    [(before,)] = rows(db_connect, count)
    analyst = TestClient(client.app)
    login(analyst, user="analista")
    assert analyst.get("/admin/stewards").status_code == 403
    assert analyst.get("/curation/review").status_code == 403
    r = client.put("/admin/stewards", json={"stewards": [{"login": "ANALISTA", "domains": ["prestamos", "prestamos"]}]})
    assert r.status_code == 200
    data = client.get("/admin/stewards").json()
    assert data["stewards"] == [{"login": "analista", "domains": ["prestamos"]}] and "prestamos" in data["domains"]
    assert "steward" in analyst.get("/auth/me").json()["roles"]
    assert analyst.get("/curation/review").status_code == 200
    assert client.put("/admin/stewards", json={"stewards": [{"login": "a;b", "domains": ["*"]}]}).status_code == 422
    assert client.put("/admin/stewards", json={"stewards": []}).status_code == 200
    assert "steward" not in analyst.get("/auth/me").json()["roles"]  # quitar el rol surte efecto de inmediato
    assert rows(db_connect, count) == [(before + 2,)]  # la solicitud rechazada (422) no llegó a aplicarse ni a auditarse
    history = rows(db_connect, "SELECT modified_by FROM curation.steward FOR SYSTEM_TIME ALL WHERE login = 'analista'")
    assert history and set(history) == {("demo",)}  # el historial temporal dice quién dio el rol


def test_el_voto_del_responsable_rige_en_la_siguiente_busqueda(client, repo):
    """F24 CA2: su "✔" entra de inmediato y su "✖" retira la pareja, sin esperar a ninguna recarga en segundo plano."""
    question = "¿Dónde está el DUI del cliente?"

    def golden_evidence(api):
        top = api.post("/discover", json={"question": question}).json()["discovery"]["candidates"][0]
        return [e["source"] for e in top.get("evidence", []) if e["kind"] == "golden_discovery"]

    env, top = ask(client, question)
    r = client.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": top, "verdict": "confirm"})
    assert r.status_code == 200
    assert golden_evidence(client) == ["confirmado por el responsable"]  # sin `drain()`
    env, top = ask(client, question)
    r = client.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": top, "verdict": "reject"})
    assert r.status_code == 200 and golden_evidence(client) == []
    assert [g.rejected for g in repo.load()[0].knowledge.golden] == [True]


def test_si_el_catalogo_no_recarga_tras_editar_no_se_sirve_lo_anterior(client, repo, monkeypatch):
    """Tras una escritura, si el índice no se puede reconstruir, quien editó recibe el error y nadie ve lo retirado."""
    runtime = client.app.state.runtime
    rule = {"id": "BR-RETIRADA", "text": "Regla que se va a retirar", "applies_to": [CLIENTES]}
    assert client.put("/curation/rules", json=rule).status_code == 200
    real = runtime._build_service
    monkeypatch.setattr(runtime, "_build_service", lambda gateway: (_ for _ in ()).throw(ValueError("índice roto")))
    quiet = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    assert quiet.delete("/curation/rules/BR-RETIRADA").status_code == 500
    assert "BR-RETIRADA" not in {r.id for r in repo.load()[0].knowledge.rules}  # el borrado sí es firme
    blocked = quiet.get(f"/assets/{CLIENTES}")
    assert blocked.status_code == 409 and "ValueError" not in blocked.text  # ni lo anterior ni el tipo del error
    monkeypatch.setattr(runtime, "_build_service", real)
    runtime.reload()
    assert all(r["id"] != "BR-RETIRADA" for r in client.get(f"/assets/{CLIENTES}").json()["business_rules"])


def test_un_cambio_que_falla_deja_constancia_de_que_no_se_aplico(client, db_connect):
    runtime = client.app.state.runtime
    runtime.writer.write_descriptions = lambda edits, **kw: (_ for _ in ()).throw(ConnectionError("BD inaccesible"))
    quiet = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    try:
        assert describe(quiet, "Edición que no llega").status_code == 500
    finally:
        del runtime.writer.write_descriptions
    events = rows(db_connect, "SELECT TOP 2 kind, data_json FROM audit.audit_event WHERE kind LIKE 'curation_description%' "
                              "ORDER BY id DESC")
    assert [kind for kind, _ in events] == ["curation_description_failed", "curation_description"]
    assert "ConnectionError" in events[0][1] and "BD inaccesible" not in events[0][1]  # el tipo, no el texto


def test_dos_votos_a_la_vez_cuentan_los_dos(client, repo):
    """El voto y la confirmación que resulta se escriben juntos: ninguno pisa el recuento del otro."""
    import threading

    assert client.put("/admin/stewards", json={"stewards": []}).status_code == 200
    voters = []
    for user in ("analista", "responsable"):
        api = TestClient(client.app)
        login(api, user=user)
        voters.append((api, *ask(api)))
    threads = [threading.Thread(target=lambda a=api, e=env, t=top: a.post(
        "/discover/feedback", json={"trace_id": e["trace_id"], "asset_key": t, "verdict": "confirm"}))
        for api, env, top in voters]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    client.app.state.runtime.drain()
    [golden] = repo.load()[0].knowledge.golden
    assert (golden.confirmed_by, golden.confirmations) == ("users", 2)
