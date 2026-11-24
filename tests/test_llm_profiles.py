"""Perfiles de modelos elegibles en pantalla (F16, F17): selección guardada, `apply_profile` y guarda de residencia."""

from __future__ import annotations

from pathlib import Path

import pytest

from discovery_data_agent.llm import factory
from discovery_data_agent.llm.factory import (
    NO_MODEL,
    ModelsConfig,
    apply_profile,
    load_models,
    read_selection,
    selection_path,
    write_selection,
)
from discovery_data_agent.llm.gateway import GatewayConfigError, LLMGateway, ResidencyError

REPO = Path(__file__).resolve().parents[1]

CON_PERFILES = """
data_mode: test
active_profile: nvidia
providers:
  nvidia_nim: {enabled: false, api_key_env: NVIDIA_API_KEY, allowed_data: test}
  anthropic: {enabled: false, api_key_env: ANTHROPIC_API_KEY, allowed_data: test}
  openai: {enabled: false}
roles:
  fast: {provider: openai, model: modelo-del-archivo}
profiles:
  nvidia:
    label: NVIDIA
    roles:
      fast: {provider: nvidia_nim, model: nv-fast}
      enrich: {provider: nvidia_nim, model: nv-enrich}
  claude:
    label: Claude
    roles:
      fast: {provider: anthropic, model: cl-fast}
      enrich: {provider: anthropic, model: cl-enrich}
"""

SIN_PERFILES = """
data_mode: test
providers:
  nvidia_nim: {allowed_data: test}
roles:
  fast: {provider: nvidia_nim, model: modelo-del-archivo}
  planner: {provider: nvidia_nim, model: otro}
"""


