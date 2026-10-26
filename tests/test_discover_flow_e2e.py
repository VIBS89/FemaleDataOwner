"""E2E del DiscoverFlow: pregunta en lenguaje natural → grafo de LangGraph → candidatos descubiertos entre varias BDs."""

from converdata.audit.recorder import discovery_rows
from conftest import ONBOARDING_Q


def _top_keys(env):
    disc = env.discovery
    return [c.asset_key for c in disc.candidates] + [a.asset_key for a in disc.alternatives]


def test_pregunta_de_la_propuesta_devuelve_los_tres_identificadores(service, analyst):
    """F22-CA1: ClientCode, LegalClientId y UserId entre los 3 primeros (candidatos + alternativas)."""
    env = service.run(ONBOARDING_Q, analyst)
    assert env.status == "ok" and env.flow == "discover"
    top3 = _top_keys(env)[:3]
    assert top3[0] == "VBank_ING.dbo.Users.ClientCode"
    assert set(top3) == {
        "VBank_ING.dbo.Users.ClientCode",
        "VBank_ING.dbo.Users.LegalClientId",
        "VBank_ING.dbo.Users.UserId",
    }
    assert env.discovery.candidates[0].confidence >= 0.85
    assert not env.discovery.knowledge_gap


def test_cada_candidato_trae_los_ocho_elementos(service, analyst):
    """F22-CA2: tabla, campo, BD, ambiente, servidor, descripción, confianza y relaciones."""
    env = service.run(ONBOARDING_Q, analyst)
    top = env.discovery.candidates[0]
    assert (top.table, top.column, top.database) == ("Users", "ClientCode", "VBank_ING")
    assert {(l.environment, l.server) for l in top.locations} == {
        ("produccion", "SQL Producción Canales"),
        ("qa", "SQL QA Canales"),
    }
    assert top.description and top.description_source == "human"
    assert 0 < top.confidence <= 1
    assert env.discovery.related
    # El servidor se muestra por alias, nunca por host.
    assert "corp.local" not in env.model_dump_json()


def test_descubre_relaciones_entre_bases_de_datos(service, analyst):
    """El activo se conecta con las otras BDs del patrimonio: origen ETL (Onboarding), réplica (DWH) y misma entidad."""
    env = service.run(ONBOARDING_Q, analyst)
    top = env.discovery.candidates[0]
    assert top.lineage.upstream == ["Onboarding.dbo.Solicitud"]
    assert top.lineage.downstream == ["DWH.dim.Cliente"]
    relations = {(r.from_, r.to, r.relation) for r in env.discovery.related}
    assert ("Onboarding.dbo.Solicitud", "VBank_ING.dbo.Users", "etl") in relations
    assert ("VBank_ING.dbo.Users", "DWH.dim.Cliente", "etl") in relations
    assert ("VBank_ING.dbo.UserDevices", "VBank_ING.dbo.Users", "fk") in relations
    assert ("VBank_ING.dbo.Users", "DWH.dim.Cliente", "same_entity") in relations
    assert set(env.databases) >= {"VBank_ING", "Onboarding", "DWH"}
    # La copia del DWH es una réplica por ETL: se muestra como linaje, no como alternativa.
    assert "DWH.dim.Cliente.ClientCode" not in _top_keys(env)


def test_reglas_responsables_y_drift(service, analyst):
    env = service.run(ONBOARDING_Q, analyst)
    top = env.discovery.candidates[0]
    assert [r.id for r in top.business_rules] == ["BR-ONB-004"]
    assert top.owners.business == "Producto Banca Digital"
    assert top.drift_warning == "QA difiere de produccion"
    assert any(e.kind == "golden_discovery" for e in top.evidence)


def test_usuario_sin_permiso_no_descubre_nada_de_vbank(service, rrhh_user):
    """F22-CA4 / F14-CA6: ni candidatos, ni ubicaciones, ni relaciones, ni reglas; respuesta sin nombres."""
    env = service.run(ONBOARDING_Q, rrhh_user)
    dump = env.model_dump_json(by_alias=True)
    for forbidden in ("VBank_ING", "Onboarding", "DWH", "ClientCode", "Users"):
        assert forbidden not in dump
    assert env.discovery.candidates == []
    assert env.discovery.knowledge_gap
    assert env.answer_text.startswith("No encontré datos disponibles para ti")


