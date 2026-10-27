"""Piezas deterministas: catálogo (F1), memoria (F2), intención (F3), visibilidad (F14) y confianza (F22)."""

import pytest
import yaml

from converdata.catalog.store import load_catalog
from converdata.config import DiscoverySettings, load_inventory
from converdata.discovery.deterministic import RuleBasedIntentClassifier
from converdata.discovery.engine import Draft, compute_confidence
from converdata.identity.visibility import VisibilityResolver, VisibleObject
from converdata.memory.memory_store import InMemoryVectorStore
from converdata.models.catalog import CatalogObject
from conftest import FIXTURE, ONBOARDING_Q

# --- F1 catálogo ---------------------------------------------------------------------------------


def test_catalogo_rechaza_valores_de_datos():
    data = yaml.safe_load((FIXTURE / "catalog/produccion/SRVPRDSQL01/VBank_ING/dbo.Users.yaml").read_text(encoding="utf-8"))
    data["columns"][1]["sample_values"] = ["ACME-TEST-123"]
    with pytest.raises(ValueError, match="valores de datos"):
        CatalogObject.model_validate(data)


def test_catalogo_valida_ids():
    data = yaml.safe_load((FIXTURE / "catalog/produccion/SRVPRDSQL01/VBank_ING/dbo.Users.yaml").read_text(encoding="utf-8"))
    data["id"] = "produccion:OTRO.VBank_ING.dbo.Users"
    with pytest.raises(ValueError):
        CatalogObject.model_validate(data)


def test_catalogo_agrupa_ambientes_con_referencia_primero(service):
    copies = service.deps.catalog.copies("VBank_ING.dbo.Users.ClientCode")
    assert [o.environment for o in copies] == ["produccion", "qa"]


# --- F2 memoria ----------------------------------------------------------------------------------


def _all_ids(service):
    return frozenset(o.id for o in service.deps.catalog.objects)


def test_busqueda_lexica_nombre_tecnico_primero(service):
    """F2-CA6: buscar `ClientCode` devuelve esa columna primero."""
    hits = service.deps.store.search_columns("ClientCode", visible_ids=_all_ids(service))
    assert {h.asset_key for h in hits[:2]} == {"VBank_ING.dbo.Users.ClientCode", "DWH.dim.Cliente.ClientCode"}
    hits = service.deps.store.search_columns("LegalClientId", visible_ids=_all_ids(service))
    assert hits[0].asset_key == "VBank_ING.dbo.Users.LegalClientId"


def test_busqueda_filtra_por_visibilidad(service, analyst):
    """F2-CA2: con `visible_ids` sin RRHH, ninguna búsqueda devuelve RRHH."""
    store = service.deps.store
    assert all(not h.asset_key.startswith("RRHH") for h in store.search_columns("identificador único empleado salario", visible_ids=analyst.visible_ids))
    assert all(not h.asset_key.startswith("RRHH") for h in store.search_tables("empleados salario", visible_ids=analyst.visible_ids))
    knowledge = store.search_knowledge("planilla empleado", visible_ids=analyst.visible_ids, groups=["GG-RRHH"])
    assert all(h.item.domain != "rrhh" for h in knowledge)


def test_conocimiento_respeta_acl_de_origen(service, rrhh_user):
    store = service.deps.store
    with_group = store.search_knowledge("planilla empleado", visible_ids=rrhh_user.visible_ids, groups=["GG-RRHH"])
    without = store.search_knowledge("planilla empleado", visible_ids=rrhh_user.visible_ids, groups=[])
    assert [h.item.id for h in with_group] == ["doc-rrhh-planilla"] and without == []


def test_golden_solo_si_todos_sus_activos_son_visibles(service, rrhh_user, analyst):
    store = service.deps.store
    assert store.search_golden_discovery(ONBOARDING_Q, visible_ids=rrhh_user.visible_ids) == []
    hits = store.search_golden_discovery(ONBOARDING_Q, visible_ids=analyst.visible_ids)
    assert hits[0].golden.id == "gd-001" and hits[0].similarity >= 0.85


def test_visible_ids_es_obligatorio(service):
    with pytest.raises(ValueError):
        service.deps.store.search_tables("clientes", visible_ids=None)


