"""HU-04 y HU-05 · Migraciones de la BD `DiscoveryDataAgent`: ejecutor (sin servidor) y DDL contra un SQL Server real."""

import re
import time
from pathlib import Path

import pytest

from discovery_data_agent.storage.connection import connection_string, connector, describe, names_database
from discovery_data_agent.storage.migrations import Migration, MigrationError, discover, migrate, pending
from fakes import FakeDb

REPO = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO / "db" / "discovery_data_agent"


# --- ejecutor, sin servidor -------------------------------------------------------------------------
def _write(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_parte_por_lotes_go_y_el_hash_no_depende_del_fin_de_linea(tmp_path):
    unix = _write(tmp_path, "001_a.sql", "CREATE SCHEMA x;\nGO\nCREATE TABLE x.t (id int);\ngo\n")
    assert Migration(1, "a", unix).batches() == ["CREATE SCHEMA x;", "CREATE TABLE x.t (id int);"]
    windows = tmp_path / "win.sql"
    windows.write_bytes(unix.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert Migration(1, "a", windows).checksum == Migration(1, "a", unix).checksum


def test_rechaza_nombres_invalidos_y_huecos_en_la_numeracion(tmp_path):
    _write(tmp_path, "001_a.sql", "SELECT 1")
    _write(tmp_path, "003_c.sql", "SELECT 1")
    with pytest.raises(MigrationError, match="sin huecos"):
        discover(tmp_path)
    (tmp_path / "003_c.sql").unlink()
    _write(tmp_path, "cambios.sql", "SELECT 1")
    with pytest.raises(MigrationError, match="inválido"):
        discover(tmp_path)


def test_aplica_cada_script_en_una_transaccion_y_lo_registra(tmp_path):
    _write(tmp_path, "001_a.sql", "CREATE SCHEMA x;\nGO\nCREATE TABLE x.t (id int);")
    db = FakeDb(results={r"SELECT OBJECT_ID": [(None,)]})
    done = migrate(db.connect, tmp_path)
    assert [m.version for m in done] == [1]
    [row] = db.inserts_into("dbo.schema_version")
    assert row[0] == 1 and row[1] == "a" and re.fullmatch(r"[0-9a-f]{64}", row[2])
    assert db.commits == 1 and db.rollbacks == 0


def test_si_un_lote_falla_no_queda_nada_aplicado(tmp_path):
    _write(tmp_path, "001_a.sql", "CREATE SCHEMA x;\nGO\nCREATE TABLE rota;")
    db = FakeDb(fail_on=r"TABLE rota", results={r"SELECT OBJECT_ID": [(None,)]})
    with pytest.raises(MigrationError, match="001_a.sql"):
        migrate(db.connect, tmp_path)
    assert db.commits == 0 and db.rollbacks == 1 and db.inserts_into("dbo.schema_version") == []


def test_un_script_ya_aplicado_no_se_puede_editar(tmp_path):
    path = _write(tmp_path, "001_a.sql", "SELECT 1")
    checksum = Migration(1, "a", path).checksum
    db = FakeDb(results={r"SELECT OBJECT_ID": [(1,)], r"FROM dbo\.schema_version": [(1, checksum)]})
    assert pending(db.connect, tmp_path) == []
    path.write_text("SELECT 2", encoding="utf-8")
    with pytest.raises(MigrationError, match="cambió después de aplicarse"):
        pending(db.connect, tmp_path)


def test_la_bd_no_puede_ir_por_delante_del_codigo(tmp_path):
    _write(tmp_path, "001_a.sql", "SELECT 1")
    checksum = Migration(1, "a", tmp_path / "001_a.sql").checksum
    db = FakeDb(results={r"SELECT OBJECT_ID": [(1,)], r"FROM dbo\.schema_version": [(1, checksum), (2, "f" * 64)]})
    with pytest.raises(MigrationError, match="no conoce"):
        pending(db.connect, tmp_path)


def test_la_cadena_de_conexion_se_describe_sin_secretos():
    assert connection_string("  ") is None
    text = describe("DRIVER={ODBC Driver 18 for SQL Server};SERVER=srv01;DATABASE=DiscoveryDataAgent;UID=app;PWD=S3creta")
    assert text == "srv01/DiscoveryDataAgent" and "S3creta" not in text and "app" not in text


def test_las_pruebas_no_aceptan_una_cadena_que_nombre_una_bd():
    """El `conftest.py` de la raíz aborta si `DISCOVERY_DATA_AGENT_TEST_DB` trae `DATABASE`: publicaría un catálogo vacío en ella."""
    assert names_database("SERVER=srv;DATABASE=DiscoveryDataAgent;Trusted_Connection=yes")
    assert names_database("Server=srv; Initial Catalog = DiscoveryDataAgent")
    assert not names_database("SERVER=localhost\\SQLEXPRESS;Trusted_Connection=yes;TrustServerCertificate=yes")


# --- el DDL del repo ---------------------------------------------------------------------------------
def test_el_ddl_no_usa_vectores_full_text_ni_tablas_de_grafo():
    """PRD §13, decisiones 9 y 10: tablas normales, SQL Server 2016+."""
    for migration in discover(MIGRATIONS):
        code = re.sub(r"/\*.*?\*/", "", migration.sql, flags=re.S)
        code = re.sub(r"--[^\n]*", "", code)
        for banned in (r"\bVECTOR\s*\(", r"\bFULLTEXT\b", r"\bAS\s+NODE\b", r"\bAS\s+EDGE\b", r"\bCONTAINSTABLE\b"):
            assert not re.search(banned, code, re.I), f"{migration.path.name} usa {banned}"


# --- contra SQL Server real --------------------------------------------------------------------------
pytestmark_sql = pytest.mark.sqlserver


def _scalar(connect, sql, *params):
    conn = connect()
    try:
        return conn.cursor().execute(sql, *params).fetchone()[0]
    finally:
        conn.close()


def _as_role(connect, role: str, sql: str):
    """Ejecuta `sql` como un usuario que solo pertenece a `role`; devuelve None o el texto del error."""
    conn = connect()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        user = f"prueba_{role}"
        cur.execute(f"IF USER_ID('{user}') IS NULL CREATE USER [{user}] WITHOUT LOGIN")
        cur.execute(f"ALTER ROLE [{role}] ADD MEMBER [{user}]")
        cur.execute(f"EXECUTE AS USER = '{user}'")
        try:
            cur.execute(sql)
            return None
        except Exception as exc:  # pyodbc.ProgrammingError con el mensaje de SQL Server
            return str(exc)
    finally:
        conn.rollback()  # nada de lo probado queda escrito
        conn.close()


@pytestmark_sql
def test_las_migraciones_se_aplican_y_la_segunda_vez_no_cambian_nada(db_connect):
    assert pending(db_connect, MIGRATIONS) == []
    assert migrate(db_connect, MIGRATIONS) == []
    assert _scalar(db_connect, "SELECT COUNT(*) FROM dbo.schema_version") == len(discover(MIGRATIONS))
    schemas = {"catalog", "knowledge", "golden", "curation", "audit"}
    conn = db_connect()
    found = {r[0] for r in conn.cursor().execute("SELECT name FROM sys.schemas").fetchall()}
    conn.close()
    assert schemas <= found


@pytestmark_sql
def test_el_historial_temporal_conserva_la_version_anterior(db_connect):
    conn = db_connect()
    conn.autocommit = True  # cada sentencia es su propia transacción: el historial usa la hora de inicio de cada una
    cur = conn.cursor()
    pid = "qa:SRV.Prueba.dbo.Historial"
    cur.execute("DELETE FROM catalog.object WHERE physical_id = ?", pid)
    cur.execute(
        """INSERT INTO catalog.object (physical_id, asset_key, environment, server_id, kind, database_name, schema_name,
               object_name, description, description_source, synonyms_json, primary_key_json, parameters_json,
               drift_json, modified_by)
           VALUES (?, 'Prueba.dbo.Historial', 'qa', 'SRV', 'table', 'Prueba', 'dbo', 'Historial', 'sugerida',
                   'generated', '[]', '[]', '[]', '[]', 'builder')""", pid)
    time.sleep(0.2)  # SQL Server descarta las versiones de duración cero
    cur.execute("UPDATE catalog.object SET description = 'revisada', description_source = 'human', reviewed = 1, "
                "modified_by = 'steward1' WHERE physical_id = ?", pid)
    rows = cur.execute(
        "SELECT description, modified_by FROM catalog.object FOR SYSTEM_TIME ALL WHERE physical_id = ? "
        "AND valid_from >= DATEADD(MINUTE, -1, SYSUTCDATETIME()) ORDER BY valid_from", pid).fetchall()
    cur.execute("DELETE FROM catalog.object WHERE physical_id = ?", pid)
    conn.close()
    assert [tuple(r) for r in rows] == [("sugerida", "builder"), ("revisada", "steward1")]


@pytestmark_sql
@pytest.mark.parametrize("sql", [
    "UPDATE audit.audit_event SET kind = 'x'",
    "DELETE FROM audit.audit_question",
    "DELETE FROM audit.audit_event",
    "TRUNCATE TABLE audit.audit_event",
    "EXEC audit.usp_purge @keep_days = 180",
])
def test_la_api_no_puede_modificar_ni_borrar_la_auditoria(db_connect, sql):
    error = _as_role(db_connect, "discovery_data_agent_app", sql)
    assert error is not None and re.search(r"permission|permiso", error, re.I), error


@pytestmark_sql
def test_la_api_si_puede_insertar_y_leer_la_auditoria(db_connect):
    assert _as_role(db_connect, "discovery_data_agent_app",
                    "INSERT INTO audit.audit_event (kind, user_id, data_json) VALUES ('prueba', 'u', '{}')") is None
    assert _as_role(db_connect, "discovery_data_agent_app", "SELECT TOP 1 * FROM audit.audit_event") is None


@pytestmark_sql
@pytest.mark.parametrize("sql", [
    "INSERT INTO audit.audit_event (kind, user_id, data_json) VALUES ('x', 'u', '{}')",
    "SELECT TOP 1 * FROM catalog.object",
    "DELETE FROM audit.audit_event",
])
def test_el_auditor_solo_lee_la_auditoria(db_connect, sql):
    assert _as_role(db_connect, "discovery_data_agent_auditor", sql) is not None
    assert _as_role(db_connect, "discovery_data_agent_auditor", "SELECT TOP 1 * FROM audit.audit_question") is None


@pytestmark_sql
@pytest.mark.parametrize("sql", [
    "SELECT TOP 1 question FROM audit.audit_question",
    "SELECT TOP 1 * FROM golden.golden_discovery_original",
    "SELECT TOP 1 template FROM knowledge.golden_discovery",  # la plantilla es el texto de la pregunta (D2)
    "DELETE FROM knowledge.golden_discovery",
    "DELETE FROM knowledge.business_rule",
    "UPDATE knowledge.item SET content = 'x'",
    "SELECT TOP 1 * FROM curation.owners",
    "DELETE FROM curation.owners",
    "DELETE FROM audit.audit_event",
    "DELETE FROM catalog.catalog_version",
    "UPDATE catalog.catalog_version SET published_by = 'x'",
    "ALTER TABLE catalog.object SET (SYSTEM_VERSIONING = OFF)",
])
def test_el_builder_solo_toca_lo_que_deriva_de_los_metadatos(db_connect, sql):
    """No lee preguntas ni confirmaciones, no borra lo curado ni la auditoría, y no puede reescribir el historial."""
    assert _as_role(db_connect, "discovery_data_agent_builder", sql) is not None
    assert _as_role(db_connect, "discovery_data_agent_builder", "SELECT TOP 1 * FROM catalog.object") is None
    assert _as_role(db_connect, "discovery_data_agent_builder", "DELETE FROM knowledge.lineage_edge") is None
    assert _as_role(db_connect, "discovery_data_agent_builder",
                    "INSERT INTO audit.audit_event (kind, user_id, data_json) VALUES ('catalog_build', 'b', '{}')") is None


@pytestmark_sql
@pytest.mark.parametrize("sql", [
    "ALTER TABLE catalog.object SET (SYSTEM_VERSIONING = OFF)",
    "ALTER TABLE knowledge.business_rule SET (SYSTEM_VERSIONING = OFF)",
    "DELETE FROM catalog.object_history",
    "DELETE FROM catalog.catalog_version",
    "UPDATE catalog.catalog_version SET version = 1",
])
def test_la_api_no_puede_reescribir_el_historial_ni_la_version(db_connect, sql):
    assert _as_role(db_connect, "discovery_data_agent_app", sql) is not None


@pytestmark_sql
def test_la_purga_exige_180_dias_y_solo_la_ejecuta_mantenimiento(db_connect):
    error = _as_role(db_connect, "discovery_data_agent_maintenance", "EXEC audit.usp_purge @keep_days = 30")
    assert error is not None and "180" in error
    assert _as_role(db_connect, "discovery_data_agent_maintenance", "EXEC audit.usp_purge @keep_days = 180") is None
    assert _as_role(db_connect, "discovery_data_agent_maintenance", "DELETE FROM audit.audit_event") is not None
    assert _as_role(db_connect, "discovery_data_agent_maintenance", "SELECT TOP 1 * FROM audit.audit_question") is not None


def test_la_version_que_exige_el_codigo_es_la_ultima_migracion():
    from discovery_data_agent.storage.migrations import REQUIRED_VERSION

    assert REQUIRED_VERSION == discover(MIGRATIONS)[-1].version


def test_la_api_no_arranca_con_migraciones_pendientes_y_lo_dice_claro():
    from discovery_data_agent.storage.migrations import REQUIRED_VERSION, require_current

    behind = FakeDb(results={r"SELECT OBJECT_ID": [(1,)], r"FROM dbo\.schema_version": [(1, "a" * 64)]})
    with pytest.raises(MigrationError, match="discovery-data-agent db migrate"):
        require_current(behind.connect)
    current = FakeDb(results={r"SELECT OBJECT_ID": [(1,)],
                              r"FROM dbo\.schema_version": [(v, "a" * 64) for v in range(1, REQUIRED_VERSION + 1)]})
    require_current(current.connect)  # al día: no lanza