def test_rrhh_invisible_para_el_analista(service, analyst):
    env = service.run("¿dónde está el salario de los empleados?", analyst)
    assert "RRHH" not in env.model_dump_json(by_alias=True)
    assert env.discovery.candidates == []


def test_ubicacion_sin_permiso_no_aparece(service):
    """Si solo puede leer la copia de QA, solo ve la ubicación de QA (F14)."""
    from converdata.models.identity import UserContext

    ids = frozenset({"qa:SRVQASQL01.VBank_ING.dbo.Users"})
    env = service.run(ONBOARDING_Q, UserContext(user_id="qa", visible_ids=ids))
    top = env.discovery.candidates[0]
    assert [l.environment for l in top.locations] == ["qa"]
    assert top.drift_warning is None
    # El linaje hacia BDs no visibles se recorta.
    assert top.lineage.upstream == [] and top.lineage.downstream == []
    assert env.discovery.related == []


def test_resumen_de_dominio_recorre_las_bds(service, analyst):
    """Intent `exploration` (RF-11): tablas principales de la entidad Cliente en sus tres BDs, canónica primero."""
    env = service.run("¿qué datos tenemos de clientes?", analyst)
    keys = [c.asset_key for c in env.discovery.candidates]
    assert keys[0] == "VBank_ING.dbo.Users"
    assert {"DWH.dim.Cliente", "Onboarding.dbo.Solicitud"} <= set(keys)
    assert all(c.kind == "table" for c in env.discovery.candidates)


def test_pregunta_de_datos_sin_askflow_indica_donde_estan(service, analyst):
    """F3: con `features.ask_flow: false` una pregunta de cifras se responde como descubrimiento."""
    env = service.run("¿cuántos clientes se registraron por onboarding el mes pasado?", analyst)
    assert env.flow == "discover" and env.status == "ok"
    assert env.assumptions and "no está habilitada" in env.assumptions[0]
    assert env.discovery.candidates[0].asset_key == "VBank_ING.dbo.Users"


def test_otras_preguntas_reales(service, analyst):
    cases = {
        "¿dónde está la fecha de alta del cliente digital?": "VBank_ING.dbo.Users.CreatedAt",
        "¿qué significa el estado de la solicitud de onboarding?": "Onboarding.dbo.Solicitud.Estado",
        "¿qué proceso llena la dimensión de clientes del DWH?": "DWH.dim.Cliente",
    }
    for question, expected in cases.items():
        env = service.run(question, analyst)
        assert env.discovery.candidates[0].asset_key == expected, question


def test_aclaracion_y_fuera_de_alcance(service, analyst):
    env = service.run("dame los datos", analyst)
    assert env.status == "needs_clarification" and env.clarification.options
    env = service.run("borra los pedidos cancelados", analyst)
    assert env.status == "rejected" and env.discovery is None


def test_auditoria_un_registro_por_pregunta(service, analyst):
    """F11-CA1 y CA5: una fila de `audit_question`, pasos del DiscoverFlow y filas de `audit_discovery`."""
    env = service.run(ONBOARDING_Q, analyst)
    records = service.deps.audit.records
    assert len(records) == 1 and records[0].trace_id == env.trace_id
    assert [s.step for s in records[0].steps] == ["intent", "retrieve", "grade", "rerank", "expand", "review", "respond"]
    rows = discovery_rows(env)
    disc = env.discovery
    assert len(rows) == len(disc.candidates) + len(disc.alternatives) + len(disc.related)


def test_auditoria_fail_closed(service, analyst):
    class Broken:
        def write(self, record):
            raise ConnectionError("BD ConverData caída")

    service.deps.audit = Broken()
    from converdata.flows.discover import DiscoverService

    env = DiscoverService(service.deps).run(ONBOARDING_Q, analyst)
    assert env.status == "error" and env.discovery is None


def test_stream_emite_pasos_y_respuesta(service, analyst):
    events = list(service.stream(ONBOARDING_Q, analyst))
    nodes = [payload["node"] for kind, payload in events if kind == "step"]
    assert nodes == ["intent", "retrieve", "grade", "rerank", "expand", "review", "respond"]
    assert events[-1][0] == "answer" and events[-1][1]["discovery"]["candidates"]


def test_determinista_misma_pregunta_misma_respuesta(service, analyst):
    a = service.run(ONBOARDING_Q, analyst).discovery.model_dump()
    b = service.run(ONBOARDING_Q, analyst).discovery.model_dump()
    assert a == b
