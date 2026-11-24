"""Caso de uso `refresh_catalog` (el mismo para la tarea programada y para la API) y la CLI sobre la BD `DiscoveryDataAgent`.

Las pruebas marcadas `sqlserver` necesitan `DISCOVERY_DATA_AGENT_TEST_DB` (ver `conftest.py` de la raíz).
"""

import pytest

from discovery_data_agent import cli
from discovery_data_agent.application.catalog_refresh import refresh_catalog
from discovery_data_agent.catalog.store import CatalogSnapshot, KnowledgeBase, PublishResult, load_snapshot
from discovery_data_agent.config import Inventory, OwnersDirectory, ServerConfig
from discovery_data_agent.curation import DescriptionEdit
from discovery_data_agent.storage.catalog_repository import SqlServerCatalogRepository
from conftest import FIXTURE
from test_catalog_build import FakeSource, _inventory

CLIENTES = "BancaPrestamos.dbo.Clientes"


class MemoryRepository:
    """Almacén en memoria con el contrato de `CatalogRepository` que usa el caso de uso."""

    def __init__(self, snapshot: CatalogSnapshot | None = None):
        self.snapshot, self.loads, self.published = snapshot, [], []

    def load(self, scope="all"):
        self.loads.append(scope)
        return (self.snapshot, 7) if self.snapshot else None

    def publish(self, snapshot, *, published_by, reason, scope="all", expected_version=None):
        self.published.append((published_by, reason, scope))
        self.snapshot = snapshot
        return PublishResult(version=8, changed=True)


def test_sin_almacen_el_directorio_es_el_catalogo(tmp_path):
    result = refresh_catalog(_inventory(), tmp_path, source_factory=FakeSource)
    assert result.report.servers_ok == ["LOCAL"] and result.published is None and result.version is None
    assert load_snapshot(tmp_path).catalog().exists(CLIENTES)


def test_parte_de_lo_publicado_y_publica_solo_lo_que_deriva_de_los_metadatos(tmp_path):
    first = MemoryRepository()
    refresh_catalog(_inventory(), tmp_path / "a", source_factory=FakeSource, repository=first, published_by="builder")
    assert first.loads == ["build"] and first.published == [("builder", "build", "build")]
    # Segundo refresco en otro directorio vacío: arranca con el catálogo vigente y no vuelve a enriquecer lo igual.
    curated = first.snapshot
    next(o for o in curated.objects if o.asset_key == CLIENTES).description = "Clientes, según el responsable"
    next(o for o in curated.objects if o.asset_key == CLIENTES).description_source = "human"
    repo = MemoryRepository(curated)
    result = refresh_catalog(_inventory(), tmp_path / "b", source_factory=FakeSource, repository=repo,
                             published_by="ana", after_build=lambda root: (root / "marca").write_text("x"))
    assert result.previous_version == 7 and result.version == 8 and result.report.reused == result.report.objects
    assert (tmp_path / "b" / "marca").is_file()  # el paso extra corre antes de publicar
    published = next(o for o in repo.snapshot.objects if o.asset_key == CLIENTES)
    assert (published.description, published.description_source) == ("Clientes, según el responsable", "human")


def test_si_ningun_servidor_responde_no_se_publica_nada(tmp_path):
    inventory = _inventory()
    inventory.servers = [s for s in inventory.servers if s.id == "CAIDO"]
    repo = MemoryRepository()
    result = refresh_catalog(inventory, tmp_path, source_factory=FakeSource, repository=repo,
                             after_build=lambda root: pytest.fail("no debe correr"))
    assert not result.report.servers_ok and result.published is None and repo.published == []


def test_la_bd_de_trabajo_no_se_cataloga_a_si_misma(tmp_path):
    class WithOwnDatabase(FakeSource):
        def list_databases(self):
            return [*super().list_databases(), "DiscoveryDataAgent", "MiDiscoveryDataAgent"]

    result = refresh_catalog(_inventory(), tmp_path, source_factory=WithOwnDatabase, own_databases={"MiDiscoveryDataAgent"})
    assert {"DiscoveryDataAgent", "MiDiscoveryDataAgent"}.isdisjoint(result.report.databases)


# --- la CLI sobre la BD real ---------------------------------------------------------------------------
@pytest.fixture
def db_cli(discovery_data_agent_db, db_connect, monkeypatch, capsys):
    """`discovery-data-agent <args>` contra la BD desechable, que arranca sin catálogo ni inventario."""
    monkeypatch.setenv("DISCOVERY_DATA_AGENT_DB", discovery_data_agent_db)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    SqlServerCatalogRepository(db_connect).publish(
        CatalogSnapshot(Inventory(servers=[]), [], KnowledgeBase(), OwnersDirectory()),
        published_by="prueba", reason="import")
    SqlServerCatalogRepository(db_connect).save_inventory([], by="prueba")

    def run(*args):
        code = cli.main(list(args))
        return code, capsys.readouterr().out

    return run


