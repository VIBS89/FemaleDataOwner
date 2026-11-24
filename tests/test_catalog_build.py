"""Agente de esquemas (CatalogBuildFlow): de SQL Server sin catálogo previo al DiscoverFlow funcionando."""

import pytest
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


def test_un_servidor_caido_no_vacia_su_parte_del_catalogo(tmp_path):
    """El refresco nocturno no puede dejar sin catálogo a los usuarios porque un servidor no respondió esa noche."""

    class Flaky(FakeSource):
        down = False

        def __init__(self, server):
            if Flaky.down and server.id == "LOCAL":
                raise ConnectionError("servidor no responde")
            super().__init__(server)

    first = build_catalog(_inventory(), tmp_path, source_factory=Flaky)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "catalog").rglob("*.yaml"))
    lineage = (tmp_path / "knowledge" / "lineage" / "views.yaml").read_text(encoding="utf-8")
    assert first.objects == 4 and "vw_Cartera" in lineage
    Flaky.down = True
    second = build_catalog(_inventory(), tmp_path, source_factory=Flaky)
    assert second.servers_ok == [] and set(second.servers_failed) == {"LOCAL", "CAIDO"}
    assert second.kept_from_failed == 4 and second.objects == 4
    assert sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / "catalog").rglob("*.yaml")) == before
    assert (tmp_path / "knowledge" / "lineage" / "views.yaml").read_text(encoding="utf-8") == lineage


def test_la_bd_de_trabajo_converdata_no_se_cataloga(tmp_path):
    class WithOwnDb(FakeSource):
        def list_databases(self):
            return [*super().list_databases(), "ConverData", "ConverData_QA"]

    report = build_catalog(_inventory(), tmp_path, source_factory=WithOwnDb,
                           exclude_databases=frozenset({"converdata", "converdata_qa"}))
    assert report.databases == ["LOCAL/BancaPrestamos", "LOCAL/BancaTarjetasCredito"]
    assert not (tmp_path / "catalog" / "desarrollo" / "LOCAL" / "ConverData").exists()


# --- Enriquecimiento: tablas que el modelo no describió y elección del rol ------------------------------------------


class EnriquecedorParcial:
    """Doble que imita una salida cortada por longitud: con un lote de varias tablas describe solo la primera; si se le
    pide una sola, la describe. `nunca` son tablas que no describe en ningún caso."""

    def __init__(self, nunca=()):
        self.nunca = {n.lower() for n in nunca}
        self.llamadas: list[list[str]] = []

    def enrich(self, tables):
        from converdata.llm.nodes import ColumnEnrichment, EnrichmentBatch, TableEnrichment

        self.llamadas.append([t["table"] for t in tables])
        pedidas = [t for t in tables if t["table"].split(".")[-1].lower() not in self.nunca]
        if len(tables) > 1:
            pedidas = pedidas[:1]
        return EnrichmentBatch(tables=[
            TableEnrichment(table=t["table"], description=f"Descripcion de {t['table']}", synonyms=["sinonimo"], columns=[
                ColumnEnrichment(name=c["name"], description=f"Columna {c['name']}") for c in t["columns"]])
            for t in pedidas
        ])


def _yaml(tmp_path, db, nombre):
    ruta = tmp_path / f"catalog/desarrollo/LOCAL/{db}/dbo.{nombre}.yaml"
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def test_las_tablas_que_el_modelo_no_describio_se_piden_de_nuevo_una_por_una(tmp_path):
    enriquecedor = EnriquecedorParcial()
    report = build_catalog(_inventory(), tmp_path, source_factory=FakeSource, enricher=enriquecedor)
    assert len(enriquecedor.llamadas[0]) == 4, "primero se pide el lote completo"
    reintentos = enriquecedor.llamadas[1:]
    assert reintentos and all(len(r) == 1 for r in reintentos), "las que faltaron se piden una por una"
    for db, nombre in [("BancaPrestamos", "Clientes"), ("BancaPrestamos", "Prestamos"), ("BancaPrestamos", "vw_Cartera"),
                       ("BancaTarjetasCredito", "Clientes")]:
        data = _yaml(tmp_path, db, nombre)
        assert data["description"], f"{db}.{nombre} quedó sin descripción"
        assert all(c.get("description") for c in data["columns"])
    assert report.enriched == 4 and not report.enrich_errors


