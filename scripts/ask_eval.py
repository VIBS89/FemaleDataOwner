"""Verifica el AskFlow contra los casos de uso de `scripts/ask_casos.yaml`.

Para cada caso: hace la pregunta a DiscoveryDataAgent-API (como lo haría la web) y compara las cifras de la respuesta con las
de la consulta de verificación, que se ejecuta directamente en SQL Server con el mismo login.

    .venv/Scripts/python scripts/ask_eval.py --login demo            # pide la contraseña
    .venv/Scripts/python scripts/ask_eval.py --login demo --solo top-comercios,compras-q2

Sale con código 1 si algún caso falla. Imprime solo totales y cifras agregadas, nunca filas con datos personales.
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import getpass
import json
import os
import sys
import urllib.request
from pathlib import Path

import pyodbc
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 0.005  # 0.5 %: redondeos de promedios y porcentajes


def post(api: str, path: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(api + path, json.dumps(body).encode("utf-8"), headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)


def numeric(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, decimal.Decimal)):
        return float(value)
    return None


def same_number(a: float, b: float) -> bool:
    """Iguales con tolerancia; un porcentaje puede venir como 12.5 o como 0.125."""
    for x in (a, a * 100, a / 100):
        if abs(x - b) <= max(abs(b) * TOLERANCE, 0.01):
            return True
    return False


def text_key(value) -> str | None:
    return str(value).strip().lower() if isinstance(value, str) and value.strip() else None


def matches(expected: list[list], got: list[list], case: dict) -> tuple[bool, str]:
    """Cada fila esperada debe aparecer en el resultado: sus cifras (y sus textos, salvo `solo_cifras`)."""
    if not got:
        return False, "el agente no devolvió filas"
    if case.get("sin_orden"):
        want = sorted(n for r in expected for v in r if (n := numeric(v)) is not None)
        have = sorted(n for r in got for v in r if (n := numeric(v)) is not None)
        ok = all(any(same_number(h, w) for h in have) for w in want)
        return ok, "" if ok else f"esperaba {want}, obtuve {have[:10]}"
    only = case.get("solo_cifras")
    for row in expected:
        cols = only if only is not None else range(len(row))
        nums = [n for i in cols if (n := numeric(row[i])) is not None]
        texts = [] if only is not None else [t for v in row if (t := text_key(v))]
        found = any(
            all(any((h := numeric(v)) is not None and same_number(h, n) for v in r) for n in nums)
            and all(any(text_key(v) == t for v in r) for t in texts)
            for r in got
        )
        if not found:
            return False, f"no aparece la fila esperada {[_short(v) for v in row]}"
    if len(got) != len(expected) and len(expected) > 1:
        return False, f"esperaba {len(expected)} filas, obtuve {len(got)}"
    return True, ""


def _short(value):
    if isinstance(value, (float, decimal.Decimal)):
        return round(float(value), 2)
    return value


def run_sql(conn, sql: str) -> list[list]:
    return [list(r) for r in conn.cursor().execute(sql).fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--server", default=r"localhost\SQLEXPRESS")
    parser.add_argument("--login", required=True)
    parser.add_argument("--casos", default=str(ROOT / "scripts" / "ask_casos.yaml"))
    parser.add_argument("--solo", help="ids separados por coma")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    password = os.environ.get("DISCOVERY_DATA_AGENT_EVAL_PASSWORD") or getpass.getpass(f"Contraseña de {args.login}: ")

    spec = yaml.safe_load(Path(args.casos).read_text(encoding="utf-8"))
    cases = spec["casos"]
    if args.solo:
        wanted = set(args.solo.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if str(spec.get("fecha_hoy")) != str(dt.date.today()):
        print(f"Aviso: los casos con periodos relativos asumen hoy = {spec.get('fecha_hoy')} (hoy es {dt.date.today()}).")

    token = post(args.api, "/auth/login", {"auth": "sql", "login": args.login, "password": password})["token"]
    conn = pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={args.server};UID={args.login};"
                          f"PWD={{{password}}};TrustServerCertificate=yes", readonly=True)

    passed = 0
    for case in cases:
        env = post(args.api, "/discover", {"question": case["pregunta"], "history": case.get("historial", [])}, token)
        data = env.get("data") or {}
        figure = env.get("figure")
        engine = "plantilla" if figure else ("LLM" if data else "-")
        if figure:  # cifra de plantilla (decisión 17): un total o un desglose por categoría
            groups = figure.get("groups") or []
            data = {"rows": [[g["label"], g["value"]] for g in groups] if groups else [[figure.get("value")]],
                    "sql": " ; ".join(figure.get("sql") or [])}
        if case.get("flujo") == "discover":
            top = ((env.get("discovery") or {}).get("candidates") or [{}])[0].get("asset_key")
            ok = env["flow"] == "discover" and top == case["candidato"]
            why = "" if ok else f"flujo={env['flow']}, candidato={top}"
        elif env["flow"] != "ask":
            ok, why = False, f"no calculó el dato ({'; '.join(env.get('assumptions') or []) or env['answer_text'][:80]})"
        else:
            ok, why = False, ""
            for sql in [case["esperado"], *case.get("alternativas", [])]:
                ok, why = matches(run_sql(conn, sql), data.get("rows", []), case)
                if ok:
                    break
        passed += ok
        mark = "OK " if ok else "FALLA"
        print(f"[{mark}] {engine:9s} {case['categoria']:32s} {case['pregunta']}")
        print(f"        → {env['answer_text']}")
        if not ok:
            print(f"        ✗ {why}")
            if data.get("sql"):
                print(f"        SQL: {data['sql']}")
    print(f"\n{passed}/{len(cases)} casos correctos")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
