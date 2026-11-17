"""HU-06 y HU-09 · El catálogo en la BD `ConverData`: publicar con historial, cargar, exportar y responder igual que con YAML.

Las pruebas de este archivo necesitan un SQL Server real (`CONVERDATA_TEST_DB`, ver `conftest.py` de la raíz).
"""

import time
from pathlib import Path

import pytest

from converdata.bootstrap import build_service, build_service_from_db
from converdata.builder.catalog_builder import write_snapshot
from converdata.catalog.store import CatalogSnapshot, StaleCatalog, load_snapshot
from converdata.evaluation.discovery_eval import evaluate, load_cases
from converdata.models.knowledge import BusinessRule, GoldenDiscovery
from converdata.audit.sqlserver import SqlServerAuditSink
from converdata.storage.catalog_repository import SqlServerCatalogRepository
from conftest import FIXTURE

pytestmark = pytest.mark.sqlserver
BANCOS = FIXTURE.parent / "bancos"
USERS = "VBank_ING.dbo.Users"


@pytest.fixture
def repo(db_connect):
    return SqlServerCatalogRepository(db_connect)


@pytest.fixture
def vbank(repo) -> CatalogSnapshot:
    """El fixture VBank recién publicado (la BD queda igual a él, pase lo que pase en otras pruebas)."""
    snapshot = load_snapshot(FIXTURE)
    repo.publish(snapshot, published_by="prueba", reason="import")
    return snapshot


def _by_id(objects):
    return {o.id: o for o in objects}


def _same(a: CatalogSnapshot, b: CatalogSnapshot) -> None:
    assert _by_id(a.objects) == _by_id(b.objects)
    assert {s.id: s for s in a.inventory.servers} == {s.id: s for s in b.inventory.servers}
    ka, kb = a.knowledge, b.knowledge
    assert {r.id: r for r in ka.rules} == {r.id: r for r in kb.rules}
    assert {i.id: i for i in ka.items} == {i.id: i for i in kb.items}
    assert {g.id: g for g in ka.golden} == {g.id: g for g in kb.golden}
    assert {e.name: e for e in ka.entities} == {e.name: e for e in kb.entities}
    assert ka.lineage == kb.lineage
    assert {d.domain: d for d in a.owners.domains} == {d.domain: d for d in b.owners.domains}


def test_lo_publicado_se_carga_identico_y_repetirlo_no_cambia_nada(repo, vbank):
    loaded, version = repo.load()
    _same(loaded, vbank)
    assert version == repo.version()
    again = repo.publish(vbank, published_by="prueba", reason="import")
    assert again.changed is False and again.counts == {} and again.version == version


@pytest.mark.parametrize("root", [FIXTURE, BANCOS], ids=["vbank", "bancos"])
def test_el_descubrimiento_responde_igual_desde_la_bd_que_desde_yaml(repo, db_connect, root):
    """HU-09: mismas métricas y mismos candidatos, caso por caso, con el set de evaluación del catálogo."""
    repo.publish(load_snapshot(root), published_by="prueba", reason="import")
    cases = load_cases(root / "eval" / "discovery.yaml")
    from_yaml = evaluate(build_service(root), cases)
    from_db = evaluate(build_service_from_db(db_connect, settings_path=root / "config" / "settings.yaml"), cases)
    ignore = {"p50_ms", "p95_ms"}
    measured = lambda report: {k: v for k, v in report.metrics.items() if k not in ignore}  # noqa: E731
    answers = lambda report: [(r.case.id, r.ranked, r.top_confidence) for r in report.results]  # noqa: E731
    assert measured(from_db) == measured(from_yaml)
    assert from_db.by_type() == from_yaml.by_type()
    assert answers(from_db) == answers(from_yaml)
    assert from_db.metrics["leaks"] == 0 and from_db.metrics["invented"] == 0


def test_una_edicion_humana_queda_en_el_historial_con_su_autor(repo, vbank):
    """HU-06 CA2 y RF-34: se ve la versión anterior y quién la cambió."""
    before = next(o for o in vbank.objects if o.asset_key == USERS).description
    edited = load_snapshot(FIXTURE)
    for obj in edited.objects:
        if obj.asset_key == USERS:
            obj.description, obj.description_source, obj.reviewed = "Usuarios de la banca digital (prueba)", "human", True
    time.sleep(0.05)  # el historial descarta versiones de duración cero
    result = repo.publish(edited, published_by="steward_canales", reason="curation", expected_version=repo.version())
    assert result.changed and set(result.counts) == {"object.updated"}
    history = [h for h in repo.description_history(USERS) if h["physical_id"].startswith("produccion:")]
    assert [(h["description"], h["modified_by"]) for h in history][-2:] == [
        (before, "prueba"), ("Usuarios de la banca digital (prueba)", "steward_canales")]


