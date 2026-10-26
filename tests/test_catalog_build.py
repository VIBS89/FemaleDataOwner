"""Agente de esquemas (CatalogBuildFlow): de SQL Server sin catálogo previo al DiscoverFlow funcionando."""

import yaml

from converdata.bootstrap import build_service, user_with_databases
from converdata.config import Inventory, ServerConfig
from converdata.flows.catalog_build import build_catalog
from converdata.metadata.sqlserver import RawColumn, RawObject, format_type


def _clientes(db):
    return RawObject(db, "dbo", "Clientes", "table", columns=[
        RawColumn("ClienteID", "int", False), RawColumn("DUI", "char(10)", False),
        RawColumn("Nombres", "nvarchar(60)", False), RawColumn("Email", "nvarchar(120)", True),
    ], primary_key=["ClienteID"], row_count=1000)


class FakeSource:
    """Simula lo que `SqlServerMetadata` lee de sys.* (sin valores de datos)."""

    calls = 0

    def __init__(self, server):
        self.server = server
        if server.id == "CAIDO":
            raise ConnectionError("servidor no responde")

    def list_databases(self):
        return ["BancaPrestamos", "BancaTarjetasCredito"]

    def extract_database(self, db):
        FakeSource.calls += 1
        objs = [_clientes(db)]
        if db == "BancaPrestamos":
            objs.append(RawObject(db, "dbo", "Prestamos", "table", columns=[
                RawColumn("PrestamoID", "int", False), RawColumn("ClienteID", "int", False),
                RawColumn("TasaAnual", "decimal(5,2)", False), RawColumn("DiasMora", "int", False),
            ], primary_key=["PrestamoID"], foreign_keys=[{"name": "FK_P_C", "columns": ["ClienteID"], "ref_schema": "dbo",
                                                          "ref_table": "Clientes", "ref_columns": ["ClienteID"]}]))
            objs.append(RawObject(db, "dbo", "vw_Cartera", "view", columns=[RawColumn("DiasMora", "int", True)],
                                  dependencies=["BancaPrestamos.dbo.Prestamos"]))
        return objs


def _inventory():
    return Inventory(servers=[
        ServerConfig(id="LOCAL", host="localhost", alias="SQL local", environment="desarrollo", databases=["*"], is_reference=True),
        ServerConfig(id="CAIDO", host="x", alias="Caído", environment="qa", databases=["X"]),
    ])


def test_descubre_esquemas_sin_catalogo_previo(tmp_path):
    report = build_catalog(_inventory(), tmp_path, source_factory=FakeSource)
    assert report.servers_ok == ["LOCAL"] and "CAIDO" in report.servers_failed  # F1-CA5: sigue con los demás
    assert report.objects == 4
    assert report.entities == ["Cliente (2 BDs)"]
    assert report.lineage_edges == 1
    prestamos = yaml.safe_load((tmp_path / "catalog/desarrollo/LOCAL/BancaPrestamos/dbo.Prestamos.yaml").read_text(encoding="utf-8"))
    assert prestamos["foreign_keys"][0]["ref"] == "BancaPrestamos.dbo.Clientes"
    assert "sample_values" not in str(prestamos)
    clientes = yaml.safe_load((tmp_path / "catalog/desarrollo/LOCAL/BancaPrestamos/dbo.Clientes.yaml").read_text(encoding="utf-8"))
    pii = {c["name"]: c.get("pii", False) for c in clientes["columns"]}
    assert pii == {"ClienteID": False, "DUI": True, "Nombres": True, "Email": True}
    # El inventario escrito refleja las BDs descubiertas y no expone el host.
    inv = yaml.safe_load((tmp_path / "config/databases.yaml").read_text(encoding="utf-8"))
    assert inv["servers"][0]["databases"] == ["BancaPrestamos", "BancaTarjetasCredito"]
    assert "host" not in inv["servers"][0]


def test_el_catalogo_generado_alimenta_el_discoverflow(tmp_path):
    build_catalog(_inventory(), tmp_path, source_factory=FakeSource)
    service = build_service(tmp_path)
    user = user_with_databases(service, "dev", None)
    env = service.run("¿Dónde están los días de mora de los préstamos?", user)
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.Prestamos.DiasMora"
    relations = {(r.from_, r.to, r.relation) for r in env.discovery.related}
    assert ("BancaPrestamos.dbo.Prestamos", "BancaPrestamos.dbo.vw_Cartera", "etl") in relations


def test_refresco_no_reescribe_ni_pisa_ediciones_humanas(tmp_path):
    build_catalog(_inventory(), tmp_path, source_factory=FakeSource)
    path = tmp_path / "catalog/desarrollo/LOCAL/BancaPrestamos/dbo.Prestamos.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["description"], data["description_source"] = "Préstamos desembolsados.", "human"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    report = build_catalog(_inventory(), tmp_path, source_factory=FakeSource)
    assert report.reused == 4  # mismo schema_hash: no se re-extrae ni se re-enriquece
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["description_source"] == "human"
    # La edición manual se normaliza al formato del catálogo una vez; después, sin cambios no se reescribe (F1-CA2).
    assert build_catalog(_inventory(), tmp_path, source_factory=FakeSource).files_written == 0


def test_enriquecimiento_solo_columnas_existentes(tmp_path):
    from converdata.llm.nodes import ColumnEnrichment, EnrichmentBatch, TableEnrichment

    class FakeEnricher:
        def enrich(self, tables):
            return EnrichmentBatch(tables=[
                TableEnrichment(table=t["table"], description=f"Tabla {t['table']}", synonyms=["cartera"], columns=[
                    ColumnEnrichment(name="TasaAnual", description="Tasa de interés anual del préstamo.", synonyms=["tasa de interés"]),
                    ColumnEnrichment(name="Inventada", description="no existe"),
                ]) for t in tables
            ])

    report = build_catalog(_inventory(), tmp_path, source_factory=FakeSource, enricher=FakeEnricher())
    assert report.enriched == 4  # Clientes ×2, Prestamos y vw_Cartera
    data = yaml.safe_load((tmp_path / "catalog/desarrollo/LOCAL/BancaPrestamos/dbo.Prestamos.yaml").read_text(encoding="utf-8"))
    cols = {c["name"]: c for c in data["columns"]}
    assert cols["TasaAnual"]["description"] == "Tasa de interés anual del préstamo."
    assert "Inventada" not in cols
    assert cols["TasaAnual"].get("description_source", "generated") == "generated"  # sin revisar hasta curación


def test_formato_de_tipos():
    assert format_type("nvarchar", 120, 0, 0) == "nvarchar(60)"
    assert format_type("varchar", -1, 0, 0) == "varchar(max)"
    assert format_type("decimal", 9, 12, 2) == "decimal(12,2)"