def _events(db_connect, kind):
    conn = db_connect()
    try:
        return conn.cursor().execute("SELECT COUNT(*) FROM audit.audit_event WHERE kind = ?", kind).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.sqlserver
def test_cli_migraciones_publicar_exportar_y_descubrir(db_cli, db_connect, tmp_path):
    code, out = db_cli("db", "migrate", "--status")
    assert code == 0 and "ninguna" in out  # la BD de pruebas ya está al día
    code, out = db_cli("catalog", "publish", "--root", str(FIXTURE))
    assert code == 1 and "--force" in out  # ya hay un catálogo (vacío): reemplazarlo exige decirlo
    started = _events(db_connect, "catalog_publish_started")
    code, out = db_cli("catalog", "publish", "--root", str(FIXTURE), "--force", "--by", "instalador")
    assert code == 0 and "Versión" in out and _events(db_connect, "catalog_publish_started") == started + 1
    code, out = db_cli("catalog", "export", "--out", str(tmp_path / "export"))
    assert code == 0 and "sin las confirmaciones" in out
    exported = load_snapshot(tmp_path / "export")
    assert len(exported.objects) == len(load_snapshot(FIXTURE).objects) and exported.knowledge.golden == []
    code, out = db_cli("discover", "¿Dónde está el identificador del cliente en onboarding digital?", "--db")
    assert code == 0 and "Posibles coincidencias" in out
    code, out = db_cli("audit", "verify", "--db")
    assert "registros" in out  # la cuenta de las pruebas es dueña de la BD: informa, y el veredicto depende del rol


@pytest.mark.sqlserver
def test_cli_build_usa_el_inventario_de_la_bd_y_no_pisa_lo_curado(db_cli, db_connect, tmp_path, monkeypatch):
    monkeypatch.setattr("discovery_data_agent.metadata.sqlserver.SqlServerMetadata", FakeSource)
    repo = SqlServerCatalogRepository(db_connect)
    code, out = db_cli("catalog", "build", "--db")
    assert code == 1 and "no tiene inventario" in out
    repo.save_inventory([s.model_copy(update={"auth": "sql"}) for s in _inventory().servers], by="admin")
    finished = _events(db_connect, "catalog_build_finished")
    code, out = db_cli("catalog", "build", "--db")
    assert code == 0 and "BD DiscoveryDataAgent: versión" in out and "fallidos" in out  # un servidor caído no detiene el resto
    assert _events(db_connect, "catalog_build_finished") == finished + 1
    loaded, version = repo.load()
    target = next(o for o in loaded.objects if o.asset_key == CLIENTES)
    repo.write_descriptions([DescriptionEdit(target.id, None, "Clientes con préstamo", "human", True)],
                            by="responsable", reason="curation")
    code, out = db_cli("catalog", "build", "--db", "--out", str(tmp_path / "work"))
    assert code == 0 and "(sin cambios)" in out  # nada cambió en los servidores
    assert next(o for o in repo.load()[0].objects if o.id == target.id).description == "Clientes con préstamo"
    assert repo.version() == version + 1  # solo la edición del responsable subió la versión
    # El directorio de trabajo del Builder no recibe lo curado: ni confirmaciones ni reglas.
    assert not list((tmp_path / "work" / "knowledge" / "golden").glob("*.yaml"))
    repo.save_inventory([], by="prueba")


def test_el_builder_solo_va_a_los_hosts_permitidos(monkeypatch):
    """El inventario de la BD lo edita un administrador desde la web; la cuenta del servicio no entra a cualquier host."""
    servers = [ServerConfig(id="S1", host="sql01.banco.local,1433", alias="a", environment="produccion"),
               ServerConfig(id="S2", host=r"SQL02\\INST", alias="b", environment="qa"),
               ServerConfig(id="S3", host="atacante.example.com", alias="c", environment="desarrollo")]
    monkeypatch.delenv("DISCOVERY_DATA_AGENT_BUILDER_HOSTS", raising=False)
    monkeypatch.setenv("DISCOVERY_DATA_AGENT_ENV", "dev")
    assert cli.builder_hosts_refused(servers) is None  # en desarrollo la lista es opcional
    monkeypatch.setenv("DISCOVERY_DATA_AGENT_ENV", "prod")
    assert "DISCOVERY_DATA_AGENT_BUILDER_HOSTS" in cli.builder_hosts_refused(servers)  # en qa y prod es obligatoria
    monkeypatch.setenv("DISCOVERY_DATA_AGENT_BUILDER_HOSTS", ".banco.local, sql02")
    refused = cli.builder_hosts_refused(servers)
    assert "S3" in refused and "S1" not in refused and "S2" not in refused and "atacante" not in refused
    assert cli.builder_hosts_refused(servers[:2]) is None
