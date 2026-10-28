"""Situaciones de desarrollo (OP-09 §Tests por situación): los tests con marca se omiten con el motivo, nunca en verde silencioso.

CA: OP-09 CA1 (los tests de SD-2 a SD-5 aparecen como omitidos con su motivo).
"""

from __future__ import annotations

import pytest

from situaciones import MARCAS, motivo_de_omision


def test_sqlserver_se_omite_sin_instancia_y_el_motivo_nombra_la_variable():
    motivo = motivo_de_omision("sqlserver", {}, plataforma="win32")
    assert motivo is not None and "CONVERDATA_TEST_DB" in motivo


def test_sqlserver_corre_con_instancia_de_prueba():
    assert motivo_de_omision("sqlserver", {"CONVERDATA_TEST_DB": "Driver=x"}, plataforma="win32") is None


def test_llm_local_se_omite_sin_ollama_ni_nim_y_corre_con_cualquiera():
    motivo = motivo_de_omision("llm_local", {}, plataforma="win32")
    assert motivo is not None and "OLLAMA_HOST" in motivo and "NVIDIA_API_KEY" in motivo
    assert motivo_de_omision("llm_local", {"OLLAMA_HOST": "http://localhost:11434"}, plataforma="win32") is None
    assert motivo_de_omision("llm_local", {"NVIDIA_API_KEY": "nvapi-prueba"}, plataforma="win32") is None


def test_bedrock_exige_credenciales_aws_y_proveedor_bedrock_en_los_modelos():
    assert "AWS" in motivo_de_omision("bedrock", {}, plataforma="win32")
    solo_credenciales = {"AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "x"}
    assert "CONVERDATA_MODELS" in motivo_de_omision("bedrock", solo_credenciales, plataforma="win32")
    completo = {**solo_credenciales, "CONVERDATA_MODELS": "config/models.yaml"}
    assert motivo_de_omision("bedrock", completo, plataforma="win32") is None


def test_bedrock_acepta_un_perfil_de_aws_como_credencial():
    entorno = {"AWS_PROFILE": "dev", "CONVERDATA_MODELS": "config/models.yaml"}
    assert motivo_de_omision("bedrock", entorno, plataforma="win32") is None


def test_windows_server_se_omite_fuera_de_windows_o_sin_iis():
    assert "Windows" in motivo_de_omision("windows_server", {}, plataforma="linux")
    assert "IIS" in motivo_de_omision("windows_server", {}, plataforma="win32")
    assert motivo_de_omision("windows_server", {"CONVERDATA_IIS": "1"}, plataforma="win32") is None


def test_sin_marca_conocida_no_hay_motivo_de_omision():
    assert motivo_de_omision("slow", {}, plataforma="win32") is None


def test_las_cuatro_situaciones_estan_registradas_en_pyproject():
    import tomllib
    from pathlib import Path

    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    opciones = config["tool"]["pytest"]["ini_options"]
    registradas = {m.split(":")[0].strip() for m in opciones["markers"]}
    assert set(MARCAS) <= registradas
    assert "--strict-markers" in opciones["addopts"]


@pytest.mark.sqlserver
def test_centinela_sqlserver_aparece_omitido_con_motivo_sin_instancia():
    """Si este test corre es porque hay `CONVERDATA_TEST_DB`; sin ella `pytest -rs` lo lista como omitido."""
    import os

    assert os.environ.get("CONVERDATA_TEST_DB")
