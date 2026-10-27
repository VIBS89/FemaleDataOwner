"""Ensayo del guion de la demo contra la API en modo demo (sin servidor HTTP): imprime lo que verá la pantalla.

    .venv/Scripts/python scripts/demo_probe.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from converdata_api.connector import DemoConnector  # noqa: E402
from converdata_api.main import create_app  # noqa: E402
from converdata_api.settings import ApiSettings  # noqa: E402

FIXTURES = [ROOT / "tests" / "fixtures" / "vbank", ROOT / "tests" / "fixtures" / "bancos"]
QUESTIONS = [  # guion de docs/demo-inversionistas.md y pantalla de bienvenida
    "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital.",
    "¿Qué proceso llena la dimensión de clientes del DWH?",
    "¿Dónde está el puntaje de riesgo crediticio del cliente?",
    "¿Cómo relaciono los clientes con sus tarjetas de crédito?",
    "¿Qué tabla tiene los pagos de las cuotas de préstamos?",
    "¿Dónde está el DUI del cliente?",
    "¿Cuál es el salario de los empleados?",
]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="converdata-demo-"))
    settings = ApiSettings(data_root=tmp / "catalog", inventory_path=tmp / "inventory.yaml", audit_dir=tmp / "audit",
                           curation_dir=tmp / "curation", demo=True, demo_fixtures=FIXTURES, allow_windows_auth=False)
    app = create_app(settings, DemoConnector(FIXTURES))

    def client(user: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/auth/login", json={"login": user, "password": "demo"})
        r.raise_for_status()
        return c

    admin = client("demo")
    admin.post("/admin/catalog/build", json={}).raise_for_status()
    while (job := admin.get("/admin/catalog/build").json())["status"] == "running":
        time.sleep(0.1)
    print(job["summary"], flush=True)
    analyst = client("analista")
    for q in QUESTIONS:
        t0 = time.perf_counter()
        env = analyst.post("/discover", json={"question": q}).json()
        ms = (time.perf_counter() - t0) * 1000
        disc = env.get("discovery") or {}
        top = [(c["asset_key"], round(c["confidence"], 2), c["description_source"]) for c in disc.get("candidates", [])[:2]]
        print(f"{ms:6.0f} ms  {q[:62]}\n          → {top}{'  [brecha]' if disc.get('knowledge_gap') else ''}")
        print("          " + env["answer_text"][:220].replace("\n", " "), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
