"""HU-06 y HU-09 · El catálogo en la BD `ConverData`: publicar con historial, cargar, exportar y responder igual que con YAML.

Las pruebas de este archivo necesitan un SQL Server real (`CONVERDATA_TEST_DB`, ver `conftest.py` de la raíz).
"""

import time
from pathlib import Path

import pytest

from converdata.bootstrap import build_service, build_service_from_db
from converdata.builder.catalog_builder import write_snapshot
from converdata.catalog.store import CatalogSnapshot, StaleCatalog, load_snapshot
from converdata.curation import DescriptionEdit
from converdata.evaluation.discovery_eval import evaluate, load_cases
from converdata.models.knowledge import BusinessRule, GoldenDiscovery
from converdata.audit.sqlserver import SqlServerAuditSink
from converdata.storage.catalog_repository import SqlServerCatalogRepository
from converdata.storage.curation_repository import SqlServerCurationRepository
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
    before = repo.version()
    repo.upsert_golden(golden, by="analista", question="¿Dónde están los usuarios digitales?")
    assert repo.version() == before + 1
    key = edited.objects[0].id
    assert repo.write_descriptions([DescriptionEdit(key, None, "Descripción escrita por fila", "human", True)],
                                   by="steward", reason="curation") == 1
    repo.upsert_rule(BusinessRule(id="BR-CUENTA-APP", text="Regla de la cuenta de la API", applies_to=[USERS],
                                  source="steward:steward"), by="steward")
    assert repo.delete_rule("BR-CUENTA-APP", by="steward")
    repo.save_inventory(edited.inventory.servers, by="admin")
    assert [s.id for s in repo.inventory()] == [s.id for s in edited.inventory.servers]
    curation = SqlServerCurationRepository(connect)
    curation.save_stewards([{"login": "resp", "domains": ["*"]}], by="admin")
    assert curation.add_vote({"golden_id": "u-cuenta-app", "user_id": "analista", "trace_id": "t-app",
                              "asset_key": USERS, "verdict": "confirm"}) == {"analista": "confirm"}
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
    # El inventario lo lee (para saber a qué servidores conectarse) pero no lo cambia; la curación no la ve.
    repo.save_inventory(curated.inventory.servers, by="admin")
    assert [s.id for s in builder.inventory()] == [s.id for s in curated.inventory.servers]
    with pytest.raises(Exception, match="(?i)permission|permiso"):
        builder.save_inventory([], by="builder")
    for forbidden in (lambda c: c.requests(), lambda c: c.stewards(),
                      lambda c: c.add_vote({"golden_id": "u-b", "user_id": "b", "trace_id": "t", "asset_key": USERS,
                                            "verdict": "confirm"})):
        with pytest.raises(Exception, match="(?i)permission|permiso"):
            forbidden(SqlServerCurationRepository(connect))
    with pytest.raises(Exception, match="(?i)permission|permiso"):
        builder.upsert_golden(GoldenDiscovery(id="u-x", template="x", asset_keys=[USERS], confirmed_by="users"), by="b")

    after, _ = repo.load()
    assert {r.id for r in after.knowledge.rules} == rules_before and "u-builder" in {g.id for g in after.knowledge.golden}
    assert 424242 in {o.row_count for o in after.objects}


def test_un_voto_escribe_una_sola_fila_y_sube_la_version(repo, vbank, db_connect):
    before = repo.version()
    golden = GoldenDiscovery(id="u-voto", template="codigo de cliente digital", asset_keys=[USERS], confirmed_by="users")
    repo.upsert_golden(golden, by="analista", question="¿Cuál es el código de cliente digital 123?")
    repo.upsert_golden(golden.model_copy(update={"confirmations": 2}), by="otra", question="otra forma de preguntarlo")
    assert repo.version() == before + 2
    [stored] = [g for g in repo.load()[0].knowledge.golden if g.id == "u-voto"]
    assert stored.confirmations == 2
    # El original va al esquema `golden`, una sola vez, y no vuelve con el catálogo (no entra al índice).
    originals = _rows(db_connect, "SELECT question FROM golden.golden_discovery_original WHERE golden_id = 'u-voto'")
    assert originals == [("¿Cuál es el código de cliente digital 123?",)]
    _same(CatalogSnapshot(vbank.inventory, vbank.objects, vbank.knowledge, vbank.owners),
          CatalogSnapshot(vbank.inventory, repo.load()[0].objects, vbank.knowledge, vbank.owners))  # el catálogo no cambió


def _rows(connect, sql, *params):
    conn = connect()
    try:
        return [tuple(r) for r in conn.cursor().execute(sql, *params).fetchall()]
    finally:
        conn.close()


