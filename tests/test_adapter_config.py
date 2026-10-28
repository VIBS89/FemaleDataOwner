"""Selección de adaptadores por configuración y guarda de entorno (OP-09 §Selección de adaptadores, CA2 y CA3).

Se prueba con un `Mapping` en lugar de `os.environ`: la función es pura.
"""

from __future__ import annotations

import pytest

from converdata.audit.sqlserver import SqlServerAuditSink
from converdata.bootstrap import (
    AdapterConfig,
    ConfiguracionInvalida,
    build_service,
    resolve_audit_sink,
    resolve_catalog_store,
)
from converdata.catalog.files import FileCatalogStore
from converdata.config import Settings
from conftest import FIXTURE

DB = "Driver={ODBC Driver 18 for SQL Server};Server=localhost;Database=ConverData;Trusted_Connection=yes"
EN_SERVIDOR = {"CONVERDATA_STORE": "sqlserver", "CONVERDATA_AUDIT": "sqlserver", "CONVERDATA_DB": DB}


def _models(tmp_path, proveedor="bedrock"):
    ruta = tmp_path / "models.yaml"
    ruta.write_text(
        f"providers:\n  {proveedor}: {{enabled: true}}\nroles:\n  planner: {{provider: {proveedor}, model: m}}\n",
        encoding="utf-8",
    )
    return str(ruta)


def test_por_defecto_todo_en_archivos_y_entorno_dev():
    cfg = AdapterConfig.from_env({})

    assert (cfg.store, cfg.audit, cfg.env, cfg.db, cfg.models) == ("files", "files", "dev", None, None)


def test_la_auditoria_sigue_al_almacen_si_no_se_indica():
    assert AdapterConfig.from_env({"CONVERDATA_STORE": "sqlserver", "CONVERDATA_DB": DB}).audit == "sqlserver"


def test_la_auditoria_puede_ir_en_archivos_con_el_almacen_en_sqlserver():
    cfg = AdapterConfig.from_env({"CONVERDATA_STORE": "sqlserver", "CONVERDATA_AUDIT": "files", "CONVERDATA_DB": DB})

    assert (cfg.store, cfg.audit) == ("sqlserver", "files")


@pytest.mark.parametrize("variable", ["CONVERDATA_STORE", "CONVERDATA_AUDIT", "CONVERDATA_ENV"])
def test_un_valor_desconocido_falla_nombrando_la_variable(variable):
    with pytest.raises(ConfiguracionInvalida, match=variable):
        AdapterConfig.from_env({variable: "inventado"})


def test_sqlserver_sin_cadena_de_conexion_falla_nombrando_converdata_db():
    with pytest.raises(ConfiguracionInvalida, match="CONVERDATA_DB"):
        AdapterConfig.from_env({"CONVERDATA_STORE": "sqlserver"})


@pytest.mark.parametrize("cadena", [DB + ";PWD=secreto", DB + ";Password=secreto", DB + ";pwd = secreto"])
def test_la_cadena_de_conexion_no_puede_llevar_la_contrasena(cadena):
    with pytest.raises(ConfiguracionInvalida, match="CONVERDATA_DB_PASSWORD"):
        AdapterConfig.from_env({**EN_SERVIDOR, "CONVERDATA_DB": cadena})


def test_la_contrasena_solo_entra_a_la_conexion_desde_su_variable_y_no_se_ve_en_el_repr():
    entorno = {**EN_SERVIDOR, "CONVERDATA_DB": DB.replace("Trusted_Connection=yes", "UID=cd_app")}
    cfg = AdapterConfig.from_env(entorno)

    assert "PWD" not in cfg.db
    assert cfg.connection_string({"CONVERDATA_DB_PASSWORD": "prueba-123"}).endswith(";PWD=prueba-123")
    assert "prueba-123" not in repr(cfg)


@pytest.mark.parametrize("env", ["qa", "prod"])
@pytest.mark.parametrize("variable", ["CONVERDATA_STORE", "CONVERDATA_AUDIT"])
def test_fuera_de_dev_no_se_permiten_archivos(env, variable):
    entorno = {**EN_SERVIDOR, "CONVERDATA_ENV": env, variable: "files"}

    with pytest.raises(ConfiguracionInvalida, match=variable):
        AdapterConfig.from_env(entorno)