def test_un_refresco_del_builder_no_pisa_lo_humano_ni_toca_lo_curado(repo, vbank):
    """HU-06 CA3 y F24 CA3: aunque el Builder parta de una copia anterior a la edición."""
    edited = load_snapshot(FIXTURE)
    target = next(o for o in edited.objects if o.asset_key == USERS and o.environment == "produccion")
    column = target.columns[0]
    target.description, target.description_source, target.reviewed = "Descripción del responsable", "human", True
    column.description, column.description_source, column.synonyms = "Columna descrita por el responsable", "human", ["alias humano"]
    edited.knowledge.rules.append(BusinessRule(id="BR-PRUEBA-1", text="Regla curada", applies_to=[USERS]))
    edited.knowledge.golden.append(GoldenDiscovery(id="u-prueba", template="usuarios digitales", asset_keys=[USERS],
                                                   confirmed_by="steward"))
    repo.publish(edited, published_by="steward_canales", reason="curation")

    stale = load_snapshot(FIXTURE)  # la copia del Builder: sin la edición, sin la regla, sin la confirmación
    for obj in stale.objects:
        if obj.id == target.id:
            obj.description, obj.description_source, obj.reviewed = "Texto generado", "generated", False
            obj.columns[0].description, obj.columns[0].description_source = "Texto generado", "generated"
            obj.row_count = 123456  # un cambio legítimo del refresco sí debe entrar
    repo.publish(stale, published_by="builder", reason="build", scope="build")

    loaded, _ = repo.load()
    now = next(o for o in loaded.objects if o.id == target.id)
    assert (now.description, now.description_source, now.reviewed) == ("Descripción del responsable", "human", True)
    assert (now.columns[0].description, now.columns[0].synonyms) == ("Columna descrita por el responsable", ["alias humano"])
    assert now.row_count == 123456
    assert "BR-PRUEBA-1" in {r.id for r in loaded.knowledge.rules}
    assert "u-prueba" in {g.id for g in loaded.knowledge.golden}


def test_un_objeto_eliminado_sale_del_catalogo_y_queda_en_el_historial(repo, db_connect, vbank):
    reduced = load_snapshot(FIXTURE)
    gone = next(o for o in reduced.objects if o.asset_key == USERS and o.environment == "qa")
    reduced.objects = [o for o in reduced.objects if o.id != gone.id]
    result = repo.publish(reduced, published_by="builder", reason="build", scope="build")
    assert result.counts["object.deleted"] == 1 and result.counts["column.deleted"] == len(gone.columns)
    loaded, _ = repo.load()
    assert gone.id not in _by_id(loaded.objects)
    conn = db_connect()
    kept = conn.cursor().execute("SELECT COUNT(*) FROM catalog.object_history WHERE physical_id = ?", gone.id).fetchone()[0]
    conn.close()
    assert kept >= 1


def test_no_se_publica_sobre_una_version_que_ya_no_es_la_vigente(repo, vbank):
    current = repo.version()
    edited = load_snapshot(FIXTURE)
    edited.objects[0].description = "Edición sobre una copia vieja"
    with pytest.raises(StaleCatalog):
        repo.publish(edited, published_by="steward", reason="curation", expected_version=current - 1)
    loaded, version = repo.load()
    assert version == current and "Edición sobre una copia vieja" not in {o.description for o in loaded.objects}


def test_exportar_e_importar_da_el_mismo_catalogo(repo, vbank, tmp_path):
    """HU-08: el directorio exportado se vuelve a leer sin diferencias, y es el área de trabajo del Builder."""
    loaded, _ = repo.load()
    write_snapshot(tmp_path / "export", loaded)
    _same(load_snapshot(tmp_path / "export"), loaded)
    (tmp_path / "export" / "knowledge" / "rules" / "vieja.yaml").write_text("[]", encoding="utf-8")
    write_snapshot(tmp_path / "export", loaded)  # lo que había se reemplaza
    assert not (tmp_path / "export" / "knowledge" / "rules" / "vieja.yaml").exists()