def escribir(tmp_path, texto: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(texto, encoding="utf-8")
    return path


# --- 1. sin perfiles el archivo se comporta como antes ---------------------------------------------------
def test_sin_perfiles_se_usan_los_roles_del_archivo_aunque_exista_un_active(tmp_path):
    """HU on-premise (F16): un models.yaml antiguo, sin `profiles`, ignora el archivo `.active`."""
    path = escribir(tmp_path, SIN_PERFILES)
    for contenido in ("claude", NO_MODEL, "algo-que-no-existe"):
        write_selection(path, contenido)
        config = load_models(path)
        assert set(config.roles) == {"fast", "planner"}
        assert config.roles["fast"].model == "modelo-del-archivo"
        assert config.active_profile is None


# --- 2. selección guardada --------------------------------------------------------------------------------
def test_sin_active_se_aplica_el_perfil_del_archivo(tmp_path):
    path = escribir(tmp_path, CON_PERFILES)
    assert not selection_path(path).exists()
    config = load_models(path)
    assert config.active_profile == "nvidia"
    assert {r: c.model for r, c in config.roles.items()} == {"fast": "nv-fast", "enrich": "nv-enrich"}


def test_con_active_se_aplica_el_elegido(tmp_path):
    path = escribir(tmp_path, CON_PERFILES)
    write_selection(path, "claude")
    config = load_models(path)
    assert config.active_profile == "claude"
    assert {r: c.provider for r, c in config.roles.items()} == {"fast": "anthropic", "enrich": "anthropic"}


def test_un_active_que_ya_no_existe_cae_al_perfil_del_archivo(tmp_path):
    path = escribir(tmp_path, CON_PERFILES)
    write_selection(path, "retirado")
    config = load_models(path)
    assert config.active_profile == "nvidia"
    assert config.roles["fast"].model == "nv-fast"


def test_un_active_que_no_existe_y_sin_perfil_valido_en_el_archivo_deja_los_roles_del_archivo(tmp_path):
    path = escribir(tmp_path, CON_PERFILES.replace("active_profile: nvidia\n", ""))
    write_selection(path, "retirado")
    config = load_models(path)
    assert config.roles["fast"].model == "modelo-del-archivo"


def test_active_none_deja_el_flujo_sin_roles(tmp_path):
    path = escribir(tmp_path, CON_PERFILES)
    write_selection(path, NO_MODEL)
    config = load_models(path)
    assert config.roles == {}
    assert config.active_profile == NO_MODEL
    assert config.fallback is None


def test_apply_selection_false_no_aplica_nada(tmp_path):
    path = escribir(tmp_path, CON_PERFILES)
    write_selection(path, "claude")
    config = load_models(path, apply_selection=False)
    assert config.roles["fast"].model == "modelo-del-archivo"
    assert config.active_profile == "nvidia"  # lo que dice el archivo, sin tocar
    assert config.provider("anthropic").enabled is False
    assert set(config.profiles) == {"nvidia", "claude"}


def test_la_seleccion_se_guarda_junto_al_archivo_y_solo_lleva_el_nombre(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-centinela-9999")
    path = escribir(tmp_path, CON_PERFILES)
    assert selection_path(path) == tmp_path / "models.yaml.active"
    assert read_selection(path) is None
    write_selection(path, "claude")
    assert read_selection(path) == "claude"
    assert selection_path(path).read_text(encoding="utf-8").strip() == "claude"
    selection_path(path).write_text("  \n", encoding="utf-8")
    assert read_selection(path) is None  # vacío = sin selección


# --- 3. apply_profile ---------------------------------------------------------------------------------------
def test_apply_profile_activa_solo_los_proveedores_que_el_perfil_usa(tmp_path):
    base = load_models(escribir(tmp_path, CON_PERFILES), apply_selection=False)
    aplicado = apply_profile(base, "claude")
    assert aplicado.provider("anthropic").enabled is True
    assert aplicado.provider("nvidia_nim").enabled is False
    assert aplicado.provider("openai").enabled is False
    assert aplicado.provider("anthropic").api_key_env == "ANTHROPIC_API_KEY"  # conserva el resto de su ajuste
    assert base.provider("anthropic").enabled is False  # la configuración original no se muta
    assert base.roles["fast"].model == "modelo-del-archivo"


def test_apply_profile_con_nombre_desconocido_falla(tmp_path):
    base = load_models(escribir(tmp_path, CON_PERFILES), apply_selection=False)
    with pytest.raises(ValueError, match="desconocido"):
        apply_profile(base, "inventado")


def test_apply_profile_sin_nombre_o_sin_perfiles_no_cambia_nada(tmp_path):
    con = load_models(escribir(tmp_path, CON_PERFILES), apply_selection=False)
    assert apply_profile(con, None) is con
    sin = ModelsConfig.model_validate({"roles": {"fast": {"provider": "nvidia_nim", "model": "m"}}})
    assert apply_profile(sin, "lo-que-sea") is sin


def test_apply_profile_none_no_exige_que_exista_un_perfil_llamado_none(tmp_path):
    base = load_models(escribir(tmp_path, CON_PERFILES), apply_selection=False)
    assert apply_profile(base, NO_MODEL).roles == {}


# --- 4. la guarda de residencia sigue mandando ----------------------------------------------------------------
def test_con_datos_reales_un_perfil_con_proveedor_de_prueba_no_pasa_el_gateway(tmp_path):
    """F17/OP-06: elegir un perfil no salta la guarda `data_mode: real` frente a `allowed_data: test`."""
    texto = CON_PERFILES.replace("data_mode: test", "data_mode: real")
    base = load_models(escribir(tmp_path, texto), apply_selection=False)
    for nombre in ("nvidia", "claude"):
        with pytest.raises(ResidencyError, match="data_mode=real"):
            LLMGateway(apply_profile(base, nombre))
    LLMGateway(apply_profile(base, NO_MODEL))  # sin modelo no sale ningún dato: siempre válido


def test_con_datos_reales_un_perfil_con_proveedor_real_pasa(tmp_path):
    texto = CON_PERFILES.replace("data_mode: test", "data_mode: real").replace(
        "anthropic: {enabled: false, api_key_env: ANTHROPIC_API_KEY, allowed_data: test}",
        "anthropic: {enabled: false, api_key_env: ANTHROPIC_API_KEY, allowed_data: real}")
    base = load_models(escribir(tmp_path, texto), apply_selection=False)
    LLMGateway(apply_profile(base, "claude"))
    with pytest.raises(ResidencyError):
        LLMGateway(apply_profile(base, "nvidia"))


def test_un_perfil_cuyo_proveedor_esta_desactivado_en_el_archivo_se_activa_pero_ollama_sigue_restringido(tmp_path):
    texto = CON_PERFILES + """
  local:
    label: Local
    roles:
      fast: {provider: ollama, model: llama}
"""
    base = load_models(escribir(tmp_path, texto), apply_selection=False)
    with pytest.raises(GatewayConfigError, match="environment: local"):
        LLMGateway(apply_profile(base, "local"))


def test_validar_un_perfil_no_llama_al_proveedor(tmp_path, monkeypatch):
    """Validar solo revisa la configuración: ningún constructor de modelo se invoca."""
    llamadas: list[str] = []

    def prohibido(*args, **kwargs):
        llamadas.append("construido")
        raise AssertionError("validar no debe construir ni llamar a un modelo")

    for clave in list(factory.BUILDERS):
        monkeypatch.setitem(factory.BUILDERS, clave, prohibido)
    base = load_models(escribir(tmp_path, CON_PERFILES), apply_selection=False)
    LLMGateway(apply_profile(base, "claude")).validate()
    LLMGateway(apply_profile(base, "nvidia")).validate()
    assert llamadas == []


# --- 5. config/models.example.yaml ---------------------------------------------------------------------------
def test_el_ejemplo_define_los_perfiles_nvidia_y_claude():
    config = load_models(REPO / "config" / "models.example.yaml", apply_selection=False)
    assert {"nvidia", "claude"} <= set(config.profiles)
    for nombre in ("nvidia", "claude"):
        assert {"fast", "enrich"} <= set(config.profiles[nombre].roles), nombre
        assert config.profiles[nombre].label
    assert config.active_profile in config.profiles
    assert config.profiles["nvidia"].roles["fast"].provider == "nvidia_nim"
    assert config.profiles["claude"].roles["fast"].provider == "anthropic"
    # Cada perfil del ejemplo es válido para el gateway tal cual (data_mode test).
    for nombre in config.profiles:
        LLMGateway(apply_profile(config, nombre))
