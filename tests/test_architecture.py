"""Regla de dependencias entre capas del backend (docs/architecture/capas-backend.md).

    integración ──► aplicación ──► dominio ◄── infraestructura

- **Dominio**: modelos, catálogo, lógica determinista de descubrimiento, grafo y puertos (Protocols). No conoce a nadie.
- **Aplicación**: casos de uso (flujos de LangGraph, consultas de descubrimiento). Solo usa el dominio y sus puertos.
- **Infraestructura**: adaptadores de los puertos (SQL Server, almacenes vectoriales, proveedores de LLM).
- **Integración**: API, MCP, CLI y la raíz de composición (`bootstrap`), que conecta adaptadores con casos de uso.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

# Prefijo de módulo → capa. Gana el prefijo más largo.
LAYERS = {
    "discovery_data_agent.models": "domain",
    "discovery_data_agent.catalog": "domain",
    "discovery_data_agent.config": "domain",
    "discovery_data_agent.curation": "domain",
    "discovery_data_agent.discovery": "domain",
    "discovery_data_agent.graph": "domain",
    "discovery_data_agent.builder": "domain",
    "discovery_data_agent.identity": "domain",
    "discovery_data_agent.audit": "domain",
    "discovery_data_agent.memory.base": "domain",
    "discovery_data_agent.memory.text": "domain",
    "discovery_data_agent.metadata.ports": "domain",
    "discovery_data_agent.ask": "domain",  # AskFlow: motor, validador y puertos (F6–F10)
    "discovery_data_agent.ask.planner": "infrastructure",  # el planner con LLM (langchain)
    "discovery_data_agent.audit.sqlserver": "infrastructure",
    "discovery_data_agent.audit.chain": "infrastructure",
    "discovery_data_agent.flows": "application",
    "discovery_data_agent.application": "application",
    "discovery_data_agent.memory": "infrastructure",
    "discovery_data_agent.metadata": "infrastructure",
    "discovery_data_agent.llm": "infrastructure",
    "discovery_data_agent.observability": "infrastructure",
    "discovery_data_agent.storage": "infrastructure",
    "discovery_data_agent.integration": "integration",
    "discovery_data_agent.bootstrap": "integration",
    "discovery_data_agent.cli": "integration",
    "discovery_data_agent.evaluation": "integration",
}

ALLOWED = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "infrastructure": {"domain", "infrastructure"},
    "integration": {"domain", "application", "infrastructure", "integration"},
}

# Librerías de adaptadores: solo infraestructura e integración pueden importarlas.
ADAPTER_LIBS = {"pyodbc", "langchain_core", "langchain_aws", "langchain_ollama", "langchain_nvidia_ai_endpoints",
                "langchain_openai", "anthropic", "openai",
                "fastapi", "starlette", "mcp", "uvicorn", "httpx", "boto3"}


def layer_of(module: str) -> str | None:
    best = max((p for p in LAYERS if module == p or module.startswith(p + ".")), key=len, default=None)
    return LAYERS[best] if best else None


def modules():
    for path in sorted((SRC / "discovery_data_agent").rglob("*.py")):
        rel = path.relative_to(SRC).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        yield ".".join(parts), path


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):  # incluye imports perezosos dentro de funciones
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_every_module_has_a_layer():
    missing = [m for m, _ in modules() if m != "discovery_data_agent" and layer_of(m) is None]
    assert missing == [], f"Módulos sin capa asignada en LAYERS: {missing}"


def test_dependencies_point_inwards():
    violations = []
    for module, path in modules():
        layer = layer_of(module)
        if layer is None:
            continue
        for imported in imports_of(path):
            if not imported.startswith("discovery_data_agent."):
                continue
            target = layer_of(imported)
            if target and target not in ALLOWED[layer]:
                violations.append(f"{module} ({layer}) → {imported} ({target})")
    assert violations == [], "Dependencias que rompen la regla de capas:\n" + "\n".join(violations)


def test_domain_and_application_do_not_import_adapter_libraries():
    violations = []
    for module, path in modules():
        if layer_of(module) not in ("domain", "application"):
            continue
        for imported in imports_of(path):
            if imported.split(".")[0] in ADAPTER_LIBS:
                violations.append(f"{module} → {imported}")
    assert violations == [], "El dominio y la aplicación no dependen de adaptadores:\n" + "\n".join(violations)
