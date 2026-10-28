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
    "converdata.models": "domain",
    "converdata.catalog": "domain",
    "converdata.config": "domain",
    "converdata.discovery": "domain",
    "converdata.graph": "domain",
    "converdata.builder": "domain",
    "converdata.identity": "domain",
    "converdata.audit": "domain",
    "converdata.memory.base": "domain",
    "converdata.memory.text": "domain",
    "converdata.metadata.ports": "domain",
    "converdata.audit.sqlserver": "infrastructure",
    "converdata.catalog.files": "infrastructure",
    "converdata.flows": "application",
    "converdata.application": "application",
    "converdata.memory": "infrastructure",
    "converdata.metadata": "infrastructure",
    "converdata.llm": "infrastructure",
    "converdata.observability": "infrastructure",
    "converdata.integration": "integration",
    "converdata.bootstrap": "integration",
    "converdata.cli": "integration",
    "converdata.evaluation": "integration",
}

ALLOWED = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "infrastructure": {"domain", "infrastructure"},
    "integration": {"domain", "application", "infrastructure", "integration"},
}

# Librerías de adaptadores: solo infraestructura e integración pueden importarlas.
ADAPTER_LIBS = {"pyodbc", "langchain_core", "langchain_aws", "langchain_ollama", "langchain_nvidia_ai_endpoints",
                "fastapi", "starlette", "mcp", "uvicorn", "httpx", "boto3"}


def layer_of(module: str) -> str | None:
    best = max((p for p in LAYERS if module == p or module.startswith(p + ".")), key=len, default=None)
    return LAYERS[best] if best else None


def modules():
    for path in sorted((SRC / "converdata").rglob("*.py")):
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
    missing = [m for m, _ in modules() if m != "converdata" and layer_of(m) is None]
    assert missing == [], f"Módulos sin capa asignada en LAYERS: {missing}"


def test_dependencies_point_inwards():
    violations = []
    for module, path in modules():
        layer = layer_of(module)
        if layer is None:
            continue
        for imported in imports_of(path):
            if not imported.startswith("converdata."):
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
