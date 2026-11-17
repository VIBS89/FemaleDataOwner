"""HU-06 y HU-09 · ConverData-API con el catálogo en la BD `ConverData` real (OP-02).

La BD es la fuente de verdad; `data_root` es una copia de trabajo. Necesita `CONVERDATA_TEST_DB` (ver `conftest.py` de la
raíz); sin ella se omite.
"""

import time

import pytest
from fastapi.testclient import TestClient

from converdata.catalog.store import load_snapshot
from converdata.models.knowledge import BusinessRule
from converdata.storage.catalog_repository import SqlServerCatalogRepository
from converdata_api.connector import DemoConnector
from converdata_api.main import create_app
from converdata_api.settings import ApiSettings

from test_api import FIXTURE, build, login, settings  # noqa: F401  (fixtures de la API)

pytestmark = pytest.mark.sqlserver
CLIENTES = "BancaPrestamos.dbo.Clientes"


def start(settings) -> TestClient:  # noqa: F811
    return TestClient(create_app(settings, DemoConnector(FIXTURE)))


@pytest.fixture
def client(settings, empty_catalog_db):  # noqa: F811
    settings.db = empty_catalog_db
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


def test_el_build_publica_el_catalogo_en_la_bd(client, repo):
    loaded, version = repo.load()
    runtime = client.app.state.runtime
    assert runtime.db_version == version
    assert {o.id for o in loaded.objects} == {o.id for o in runtime.service.deps.catalog.objects}
    assert len(loaded.objects) > 30 and loaded.knowledge.entities


def test_una_edicion_de_curacion_queda_en_la_bd_con_su_autor(client, repo):
    time.sleep(0.05)
    assert describe(client, "Clientes del banco con préstamos vigentes").status_code == 200
    assert description_of(client) == "Clientes del banco con préstamos vigentes"
    last = repo.description_history(CLIENTES)[-1]
    assert (last["description"], last["description_source"], last["modified_by"]) == (
        "Clientes del banco con préstamos vigentes", "human", "demo")


def test_otra_instancia_arranca_con_lo_publicado_sin_archivos_previos(client, settings, tmp_path):  # noqa: F811
    """HU-09: el servidor no depende de archivos de catálogo; un disco vacío se reconstruye desde la BD."""
    assert describe(client, "Descripción que debe sobrevivir al servidor").status_code == 200
    other = ApiSettings(
        data_root=tmp_path / "otro" / "catalog", inventory_path=settings.inventory_path,
        audit_dir=tmp_path / "otro" / "audit", curation_dir=tmp_path / "otro" / "curation", demo=True,
        demo_fixtures=[FIXTURE], demo_preload_inventory=False, allow_windows_auth=False, db=settings.db)
    second = start(other)
    assert second.get("/setup/status").json()["has_catalog"] is True
    login(second)
    assert description_of(second) == "Descripción que debe sobrevivir al servidor"
    r = second.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"})
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_la_api_carga_lo_que_publica_el_builder_sin_reiniciar(client, repo, settings):  # noqa: F811
    """Decisión 12: el Builder es otro proceso; la API detecta la versión nueva y recarga."""
    runtime = client.app.state.runtime
    before = runtime.db_version
    snapshot = load_snapshot(settings.data_root)
    target = next(o for o in snapshot.objects if o.asset_key == CLIENTES)
    target.row_count = 987654
    assert repo.publish(snapshot, published_by="builder", reason="build", scope="build").version > before
    runtime._db_checked = 0.0  # como si hubieran pasado los 15 s entre comprobaciones
    assert client.get(f"/assets/{CLIENTES}").json()["row_count"] == 987654
    assert runtime.db_version > before


def test_el_refresco_del_builder_no_pisa_lo_que_edito_el_responsable(client, repo, settings):  # noqa: F811
    stale = load_snapshot(settings.data_root)  # copia del Builder anterior a la edición
    assert describe(client, "Texto del responsable").status_code == 200
    repo.publish(stale, published_by="builder", reason="build", scope="build")
    client.app.state.runtime._db_checked = 0.0
    assert description_of(client) == "Texto del responsable"


def publish_rule_elsewhere(repo, settings, rule_id: str) -> None:  # noqa: F811
    """Otro proceso (otra instancia, el Builder) publica partiendo de lo que hay en la BD, no de nuestra copia de trabajo."""
    snapshot, _version = repo.load()
    snapshot.knowledge.rules.append(BusinessRule(id=rule_id, text="Regla publicada por otro proceso", applies_to=[CLIENTES]))
    repo.publish(snapshot, published_by="otro", reason="curation")


def test_una_edicion_parte_siempre_del_catalogo_vigente(client, repo, settings):  # noqa: F811
    """Aunque la API aún no se haya enterado de lo que publicó otro proceso, editar no lo pisa."""
    runtime = client.app.state.runtime
    publish_rule_elsewhere(repo, settings, "BR-OTRO-PROCESO")
    runtime._db_checked = time.monotonic()  # la comprobación periódica todavía no toca
    assert describe(client, "Edición sobre la copia vigente").status_code == 200
    loaded, _ = repo.load()
    assert "BR-OTRO-PROCESO" in {r.id for r in loaded.knowledge.rules}
    assert description_of(client) == "Edición sobre la copia vigente"


