"""Cadena de suministro: lo que se instala y lo que se ejecuta en la CI está fijado (requirements/README.md).

No comprueba vulnerabilidades (eso lo hace el trabajo `cadena-de-suministro` de la CI con `pip-audit` y `npm audit`):
comprueba que nada vuelva a quedar sin fijar sin que alguien lo note.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_EXTRAS = ("api", "mcp", "sqlserver", "bedrock")
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(extras: tuple[str, ...] | None) -> set[str]:
    """Nombres de las dependencias de `pyproject.toml`: las base más las de `extras` (None = todos)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    optional = project["optional-dependencies"]
    requirements = list(project["dependencies"])
    for extra in optional if extras is None else extras:
        requirements += optional[extra]
    return {canonical(re.split(r"[\[<>=!~; ]", r, maxsplit=1)[0]) for r in requirements}


def locked(name: str) -> dict[str, list[str]]:
    """Paquete → sus hashes, leído de un bloqueo de `pip` (una entrada por paquete, con sus líneas `--hash`)."""
    packages: dict[str, list[str]] = {}
    current = None
    for line in (ROOT / "requirements" / name).read_text(encoding="utf-8").splitlines():
        pin = PIN.match(line)
        if pin:
            current = canonical(pin.group(1))
            packages[current] = []
        elif current and "--hash=sha256:" in line:
            packages[current].append(line.strip())
    return packages


@pytest.mark.parametrize("lock, extras", [("runtime.lock", RUNTIME_EXTRAS), ("dev.lock", None)])
def test_toda_dependencia_declarada_esta_fijada_con_su_hash(lock, extras):
    packages = locked(lock)
    missing = declared(extras) - set(packages)
    assert not missing, f"{lock} no fija {sorted(missing)}: regenerarlo (requirements/README.md)"
    without_hash = sorted(name for name, hashes in packages.items() if not hashes)
    assert not without_hash, f"{lock} tiene paquetes sin hash: {without_hash}"
    assert len(packages) > len(declared(extras))  # también las transitivas


def test_lo_que_se_despliega_no_trae_herramientas_de_desarrollo():
    runtime, dev = locked("runtime.lock"), locked("dev.lock")
    assert "pytest" in dev and "pytest" not in runtime
    assert {"langchain-ollama", "langchain-nvidia-ai-endpoints", "langchain-openai", "anthropic"}.isdisjoint(runtime)  # proveedores solo de desarrollo
    # Lo desplegado es un subconjunto exacto de lo que prueba la CI: mismas versiones, mismos hashes.
    assert all(dev.get(name) == hashes for name, hashes in runtime.items())
    assert list(locked("build.lock")) == ["setuptools"]
    tools = locked("tools.lock")
    assert {"pip-audit", "cyclonedx-bom"} <= set(tools) and all(tools.values())


def test_las_imagenes_base_van_por_digest_y_se_instala_con_hashes():
    for dockerfile in ("api/Dockerfile", "web/Dockerfile"):
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        bases = [line for line in text.splitlines() if line.startswith("FROM ")]
        assert bases and all(re.search(r"@sha256:[0-9a-f]{64}\b", line) for line in bases), (dockerfile, bases)
    api = (ROOT / "api" / "Dockerfile").read_text(encoding="utf-8")
    installs = [line for line in api.splitlines() if "pip install" in line and not line.lstrip().startswith("#")]
    assert installs and all(verified_install(line) for line in installs), installs
    # La clave de un repositorio de paquetes ajeno se comprueba contra una huella fijada antes de confiar en ella.
    assert re.search(r"MICROSOFT_KEY_FINGERPRINT=[0-9A-F]{40}\b", api) and "grep -q \"^fpr:" in api
    assert "npm ci" in (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")  # exactamente package-lock.json


def verified_install(line: str) -> bool:
    """Un `pip install` que no puede traer nada sin verificar: o exige hashes y paquetes ya compilados, o no usa la red."""
    return ("--require-hashes" in line and "--only-binary :all:" in line) or "--no-index" in line


def test_las_acciones_de_la_ci_van_por_commit_y_la_ci_analiza_las_dependencias():
    workflow = (ROOT / ".github" / "workflows" / "calidad.yml").read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*(\S+)", workflow)
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses
    # Todo `pip install` de la CI, también el de las herramientas que emiten el veredicto y el SBOM.
    installs = [line for line in workflow.splitlines() if "pip install" in line]
    assert len(installs) >= 4 and all(verified_install(line) for line in installs), installs
    assert "schedule:" in workflow and "permissions:\n  contents: read" in workflow
    assert "pull_request_target" not in workflow and "secrets." not in workflow
    for step in ("pip-audit -r requirements/runtime.lock --require-hashes", "npm audit --omit=dev --audit-level=high",
                 "cyclonedx-py requirements", "npm sbom"):
        assert step in workflow, step


def test_la_web_fija_versiones_exactas_y_su_bloqueo_trae_integridad():
    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] >= 3
    remote = {path: p for path, p in lock["packages"].items() if path and not p.get("link")}
    assert remote and all(p.get("integrity", "").startswith("sha") for p in remote.values())
    # Lo que se despliega va con versión exacta: una actualización es un cambio visible en el repositorio.
    assert re.fullmatch(r"\d+\.\d+\.\d+", package["dependencies"]["next"])
    assert lock["packages"]["node_modules/next"]["version"] == package["dependencies"]["next"]