def test_el_catalogo_de_la_bd_no_contiene_valores_de_datos(repo, db_connect, vbank):
    """OP-02 CA5 y OP-06 CA2: ninguna tabla de `catalog` ni `knowledge` tiene columnas para valores."""
    conn = db_connect()
    names = {r[0].lower() for r in conn.cursor().execute(
        "SELECT c.name FROM sys.columns c JOIN sys.tables t ON t.object_id = c.object_id "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id WHERE s.name IN ('catalog', 'knowledge')").fetchall()}
    conn.close()
    assert not names & {"sample_values", "samples", "values", "sample_rows", "value"}
    with pytest.raises(ValueError, match="valores de datos"):
        type(vbank.objects[0]).model_validate({**vbank.objects[0].model_dump(by_alias=True), "sample_values": ["x"]})


# --- con las cuentas de verdad: cada rol hace lo suyo y nada más ---------------------------------------
def acting_as(db_connect, role: str):
    """`connect()` cuyas conexiones actúan como un usuario que solo pertenece a `role` (como la gMSA del proceso)."""
    user = f"cuenta_{role}"
    admin = db_connect()
    admin.autocommit = True
    admin.execute(f"IF USER_ID('{user}') IS NULL CREATE USER [{user}] WITHOUT LOGIN")
    admin.execute(f"ALTER ROLE [{role}] ADD MEMBER [{user}]")
    admin.close()

    def connect():
        conn = db_connect()
        conn.autocommit = True
        conn.execute(f"EXECUTE AS USER = '{user}'")
        return conn

    return connect


def test_la_cuenta_de_la_api_publica_carga_audita_y_pasa_verify(db_connect, vbank):
    """Con el rol `converdata_app` (no como dueño de la BD): todo lo que hace la API funciona, y `verify` aprueba."""
    connect = acting_as(db_connect, "converdata_app")
    repo, sink = SqlServerCatalogRepository(connect), SqlServerAuditSink(connect)
    edited = load_snapshot(FIXTURE)
    edited.objects[0].description = "Edición con la cuenta de la API"
    assert repo.publish(edited, published_by="steward", reason="curation", expected_version=repo.version()).changed
    assert "Edición con la cuenta de la API" in {o.description for o in repo.load()[0].objects}
    golden = GoldenDiscovery(id="u-cuenta-app", template="usuarios digitales", asset_keys=[USERS], confirmed_by="users")
    assert repo.upsert_golden(golden, published_by="analista") == repo.version()
    sink.event("login", "cuenta_app_prueba", servers=["S1"])
    assert sink.recent(5, user_id="cuenta_app_prueba")[0]["type"] == "login"
    report = sink.verify()
    assert report.ok, report.files[0].errors  # no puede modificar, borrar ni purgar la auditoría, ni alterar el historial


def test_la_cuenta_del_builder_refresca_sin_leer_ni_tocar_lo_curado(db_connect, repo, vbank):
    curated = load_snapshot(FIXTURE)
    curated.knowledge.golden.append(GoldenDiscovery(id="u-builder", template="pregunta de un usuario",
                                                    asset_keys=[USERS], confirmed_by="users"))
    repo.publish(curated, published_by="prueba", reason="import")
    rules_before = {r.id for r in repo.load()[0].knowledge.rules}

    connect = acting_as(db_connect, "converdata_builder")
    builder = SqlServerCatalogRepository(connect)
    working, _version = builder.load("build")
    assert working.objects and working.knowledge.entities and working.knowledge.lineage
    assert not working.knowledge.golden and not working.knowledge.rules and not working.knowledge.items
    working.objects[0].row_count = 424242
    assert builder.publish(working, published_by="builder", reason="build", scope="build").changed
    SqlServerAuditSink(connect).event("catalog_build_finished", "builder", status="ok")

    with pytest.raises(Exception, match="(?i)permission|permiso"):
        builder.load("all")  # las confirmaciones llevan el texto de las preguntas
    with pytest.raises(Exception, match="(?i)permission|permiso"):
        builder.publish(working, published_by="builder", reason="build", scope="all")
    with pytest.raises(Exception, match="(?i)permission|permiso"):
        SqlServerAuditSink(connect).recent(5)

    after, _ = repo.load()
    assert {r.id for r in after.knowledge.rules} == rules_before and "u-builder" in {g.id for g in after.knowledge.golden}
    assert 424242 in {o.row_count for o in after.objects}


def test_un_voto_escribe_una_sola_fila_y_sube_la_version(repo, vbank):
    before = repo.version()
    golden = GoldenDiscovery(id="u-voto", template="codigo de cliente digital", asset_keys=[USERS], confirmed_by="users")
    assert repo.upsert_golden(golden, published_by="analista") == before + 1
    assert repo.upsert_golden(golden.model_copy(update={"confirmations": 2}), published_by="otra") == before + 2
    [stored] = [g for g in repo.load()[0].knowledge.golden if g.id == "u-voto"]
    assert stored.confirmations == 2
    _same(CatalogSnapshot(vbank.inventory, vbank.objects, vbank.knowledge, vbank.owners),
          CatalogSnapshot(vbank.inventory, repo.load()[0].objects, vbank.knowledge, vbank.owners))  # el catálogo no cambió


def test_la_exportacion_para_git_no_lleva_preguntas(repo, vbank, tmp_path):
    loaded, _ = repo.load()
    assert loaded.knowledge.golden
    write_snapshot(tmp_path / "git", loaded, include_questions=False)
    assert not list((tmp_path / "git" / "knowledge" / "golden").glob("*.yaml"))
    assert load_snapshot(tmp_path / "git").knowledge.rules