def test_una_tabla_que_el_modelo_nunca_describe_se_reintenta_una_sola_vez_y_queda_sin_descripcion(tmp_path):
    enriquecedor = EnriquecedorParcial(nunca=["vw_Cartera"])
    report = build_catalog(_inventory(), tmp_path, source_factory=FakeSource, enricher=enriquecedor)
    solas = [llamada for llamada in enriquecedor.llamadas if llamada == ["BancaPrestamos.dbo.vw_Cartera"]]
    assert len(solas) == 1, "un solo reintento por tabla"
    assert report.enriched == 3
    assert not _yaml(tmp_path, "BancaPrestamos", "vw_Cartera").get("description")
    assert _yaml(tmp_path, "BancaPrestamos", "Prestamos")["description"]


def test_el_reintento_nunca_pisa_una_descripcion_que_no_es_generada(tmp_path):
    build_catalog(_inventory(), tmp_path, source_factory=FakeSource)
    ruta = tmp_path / "catalog/desarrollo/LOCAL/BancaPrestamos/dbo.Prestamos.yaml"
    data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    data["description"], data["description_source"] = "Préstamos desembolsados (revisado).", "human"
    ruta.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    class ConColumnaNueva(FakeSource):
        def extract_database(self, db):
            objs = super().extract_database(db)
            for o in objs:
                if o.name == "Prestamos":  # cambia la estructura: la tabla se vuelve a enriquecer
                    o.columns = [*o.columns, RawColumn("Canal", "varchar(20)", True)]
            return objs

    enriquecedor = EnriquecedorParcial()
    build_catalog(_inventory(), tmp_path, source_factory=ConColumnaNueva, enricher=enriquecedor)
    despues = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert despues["description"] == "Préstamos desembolsados (revisado)." and despues["description_source"] == "human"
    assert any("Prestamos" in t for llamada in enriquecedor.llamadas for t in llamada), "sí se pidió para la tabla"
    assert {c["name"] for c in despues["columns"]} >= {"Canal"}
    assert all(c.get("description") for c in despues["columns"])  # las columnas sin descripción sí se completan


def test_un_enriquecedor_que_falla_no_se_reintenta_en_bucle(tmp_path):
    class Roto:
        llamadas = 0

        def enrich(self, tables):
            Roto.llamadas += 1
            raise TimeoutError("sin respuesta")

    report = build_catalog(_inventory(), tmp_path, source_factory=FakeSource, enricher=Roto())
    assert Roto.llamadas <= 1 + 4, "el lote y, a lo sumo, un reintento por tabla"
    assert report.enriched == 0 and report.enrich_errors


class _LlmFalso:
    def __init__(self, rol):
        self.rol = rol

    def with_structured_output(self, schema):
        return self


class _GatewayFalso:
    def __init__(self, *roles):
        self.roles = set(roles)

    def has_role(self, rol):
        return rol in self.roles

    def chat(self, rol):
        return _LlmFalso(rol)


@pytest.mark.parametrize(
    ("roles", "esperado"),
    [
        (("enrich", "planner", "fast"), "enrich"),
        (("planner", "fast"), "planner"),
        (("fast",), "fast"),
        (("enrich", "fast"), "enrich"),
        ((), "fast"),  # sin ninguno declarado, `fast`: el gateway dirá que no está configurado
    ],
)
def test_build_enricher_prefiere_enrich_luego_planner_y_luego_fast(roles, esperado):
    from converdata.llm.nodes import LlmEnricher, build_enricher

    enriquecedor = build_enricher(_GatewayFalso(*roles))
    assert isinstance(enriquecedor, LlmEnricher)
    assert enriquecedor._llm.rol == esperado
