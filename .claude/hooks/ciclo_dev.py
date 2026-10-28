"""Hooks del ciclo de desarrollo de ConverData (codificar, probar, revisar, commit).

Uso: python .claude/hooks/ciclo_dev.py <fase>   (el evento llega por stdin como JSON)
  proteger-archivos  PreToolUse Edit|Write   bloquea .env, lockfiles, config/models.yaml y zips
  proteger-git       PreToolUse Bash         bloquea --no-verify y force push
  verificar-edicion  PostToolUse Edit|Write  sintaxis de .py y eslint de web/
  pruebas-commit     PreToolUse Bash         corre pytest antes de `git commit`
  cierre             Stop                    corre la prueba de capas si hay .py modificados

Salida 2 = bloquear (el stderr se devuelve a Claude). Salida 0 = continuar.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
PROTEGIDOS = (
    (re.compile(r"(^|/)\.env($|\.(?!example$))"), "contiene credenciales; edítalo a mano"),
    (re.compile(r"(^|/)(package-lock\.json|poetry\.lock|uv\.lock)$"), "es un lockfile generado; usa el gestor de paquetes"),
    (re.compile(r"(^|/)config/models\.yaml$"), "está ignorado por git y puede tener claves"),
    (re.compile(r"\.zip$"), "es un artefacto binario"),
)


def bloquear(mensaje: str) -> None:
    print(mensaje, file=sys.stderr)
    sys.exit(2)


def ejecutar(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=(os.name == "nt" and cmd[0] == "npx"))


def ruta_relativa(evento: dict) -> str:
    ruta = (evento.get("tool_input") or {}).get("file_path", "")
    try:
        return Path(ruta).resolve().relative_to(RAIZ.resolve()).as_posix()
    except ValueError:
        return Path(ruta).as_posix()


def comando(evento: dict) -> str:
    return (evento.get("tool_input") or {}).get("command", "")


def proteger_archivos(evento: dict) -> None:
    rel = ruta_relativa(evento)
    for patron, motivo in PROTEGIDOS:
        if patron.search(rel):
            bloquear(f"Edición bloqueada: {rel} {motivo}.")


def proteger_git(evento: dict) -> None:
    cmd = comando(evento)
    if re.search(r"\bgit\b.*\bcommit\b.*(--no-verify|\s-n\b)", cmd) or re.search(r"\bgit\b.*\bpush\b.*(--force\b|\s-f\b|--no-verify)", cmd):
        bloquear("Bloqueado: no se omiten los hooks ni se hace force push sin que el usuario lo pida explícitamente.")


def verificar_edicion(evento: dict) -> None:
    rel = ruta_relativa(evento)
    archivo = RAIZ / rel
    if rel.endswith(".py") and archivo.exists():
        r = ejecutar([sys.executable, "-m", "py_compile", str(archivo)], RAIZ, 30)
        if r.returncode:
            bloquear(f"Error de sintaxis en {rel}:\n{r.stderr}")
    elif rel.startswith("web/") and rel.endswith((".ts", ".tsx", ".js", ".mjs")) and archivo.exists() and (RAIZ / "web/node_modules").exists():
        r = ejecutar(["npx", "eslint", archivo.relative_to(RAIZ / "web").as_posix()], RAIZ / "web", 90)
        if r.returncode:
            bloquear(f"ESLint falló en {rel}:\n{r.stdout}{r.stderr}")


def pruebas_commit(evento: dict) -> None:
    if not re.search(r"\bgit\b\s+commit\b", comando(evento)):
        return
    r = ejecutar([sys.executable, "-m", "pytest", "-q", "-x", "--no-header"], RAIZ, 280)
    if "No module named pytest" in r.stderr:
        print("pytest no está instalado (pip install -e .[dev]); se omite la verificación previa al commit.", file=sys.stderr)
        return
    if r.returncode:
        bloquear(f"Commit bloqueado: pytest falló. Corrige antes de confirmar.\n{r.stdout[-3000:]}")


def cierre(evento: dict) -> None:
    if evento.get("stop_hook_active"):
        return
    r = ejecutar(["git", "status", "--porcelain", "--", "src", "api", "tests"], RAIZ, 15)
    if ".py" not in r.stdout:
        return
    r = ejecutar([sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "tests/test_architecture.py"], RAIZ, 120)
    if "No module named pytest" in r.stderr:
        return
    if r.returncode:
        bloquear(f"La prueba de capas (tests/test_architecture.py) falla; corrígela antes de terminar.\n{r.stdout[-3000:]}")


FASES = {
    "proteger-archivos": proteger_archivos,
    "proteger-git": proteger_git,
    "verificar-edicion": verificar_edicion,
    "pruebas-commit": pruebas_commit,
    "cierre": cierre,
}

if __name__ == "__main__":
    fase = FASES.get(sys.argv[1] if len(sys.argv) > 1 else "")
    if fase is None:
        bloquear(f"Fase desconocida. Opciones: {', '.join(FASES)}")
    try:
        evento = json.load(sys.stdin)
    except json.JSONDecodeError:
        evento = {}
    try:
        fase(evento)
    except subprocess.TimeoutExpired:
        print("Hook agotó su tiempo; se continúa sin verificar.", file=sys.stderr)