def test_si_otro_proceso_publica_durante_la_edicion_da_409_y_no_aplica(client, repo, settings, db_connect, monkeypatch):  # noqa: F811
    runtime = client.app.state.runtime
    real, raced = runtime.repository.publish, []

    def racing(snapshot, **kwargs):  # otro proceso publica justo entre la edición y su publicación
        if not raced:
            raced.append(True)
            publish_rule_elsewhere(repo, settings, "BR-CARRERA")
        return real(snapshot, **kwargs)

    monkeypatch.setattr(runtime.repository, "publish", racing)
    r = describe(client, "Edición que pierde la carrera")
    assert r.status_code == 409 and "vuelve a intentarlo" in r.json()["detail"]
    assert description_of(client) != "Edición que pierde la carrera"
    conn = db_connect()
    conflicts = conn.cursor().execute("SELECT COUNT(*) FROM audit.audit_event WHERE kind = 'catalog_conflict'").fetchone()[0]
    conn.close()
    assert conflicts >= 1  # la auditoría dice que el cambio anunciado no se aplicó
    # El reintento entra, y no se pierde lo que publicó el otro proceso.
    assert describe(client, "Edición repetida").status_code == 200
    loaded, _ = repo.load()
    assert "BR-CARRERA" in {r.id for r in loaded.knowledge.rules} and description_of(client) == "Edición repetida"


def test_un_diccionario_rechazado_se_puede_volver_a_aplicar(client, repo, settings, monkeypatch):  # noqa: F811
    runtime = client.app.state.runtime
    csv = "asset_key,description\nBancaPrestamos.dbo.Clientes.DUI,Documento único de identidad del cliente\n"
    real, raced = runtime.repository.publish, []

    def racing(snapshot, **kwargs):
        if not raced:
            raced.append(True)
            publish_rule_elsewhere(repo, settings, "BR-CARRERA-DICCIONARIO")
        return real(snapshot, **kwargs)

    monkeypatch.setattr(runtime.repository, "publish", racing)
    assert client.post("/curation/dictionary", json={"csv": csv}).status_code == 409
    again = client.post("/curation/dictionary", json={"csv": csv})
    assert again.status_code == 200 and again.json()["applied"] == 1 and again.json()["unchanged"] is False
    assert client.post("/curation/dictionary", json={"csv": csv}).json()["unchanged"] is True  # ya aplicado: no hace nada


def test_si_la_publicacion_falla_la_edicion_no_queda_para_que_la_publique_otro(client, repo, monkeypatch):
    """La BD cae al publicar: quien editaba recibe un error y su cambio se descarta de la copia de trabajo."""
    runtime = client.app.state.runtime
    real = runtime.repository.publish

    def broken(snapshot, **kwargs):
        raise ConnectionError("BD ConverData inaccesible")

    monkeypatch.setattr(runtime.repository, "publish", broken)
    quiet = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    assert describe(quiet, "Edición huérfana").status_code == 500
    monkeypatch.setattr(runtime.repository, "publish", real)
    assert description_of(client) != "Edición huérfana"
    rule = {"id": "BR-DESPUES", "text": "Otra edición, de otra persona", "applies_to": [CLIENTES]}
    assert client.put("/curation/rules", json=rule).status_code == 200
    loaded, _ = repo.load()
    assert "Edición huérfana" not in {o.description for o in loaded.objects}
    assert "BR-DESPUES" in {r.id for r in loaded.knowledge.rules}


def test_dos_ediciones_a_la_vez_quedan_las_dos_y_cada_una_a_su_nombre(client, repo, settings):  # noqa: F811
    """RF-34: la edición y su publicación son atómicas, así nadie publica el cambio a medias de otro."""
    import threading

    other = TestClient(client.app)
    login(other, user="demo")
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
    assert repo.description_history(CLIENTES)[-1]["description"] == "Clientes, por la primera sesión"
    assert repo.description_history("BancaPrestamos.dbo.Prestamos")[-1]["description"] == "Préstamos, por la segunda"


def test_el_build_corre_fuera_de_la_copia_de_trabajo_y_no_deja_restos(client, settings):  # noqa: F811
    assert build(client)["status"] == "ok"
    assert not list(settings.data_root.parent.glob(".build-*"))
    assert description_of(client) is None or isinstance(description_of(client), str)


def test_una_pregunta_con_datos_personales_no_se_guarda_como_confirmacion(client, repo, db_connect):
    """La confirmación guarda el texto de la pregunta: el voto cuenta y se audita, pero no pasa a `knowledge` (F17)."""
    env = client.post("/discover", json={"question": "¿Dónde está el DUI del cliente 01234567-8?"}).json()
    top = env["discovery"]["candidates"][0]["asset_key"]
    r = client.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": top, "verdict": "confirm"})
    assert r.status_code == 200 and r.json()["learned"] is False
    client.app.state.runtime.drain()
    assert repo.load()[0].knowledge.golden == []
    conn = db_connect()
    votes = conn.cursor().execute("SELECT COUNT(*) FROM audit.audit_discovery_feedback WHERE trace_id = ?",
                                  env["trace_id"]).fetchone()[0]
    conn.close()
    assert votes == 1


def test_una_regla_curada_y_una_confirmacion_llegan_a_la_bd(client, repo):
    rule = {"id": "BR-PRUEBA-API", "text": "Solo clientes con préstamo activo", "applies_to": [CLIENTES]}
    assert client.put("/curation/rules", json=rule).status_code == 200
    env = client.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"}).json()
    top = env["discovery"]["candidates"][0]["asset_key"]
    r = client.post("/discover/feedback", json={"trace_id": env["trace_id"], "asset_key": top, "verdict": "confirm"})
    assert r.status_code == 200, r.text
    for _ in range(100):  # la confirmación se publica en segundo plano
        loaded, _version = repo.load()
        if loaded.knowledge.golden:
            break
        time.sleep(0.05)
    assert "BR-PRUEBA-API" in {r.id for r in loaded.knowledge.rules}
    assert [g.asset_keys for g in loaded.knowledge.golden] == [[top]]
    assert client.delete("/curation/rules/BR-PRUEBA-API").status_code == 200
    assert "BR-PRUEBA-API" not in {r.id for r in repo.load()[0].knowledge.rules}
