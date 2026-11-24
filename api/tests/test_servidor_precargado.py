"""Servidor precargado (`DISCOVERY_DATA_AGENT_PRELOAD_SERVER`): en un entorno de pruebas con SQL Server en la propia tarea
(deploy/aws, `sql_sidecar`), el operador fija el servidor al desplegar. Así el primer login no pide el host ni el código
de instalación, y el demo sobrevive a un reinicio de la tarea sin volver a registrarlo. En qa y prod no se acepta."""

from pathlib import Path

from fastapi.testclient import TestClient

from discovery_data_agent_api.connector import DemoConnector
from discovery_data_agent_api.main import create_app
from discovery_data_agent_api.security import production_violations
from discovery_data_agent_api.settings import ApiSettings

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "bancos"


def _settings(tmp_path, **extra):
    return ApiSettings(
        data_root=tmp_path / "catalog", inventory_path=tmp_path / "inventory.yaml", audit_dir=tmp_path / "audit",
        curation_dir=tmp_path / "curation", demo=True, demo_fixtures=[FIXTURE], demo_preload_inventory=False,
        allow_windows_auth=False, setup_token="codigo-del-instalador", **extra,
    )


def test_el_servidor_precargado_entra_al_inventario_y_el_login_no_pide_host_ni_codigo(tmp_path):
    client = TestClient(create_app(_settings(tmp_path, preload_server="localhost,1433|SQL Server demo|desarrollo"),
                                   DemoConnector(FIXTURE)))

    status = client.get("/setup/status").json()
    assert status["has_inventory"] is True
    assert status["setup_token_required"] is False
    assert [(s["alias"], s["environment"]) for s in status["servers"]] == [("SQL Server demo", "desarrollo")]

    r = client.post("/auth/login", json={"login": "demo", "password": "demo"})
    assert r.status_code == 200, r.text


def test_sin_servidor_precargado_el_primer_login_sigue_pidiendo_el_codigo(tmp_path):
    client = TestClient(create_app(_settings(tmp_path), DemoConnector(FIXTURE)))

    assert client.get("/setup/status").json()["setup_token_required"] is True
    r = client.post("/auth/login", json={"login": "demo", "password": "demo", "host": "demo-sql"})
    assert r.status_code == 403


def test_un_servidor_precargado_mal_escrito_no_arranca(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        create_app(_settings(tmp_path, preload_server="solo-el-host"), DemoConnector(FIXTURE))


def test_con_login_de_construccion_el_catalogo_se_descubre_al_arrancar(tmp_path):
    import time

    client = TestClient(create_app(_settings(tmp_path, preload_server="localhost,1433|SQL Server demo|desarrollo",
                                             preload_build_login="demo", preload_build_password="demo"),
                                   DemoConnector(FIXTURE)))
    for _ in range(200):
        status = client.get("/setup/status").json()
        if status["build"]["status"] != "running":
            break
        time.sleep(0.05)
    assert status["build"]["status"] == "ok", status
    assert status["has_catalog"] is True

    client.post("/auth/login", json={"login": "demo", "password": "demo"})
    r = client.post("/discover", json={"question": "¿Dónde está el DUI del cliente?"})
    assert r.status_code == 200, r.text


def test_sin_login_de_construccion_no_se_descubre_nada_al_arrancar(tmp_path):
    client = TestClient(create_app(_settings(tmp_path, preload_server="localhost,1433|SQL Server demo|desarrollo"),
                                   DemoConnector(FIXTURE)))
    status = client.get("/setup/status").json()
    assert status["build"]["status"] == "idle"
    assert status["has_catalog"] is False


def test_qa_y_prod_no_aceptan_un_servidor_precargado(tmp_path):
    problems = production_violations(_settings(tmp_path, preload_server="localhost,1433|SQL|desarrollo"))
    assert any("DISCOVERY_DATA_AGENT_PRELOAD_SERVER" in p for p in problems)
