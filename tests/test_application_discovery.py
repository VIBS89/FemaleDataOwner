"""Capa de aplicación: consultas de descubrimiento que usan la API, el chat y el MCP (F12, F14, F19, F22).

La regla central: lo que el usuario no puede ver responde igual que lo que no existe.
"""

import pytest

from converdata.application.discovery import DiscoveryTools
from conftest import ONBOARDING_Q

CLIENT_CODE = "VBank_ING.dbo.Users.ClientCode"
USERS = "VBank_ING.dbo.Users"


@pytest.fixture
def tools(service):
    return DiscoveryTools(service)


# --- discover ------------------------------------------------------------------------------------


def test_discover_devuelve_el_envelope_del_flujo_y_lo_audita(tools, analyst, service):
    env = tools.discover(analyst, ONBOARDING_Q)
    assert env.flow == "discover" and env.status == "ok"
    assert env.discovery.candidates[0].asset_key == CLIENT_CODE
    audited = service.deps.audit.records[-1]
    assert audited.trace_id == env.trace_id and audited.client == "mcp"


# --- get_asset -----------------------------------------------------------------------------------


def test_get_asset_de_columna_trae_ubicaciones_reglas_responsables_y_linaje(tools, analyst):
    card = tools.get_asset(analyst, CLIENT_CODE)
    assert card.kind == "column" and card.column == "ClientCode" and card.table == "Users"
    assert {loc.environment for loc in card.locations} == {"produccion", "qa"}
    assert "BR-ONB-004" in [r.id for r in card.business_rules]
    assert card.lineage.upstream == ["Onboarding.dbo.Solicitud"]
    assert card.columns == []  # una columna no lista columnas


def test_get_asset_de_tabla_lista_columnas_sin_valores(tools, analyst):
    card = tools.get_asset(analyst, USERS)
    assert card.kind == "table"
    assert "ClientCode" in [c.name for c in card.columns]
    dumped = card.model_dump_json()
    assert "sample" not in dumped  # F1: nunca valores de datos


def test_get_asset_no_revela_lo_que_el_usuario_no_ve(tools, rrhh_user):
    assert tools.get_asset(rrhh_user, CLIENT_CODE) is None
    assert tools.get_asset(rrhh_user, "NoExiste.dbo.Tabla") is None  # misma respuesta que lo inexistente


def test_get_asset_omite_copias_en_bds_no_visibles(tools, service):
    from converdata.bootstrap import user_with_databases

    solo_ing = user_with_databases(service, "ing", ["VBank_ING"])
    card = tools.get_asset(solo_ing, USERS)
    assert all(not c.startswith(("DWH.", "Onboarding.")) for c in card.copies)
    assert card.lineage.upstream == [] and card.lineage.downstream == []


# --- relaciones, reglas, linaje y alternativas ---------------------------------------------------


def test_get_lineage_muestra_el_paquete_y_el_job(tools, analyst):
    edges = tools.get_lineage(analyst, CLIENT_CODE)
    by_name = {e.via.name: e for e in edges}
    assert by_name["ONB_CargaUsuarios"].via.job == "JOB_ONB_Nocturno"
    assert {e.to for e in edges} >= {"DWH.dim.Cliente"}


@pytest.mark.parametrize("call", ["get_related", "get_lineage", "list_business_rules", "find_alternatives"])
def test_detalle_de_un_activo_no_visible_esta_vacio(tools, rrhh_user, call):
    assert getattr(tools, call)(rrhh_user, CLIENT_CODE) == []


def test_list_business_rules_del_activo(tools, analyst):
    assert [r.id for r in tools.list_business_rules(analyst, CLIENT_CODE)] == ["BR-ONB-004"]


def test_get_related_incluye_la_misma_entidad_en_otras_bds(tools, analyst):
    related = tools.get_related(analyst, USERS)
    assert any(r.relation == "same_entity" for r in related)
    assert all(not r.to.startswith("RRHH.") and not r.from_.startswith("RRHH.") for r in related)


# --- catálogo y grafo del patrimonio (F19) -------------------------------------------------------


def test_search_catalog_filtra_por_visibilidad_y_acota_k(tools, analyst, rrhh_user):
    hits = tools.search_catalog(analyst, "código del cliente", k=500)
    assert hits and len(hits) <= 50
    assert all(not h.asset_key.startswith("RRHH.") for h in hits)
    rrhh_hits = tools.search_catalog(rrhh_user, "empleado")
    assert rrhh_hits and all(h.asset_key.startswith("RRHH.") for h in rrhh_hits)
    assert tools.search_catalog(rrhh_user, "ClientCode") == []


def test_where_is_ubica_la_entidad_con_la_canonica_primero(tools, analyst, rrhh_user):
    [cliente] = tools.where_is(analyst, "cliente")
    assert cliente.entity == "Cliente" and cliente.tables[0] == cliente.canonical
    assert set(cliente.tables) == {"VBank_ING.dbo.Users", "Onboarding.dbo.Solicitud", "DWH.dim.Cliente"}
    assert tools.where_is(rrhh_user, "cliente") == []  # sin tablas visibles la entidad no se menciona


def test_find_join_path_solo_por_tablas_visibles(tools, analyst, rrhh_user):
    path = tools.find_join_path(analyst, "Onboarding.dbo.Solicitud", "DWH.dim.Cliente")
    assert path is not None and path.tables[0] == "Onboarding.dbo.Solicitud" and path.tables[-1] == "DWH.dim.Cliente"
    assert tools.find_join_path(rrhh_user, "Onboarding.dbo.Solicitud", "DWH.dim.Cliente") is None


def test_estate_overview_resume_solo_lo_visible(tools, analyst, rrhh_user):
    overview = tools.estate_overview(analyst)
    assert {d.database for d in overview.databases} == {"VBank_ING", "Onboarding", "DWH"}
    assert [e.entity for e in overview.entities] == ["Cliente"]
    rrhh = tools.estate_overview(rrhh_user)
    assert [d.database for d in rrhh.databases] == ["RRHH"] and rrhh.entities == []