def test_index_catalog_idempotente(service):
    store = InMemoryVectorStore()
    first = store.index_catalog(service.deps.catalog)
    second = store.index_catalog(service.deps.catalog)
    assert first.documents == second.documents
    # Un documento por asset_key, no por ambiente: Users (prod + QA) cuenta una vez.
    assert first.collections["tables"] == len(service.deps.catalog.table_keys())


# --- F3 intención --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,intent",
    [
        (ONBOARDING_Q, "discovery"),
        ("¿qué datos tenemos de inventario?", "exploration"),
        ("¿cuánto vendimos en el último trimestre?", "data_query"),
        ("dame los datos", "ambiguous"),
        ("borra los pedidos cancelados", "out_of_scope"),
        ("hola", "out_of_scope"),
        ("¿qué significa EstadoCta?", "discovery"),
    ],
)
def test_clasificacion_de_intencion(question, intent):
    assert RuleBasedIntentClassifier().classify(question, []).intent == intent


def test_intencion_de_la_propuesta():
    """F3-CA5."""
    result = RuleBasedIntentClassifier().classify(ONBOARDING_Q, [])
    assert result.business_context == "onboarding digital"
    assert result.asset_kind_hint == "column"
    assert result.environment_hint == "produccion"


# --- F14 visibilidad -----------------------------------------------------------------------------


class FakeLister:
    def __init__(self, objects):
        self.objects, self.calls = objects, 0

    def visible_objects(self, server_id, databases):
        self.calls += 1
        return [o for s, o in self.objects if s == server_id and o.database in databases]


def test_visibilidad_se_mapea_a_ids_fisicos_y_se_cachea():
    inventory = load_inventory(FIXTURE / "config/databases.yaml")
    lister = FakeLister([
        ("SRVPRDSQL01", VisibleObject("VBank_ING", "dbo", "Users")),
        ("SRVQASQL01", VisibleObject("VBank_ING", "dbo", "Users")),
    ])
    clock = iter([0.0, 100.0, 1000.0, 1000.0]).__next__  # guardar, 2.ª consulta, 3.ª consulta, guardar
    resolver = VisibilityResolver(inventory, ttl_seconds=900, clock=clock)
    ids = resolver.resolve("s1", lister, ["SRVPRDSQL01"])  # solo el servidor donde el login se validó
    assert ids == {"produccion:SRVPRDSQL01.VBank_ING.dbo.Users"}
    resolver.resolve("s1", lister, ["SRVPRDSQL01"])
    assert lister.calls == 1  # cacheado
    resolver.resolve("s1", lister, ["SRVPRDSQL01"])
    assert lister.calls == 2  # expiró a los 15 min


# --- F22 confianza -------------------------------------------------------------------------------


def test_formula_de_confianza():
    d = Draft("A.dbo.T.C", "column", relevance=1.0, retrieval_norm=1.0, description_source="human",
              golden_confirmation=1.0, sources={"catalog", "data_dictionary", "golden"})
    assert compute_confidence(d, DiscoverySettings()) == 1.0
    d = Draft("A.dbo.T.C", "column", relevance=0.5, retrieval_norm=0.8, description_source="data_dictionary",
              sources={"catalog", "data_dictionary"})
    # 0.35*0.5 + 0.25*0.8 + 0.15*0.9 + 0 + 0.10*(2/3)
    assert compute_confidence(d, DiscoverySettings()) == pytest.approx(0.5767, abs=1e-4)


def test_tope_si_solo_hay_descripcion_generada():
    d = Draft("A.dbo.T.C", "column", relevance=1.0, retrieval_norm=1.0, description_source="generated", sources={"catalog"})
    assert compute_confidence(d, DiscoverySettings()) == 0.6


# --- F23: los marcadores de redacción no son contenido -------------------------------------------


def test_marcadores_de_pii_redactada_no_se_indexan():
    from converdata.memory.text import tokenize

    assert tokenize("Ejemplo: cliente <DUI> con cuenta <CUENTA_BANCARIA>.") == tokenize("Ejemplo: cliente con cuenta.")


def test_dui_no_lo_gana_un_documento_que_solo_tiene_el_marcador(service, analyst):
    env = service.run("¿Dónde está el DUI del cliente?", analyst)
    assert env.discovery.candidates[0].asset_key == "Onboarding.dbo.Solicitud.NumeroDocumento"
