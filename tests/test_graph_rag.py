"""GraphRAG sobre el catálogo que el agente descubrió de BancosSQL (fixture `tests/fixtures/bancos`, solo metadatos)."""

from pathlib import Path

import pytest

from converdata.bootstrap import build_service, user_with_databases
from converdata.discovery.expansion import decompose, plan_query
from converdata.evaluation.discovery_eval import evaluate, load_cases

BANCOS = Path(__file__).parent / "fixtures" / "bancos"


@pytest.fixture(scope="module")
def bancos():
    return build_service(BANCOS)


@pytest.fixture(scope="module")
def everyone(bancos):
    return user_with_databases(bancos, "dev", None)


def test_entidad_cliente_en_cuatro_bds(bancos, everyone):
    graph = bancos.deps.graph
    copies = graph.copies("BancaTarjetasCredito.dbo.Clientes.DUI", everyone.visible_ids)
    assert copies[0] == "BancaPrestamos.dbo.Clientes.DUI"  # canónica primero
    assert len(copies) == 4


def test_camino_de_union_respeta_permisos(bancos, everyone):
    graph = bancos.deps.graph
    path = graph.join_path("BancaPrestamos.dbo.CuotasPrestamo", "BancaPrestamos.dbo.Clientes", everyone.visible_ids)
    assert [(e.kind, e.detail) for e in path] == [("fk", "PrestamoID"), ("fk", "ClienteID")]
    sin_prestamos = frozenset(i for i in everyone.visible_ids if ".Prestamos" not in i)  # no ve la tabla puente
    assert graph.join_path("BancaPrestamos.dbo.CuotasPrestamo", "BancaPrestamos.dbo.Clientes", sin_prestamos) is None


def test_una_sola_respuesta_por_dato_de_la_entidad(bancos, everyone):
    env = bancos.run("¿Dónde está el DUI del cliente?", everyone)
    top = env.discovery.candidates[0]
    assert top.asset_key == "BancaPrestamos.dbo.Clientes.DUI"
    assert set(top.copies) == {f"Banca{db}.dbo.Clientes.DUI" for db in ("CuentasDebito", "TarjetasCredito", "Tokenizacion")}
    shown = [c.asset_key for c in env.discovery.candidates] + [a.asset_key for a in env.discovery.alternatives]
    assert not [k for k in shown if k.endswith("Clientes.DUI") and k != top.asset_key]


def test_pregunta_compuesta_trae_el_camino(bancos, everyone):
    env = bancos.run("¿Dónde están los días de mora de las cuotas de préstamo y el DUI del cliente?", everyone)
    assert env.discovery.candidates[0].asset_key == "BancaPrestamos.dbo.CuotasPrestamo.DiasMora"
    path = env.discovery.join_paths[0]
    assert path.tables == ["BancaPrestamos.dbo.CuotasPrestamo", "BancaPrestamos.dbo.Prestamos", "BancaPrestamos.dbo.Clientes"]


def test_descomposicion():
    assert decompose("¿Dónde está el saldo de la cuenta y el nombre de la agencia?") == [
        "donde esta el saldo de la cuenta", "el nombre de la agencia"]
    assert decompose("¿Qué tipo de dispositivo usa el cliente?") == ["¿Qué tipo de dispositivo usa el cliente?"]
    plan = plan_query("¿Dónde están los días de mora de las cuotas y el DUI del cliente?", None, True, 0.8)
    assert plan.primary_concepts and plan.secondary_parts


def test_regresion_por_tipo_de_pregunta(bancos):
    """Umbrales medidos con el catálogo crudo (sin descripciones ni embeddings). Si bajan, algo empeoró."""
    report = evaluate(bancos, load_cases(BANCOS / "eval" / "discovery.yaml"))
    by_type = report.by_type()
    assert by_type["A"]["hit@1"] == 100.0
    assert by_type["D"]["hit@1"] == 100.0 and by_type["D"]["dups"] == 0
    assert by_type["C"]["related"] == 100.0 and by_type["C"]["hit@1"] >= 80.0
    assert by_type["G"]["ok"] == 100.0
    assert report.metrics["leaks"] == 0 and report.metrics["invented"] == 0


def test_sin_grafo_hay_duplicados_y_sin_caminos(bancos):
    """Ablación: el mismo set sin el patrón `graph` muestra para qué sirve el grafo."""
    bancos.deps.settings.patterns.graph = False
    try:
        report = evaluate(bancos, load_cases(BANCOS / "eval" / "discovery.yaml"))
    finally:
        bancos.deps.settings.patterns.graph = True
    assert report.by_type()["D"]["hit@1"] < 100.0
    assert report.by_type()["C"]["related"] < 100.0


def test_canal_semantico_encuentra_sinonimos_sin_coincidencia_lexica():
    """Con un embedder (aquí uno de juguete) 'billetera' encuentra Wallets aunque no comparta palabras."""

    class ToyEmbedder:
        groups = [("billetera", "wallet"), ("huella", "fingerprint")]

        def _vec(self, text):
            t = text.lower()
            return [1.0 if any(w in t for w in g) else 0.0 for g in self.groups] + [0.01]

        def embed_documents(self, texts):
            return [self._vec(t) for t in texts]

        def embed_query(self, text):
            return self._vec(text)

    lexical = build_service(BANCOS)
    user = user_with_databases(lexical, "dev", None)
    assert lexical.deps.store.search_tables("billeteras móviles", visible_ids=user.visible_ids) == []
    service = build_service(BANCOS, embedder_override=ToyEmbedder())
    hits = service.deps.store.search_tables("billeteras móviles", visible_ids=user.visible_ids)
    assert "BancaTokenizacion.dbo.Wallets" in [h.asset_key for h in hits[:2]]