def test_la_curacion_escribe_filas_concretas_con_autor_e_historial(repo, vbank):
    """C2: una edición no publica todo el catálogo; cambia su fila, sube la versión y deja la anterior en el historial."""
    obj = next(o for o in vbank.objects if o.asset_key == USERS)
    column = obj.columns[0].name
    before = repo.version()
    time.sleep(0.05)
    edits = [DescriptionEdit(obj.id, None, "Usuarios de banca digital", "human", True, ("clientes digitales",)),
             DescriptionEdit(obj.id, column, "Identificador del usuario", "human", True)]
    assert repo.write_descriptions(edits, by="responsable", reason="curation") == 2
    assert repo.version() == before + 1  # una sola versión por edición
    loaded = next(o for o in repo.load()[0].objects if o.id == obj.id)
    assert (loaded.description, loaded.description_source, loaded.reviewed) == ("Usuarios de banca digital", "human", True)
    assert loaded.synonyms == ["clientes digitales"]
    assert loaded.columns[0].description == "Identificador del usuario" and loaded.columns[0].synonyms == obj.columns[0].synonyms
    last = repo.description_history(USERS)[-1]
    assert (last["description"], last["modified_by"]) == ("Usuarios de banca digital", "responsable")
    # Un diccionario no pisa lo que escribió una persona, ni una copia que ya no existe cuenta como escrita.
    dictionary = [DescriptionEdit(obj.id, None, "Texto del diccionario", "data_dictionary", False, keep_human=True),
                  DescriptionEdit("produccion:NO.Existe.dbo.T", None, "x", "data_dictionary", False, keep_human=True)]
    assert repo.write_descriptions(dictionary, by="responsable", reason="dictionary") == 0
    assert repo.version() == before + 1  # nada cambió: la versión no sube


def test_el_historial_atribuye_la_descripcion_a_quien_la_escribio_no_a_quien_toco_la_fila(repo, vbank):
    """RF-34: un refresco del Builder que solo cambia el número de filas no aparece como autor de la descripción."""
    obj = next(o for o in vbank.objects if o.asset_key == USERS)
    time.sleep(0.05)
    repo.write_descriptions([DescriptionEdit(obj.id, None, "Texto de la responsable", "human", True)],
                            by="responsable", reason="curation")
    for rows in (111, 222):  # dos refrescos posteriores que no tocan la descripción
        time.sleep(0.05)
        working, _ = repo.load("build")
        next(o for o in working.objects if o.id == obj.id).row_count = rows
        assert repo.publish(working, published_by="builder", reason="build", scope="build").changed
    mine = [v for v in repo.description_history(USERS) if v["physical_id"] == obj.id]
    assert [v["description"] for v in mine][-2:] == [obj.description, "Texto de la responsable"]
    last = mine[-1]
    assert last["modified_by"] == "responsable" and last["valid_to"] is None  # vigente, y a su nombre
    assert "builder" not in {v["modified_by"] for v in mine}
    assert mine[-2]["valid_to"] == last["valid_from"]  # sin huecos entre una versión y la siguiente


def test_las_reglas_curadas_se_escriben_y_borran_por_fila(repo, vbank):
    rule = BusinessRule(id="BR-FILA", text="Solo usuarios activos", applies_to=[USERS], source="steward:ana", reviewed=True)
    before = repo.version()
    repo.upsert_rule(rule, by="ana")
    repo.upsert_rule(rule.model_copy(update={"text": "Solo usuarios activos y verificados"}), by="luis")
    stored = next(r for r in repo.load()[0].knowledge.rules if r.id == "BR-FILA")
    assert stored.text == "Solo usuarios activos y verificados" and stored.source == "steward:ana"
    assert repo.delete_rule("BR-FILA", by="luis") and not repo.delete_rule("BR-FILA", by="luis")
    assert repo.version() == before + 3
    assert {r.id for r in repo.load()[0].knowledge.rules} == {r.id for r in vbank.knowledge.rules}


def test_el_inventario_con_hosts_vive_aparte_del_catalogo(repo, vbank):
    """`catalog.inventory_server` es el inventario que usa la API para conectarse; lo escribe solo ella."""
    servers = [s.model_copy(update={"host": f"{s.id.lower()}.banco.local", "auth": "sql"}) for s in vbank.inventory.servers]
    repo.save_inventory(servers, by="admin")
    assert [(s.id, s.host) for s in repo.inventory()] == [(s.id, s.host) for s in servers]
    repo.save_inventory(servers[:1], by="otro_admin")  # reemplaza: los que sobran se quitan
    assert [s.id for s in repo.inventory()] == [servers[0].id]
    repo.save_inventory([], by="admin")


def test_el_inventario_conserva_figures_de_cada_servidor(repo, vbank):
    """`figures` (None / True / False) se guarda y se lee tal cual: de él depende el cálculo de cifras en producción."""
    valores = [None, True, False]
    servers = [s.model_copy(update={"figures": valores[i % 3]}) for i, s in enumerate(vbank.inventory.servers)]
    repo.save_inventory(servers, by="admin")
    assert [(s.id, s.figures) for s in repo.inventory()] == [(s.id, s.figures) for s in servers]
    repo.save_inventory([], by="admin")