@pytest.mark.parametrize("env", ["qa", "prod"])
def test_con_sqlserver_completo_arranca_en_qa_y_prod(env):
    cfg = AdapterConfig.from_env({**EN_SERVIDOR, "CONVERDATA_ENV": env})

    assert (cfg.store, cfg.audit, cfg.env) == ("sqlserver", "sqlserver", env)


@pytest.mark.parametrize("env", ["qa", "prod"])
def test_fuera_de_dev_no_se_permite_el_modo_demo(env):
    with pytest.raises(ConfiguracionInvalida, match="CONVERDATA_DEMO"):
        AdapterConfig.from_env({**EN_SERVIDOR, "CONVERDATA_ENV": env, "CONVERDATA_DEMO": "1"})


def test_en_dev_el_modo_demo_sigue_permitido():
    assert AdapterConfig.from_env({"CONVERDATA_DEMO": "1"}).env == "dev"


@pytest.mark.parametrize("proveedor", ["ollama", "nvidia_nim"])
def test_fuera_de_dev_no_se_permiten_ollama_ni_nim(tmp_path, proveedor):
    entorno = {**EN_SERVIDOR, "CONVERDATA_ENV": "qa", "CONVERDATA_MODELS": _models(tmp_path, proveedor)}

    with pytest.raises(ConfiguracionInvalida, match=f"CONVERDATA_MODELS.*{proveedor}"):
        AdapterConfig.from_env(entorno)


def test_fuera_de_dev_bedrock_si_esta_permitido(tmp_path):
    entorno = {**EN_SERVIDOR, "CONVERDATA_ENV": "prod", "CONVERDATA_MODELS": _models(tmp_path, "bedrock")}

    assert AdapterConfig.from_env(entorno).models is not None


def test_el_respaldo_tambien_cuenta_como_proveedor(tmp_path):
    ruta = tmp_path / "models.yaml"
    ruta.write_text("roles:\n  planner: {provider: bedrock, model: m}\nfallback: {provider: ollama}\n", encoding="utf-8")

    with pytest.raises(ConfiguracionInvalida, match="ollama"):
        AdapterConfig.from_env({**EN_SERVIDOR, "CONVERDATA_ENV": "qa", "CONVERDATA_MODELS": str(ruta)})


def test_un_archivo_de_modelos_inexistente_falla_nombrando_la_variable(tmp_path):
    with pytest.raises(ConfiguracionInvalida, match="CONVERDATA_MODELS"):
        AdapterConfig.from_env({"CONVERDATA_MODELS": str(tmp_path / "no-existe.yaml")})


@pytest.mark.parametrize("env", ["qa", "prod"])
def test_fuera_de_dev_la_auditoria_no_puede_fallar_abierta(env):
    settings = Settings.model_validate({"audit": {"fail_open": True}})

    with pytest.raises(ConfiguracionInvalida, match="fail_open"):
        AdapterConfig.from_env({**EN_SERVIDOR, "CONVERDATA_ENV": env}, settings=settings)


def test_en_dev_fail_open_sigue_permitido():
    AdapterConfig.from_env({}, settings=Settings.model_validate({"audit": {"fail_open": True}}))


def test_el_almacen_de_archivos_se_resuelve_con_el_directorio_raiz():
    cfg = AdapterConfig.from_env({})

    assert isinstance(resolve_catalog_store(cfg, FIXTURE), FileCatalogStore)


def test_el_catalogo_en_sqlserver_aun_no_tiene_adaptador_y_lo_dice():
    cfg = AdapterConfig.from_env(EN_SERVIDOR)

    with pytest.raises(ConfiguracionInvalida, match="CONVERDATA_STORE=sqlserver"):
        resolve_catalog_store(cfg, FIXTURE)


def test_la_auditoria_en_sqlserver_se_resuelve_con_la_conexion_inyectada():
    cfg = AdapterConfig.from_env(EN_SERVIDOR)

    assert isinstance(resolve_audit_sink(cfg, connect=lambda: None), SqlServerAuditSink)


def test_la_auditoria_en_archivos_la_resuelve_la_integracion():
    assert resolve_audit_sink(AdapterConfig.from_env({}), connect=lambda: None) is None


def test_build_service_conserva_su_firma_y_acepta_un_almacen():
    service = build_service(FIXTURE, store=FileCatalogStore(FIXTURE))

    assert service.deps.catalog.objects
