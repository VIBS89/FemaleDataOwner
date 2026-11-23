"""Qué situación de desarrollo (OP-09) exige cada marca de pytest y cómo se detecta en el entorno."""

from __future__ import annotations

import sys
from collections.abc import Mapping

MARCAS = {
    "llm_local": "SD-2: Ollama (bge-m3 y un modelo de chat) o NVIDIA NIM con datos de prueba",
    "sqlserver": "SD-3: SQL Server 2025 con Full-Text",
    "bedrock": "SD-4: cuenta AWS con Bedrock",
    "windows_server": "SD-5: Windows Server de QA con IIS",
}


def motivo_de_omision(marca: str, entorno: Mapping[str, str], plataforma: str = sys.platform) -> str | None:
    """`None` si la situación está disponible; si no, el motivo que `pytest -rs` muestra."""
    if marca == "sqlserver" and not entorno.get("CONVERDATA_TEST_DB"):
        return "SD-3 no disponible: falta CONVERDATA_TEST_DB (cadena ODBC de una instancia SQL Server 2025 de prueba)"
    if marca == "llm_local" and not (entorno.get("OLLAMA_HOST") or entorno.get("NVIDIA_API_KEY")):
        return "SD-2 no disponible: ni OLLAMA_HOST ni NVIDIA_API_KEY están definidos"
    if marca == "bedrock":
        if not (entorno.get("AWS_ACCESS_KEY_ID") or entorno.get("AWS_PROFILE")):
            return "SD-4 no disponible: faltan credenciales de AWS (AWS_ACCESS_KEY_ID o AWS_PROFILE)"
        if not entorno.get("CONVERDATA_MODELS"):
            return "SD-4 no disponible: CONVERDATA_MODELS no apunta a un models.yaml con proveedor bedrock"
    if marca == "windows_server":
        if not plataforma.startswith("win"):
            return "SD-5 no disponible: no se ejecuta en Windows Server"
        if not entorno.get("CONVERDATA_IIS"):
            return "SD-5 no disponible: no hay IIS (defina CONVERDATA_IIS=1 en el Windows Server de QA)"
    return None