def test_la_exportacion_para_git_no_lleva_preguntas(repo, vbank, tmp_path):
    loaded, _ = repo.load()
    assert loaded.knowledge.golden
    write_snapshot(tmp_path / "git", loaded, include_questions=False)
    assert not list((tmp_path / "git" / "knowledge" / "golden").glob("*.yaml"))
    assert load_snapshot(tmp_path / "git").knowledge.rules


def test_el_refresco_no_revierte_una_correccion_humana_hecha_durante_el_build(repo, vbank):
    """F24 CA3: el Builder cargó la descripción humana anterior; la persona la corrigió mientras corría; gana la persona."""
    obj = next(o for o in vbank.objects if o.asset_key == USERS)
    column = obj.columns[0].name
    repo.write_descriptions([DescriptionEdit(obj.id, None, "Versión 1 de la responsable", "human", True),
                             DescriptionEdit(obj.id, column, "Columna, versión 1", "human", True)],
                            by="responsable", reason="curation")
    working, _ = repo.load("build")  # el Builder arranca con la versión 1
    repo.write_descriptions([DescriptionEdit(obj.id, None, "Versión 2: retira un texto indebido", "human", True,
                                             ("usuarios",)),
                             DescriptionEdit(obj.id, column, "Columna, versión 2", "human", True)],
                            by="responsable", reason="curation")
    next(o for o in working.objects if o.id == obj.id).row_count = 31415
    assert repo.publish(working, published_by="builder", reason="build", scope="build").changed
    after = next(o for o in repo.load()[0].objects if o.id == obj.id)
    assert (after.description, after.synonyms, after.row_count) == ("Versión 2: retira un texto indebido", ["usuarios"], 31415)
    assert after.columns[0].description == "Columna, versión 2"
    assert repo.description_history(USERS)[-1]["modified_by"] == "responsable"


def test_la_purga_alcanza_las_dudas_y_los_originales_pero_no_los_votos(repo, vbank, db_connect):
    """OP-05: lo que guarda preguntas fuera de la auditoría se purga con ella; los votos no llevan texto libre."""
    curation = SqlServerCurationRepository(db_connect)
    old = {"id": "purga-vieja", "created_at": "2020-01-01T00:00:00+00:00", "status": "answered", "user_id": "ana",
           "trace_id": "t-purga-vieja", "question": "¿Dónde está el saldo?", "domain": "prestamos", "shown": [],
           "note": None, "answer": None}
    curation.add_requests([old, {**old, "id": "purga-nueva", "trace_id": "t-purga-nueva",
                                 "created_at": "2100-01-01T00:00:00+00:00"}])
    golden = GoldenDiscovery(id="u-purga", template="donde esta el saldo", asset_keys=[USERS], confirmed_by="users")
    repo.upsert_golden(golden, by="ana", question="¿Dónde está el saldo?")
    curation.add_vote({"golden_id": "u-purga", "user_id": "ana", "trace_id": "t", "asset_key": USERS, "verdict": "confirm"})
    conn = db_connect()
    conn.autocommit = True
    conn.execute("UPDATE golden.golden_discovery_original SET created_at = '2020-01-01' WHERE golden_id = 'u-purga'")
    row = conn.execute("EXEC audit.usp_purge @keep_days = 180").fetchone()
    conn.close()
    assert row.requests >= 1 and row.originals >= 1
    assert {r["id"] for r in curation.requests()} & {"purga-vieja", "purga-nueva"} == {"purga-nueva"}
    assert _rows(db_connect, "SELECT COUNT(*) FROM golden.golden_discovery_original WHERE golden_id = 'u-purga'") == [(0,)]
    assert _rows(db_connect, "SELECT COUNT(*) FROM curation.vote WHERE golden_id = 'u-purga'") == [(1,)]
    assert "u-purga" in {g.id for g in repo.load()[0].knowledge.golden}  # la plantilla anónima se conserva


def test_la_cuenta_de_la_api_no_puede_cambiar_ni_borrar_votos_ni_originales(db_connect, repo, vbank):
    connect = acting_as(db_connect, "converdata_app")
    SqlServerCurationRepository(connect).add_vote(
        {"golden_id": "u-fijo", "user_id": "ana", "trace_id": "t", "asset_key": USERS, "verdict": "confirm"})
    for sql in ("UPDATE curation.vote SET verdict = 'reject' WHERE golden_id = 'u-fijo'",
                "DELETE FROM curation.vote WHERE golden_id = 'u-fijo'",
                "DELETE FROM golden.golden_discovery_original",
                "ALTER TABLE curation.steward SET (SYSTEM_VERSIONING = OFF)"):
        conn = connect()
        with pytest.raises(Exception, match="(?i)permission|permiso"):
            conn.execute(sql)
        conn.close()
