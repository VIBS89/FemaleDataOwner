"""Curación y captura del conocimiento (F24): lo que la API añade sobre los repositorios.

- `CurationDesk`: responsables por login, dudas escaladas ("Preguntar al responsable") y su aviso. La notificación
  lleva solo el dominio y el enlace a la vista Curación, nunca el texto de la pregunta (OP-04 CA7).
- `demand_by_asset` y `metrics_report`: la cola de revisión y el tablero de impacto, calculados desde la auditoría.

El estado vive en el `CurationRepository` (esquema `curation` de la BD `DiscoveryDataAgent`; archivos en desarrollo). Las
descripciones, las reglas y las confirmaciones se escriben por `AgentRuntime` (`KnowledgeWriter`).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
import urllib.request
import uuid
from collections import Counter, defaultdict

from discovery_data_agent.catalog.ids import table_key
from discovery_data_agent.curation import CurationRepository

log = logging.getLogger(__name__)
STEWARDS_TTL_S = 5.0


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class CurationDesk:
    def __init__(self, repository: CurationRepository, notify_webhook: str | None = None, public_url: str = ""):
        self.repository = repository
        self.notify_webhook = notify_webhook
        self.public_url = public_url.rstrip("/")
        self._stewards: tuple[float, list[dict]] | None = None  # (leído_en, lista)

    # --- responsables -------------------------------------------------------------------------------
    def stewards(self) -> list[dict]:
        """Se releen como mucho cada `STEWARDS_TTL_S` segundos (una petición comprueba el dominio de cada fila de un
        diccionario); guardar la lista la refresca al momento, así quitar un rol rige de inmediato."""
        cached = self._stewards
        if cached is None or time.monotonic() - cached[0] > STEWARDS_TTL_S:
            cached = (time.monotonic(), [{"login": s["login"].lower(), "domains": list(s.get("domains") or ["*"])}
                                         for s in self.repository.stewards()])
            self._stewards = cached
        return [dict(s) for s in cached[1]]

    def save_stewards(self, items: list[dict], *, by: str) -> list[dict]:
        clean: dict[str, dict] = {}
        for item in items:
            login = item["login"].strip().lower()
            if login:
                domains = list(dict.fromkeys(d.strip() for d in item.get("domains") or [] if d.strip())) or ["*"]
                clean[login] = {"login": login, "domains": domains}
        self.repository.save_stewards(list(clean.values()), by=by)
        self._stewards = None
        return list(clean.values())

    def steward_domains(self, login: str) -> list[str] | None:
        """Dominios de un responsable (`["*"]` = todos); None si no es responsable."""
        for s in self.stewards():
            if s["login"] == login.lower():
                return s["domains"]
        return None

    # --- solicitudes escaladas (F24 §Escalamiento) ---------------------------------------------------
    def requests(self) -> list[dict]:
        return self.repository.requests()

    def create_request(self, user_id: str, trace_id: str, question: str, domain: str, shown: list[str],
                       note: str | None) -> dict:
        new = {"id": uuid.uuid4().hex[:10], "created_at": _now(), "status": "open", "user_id": user_id,
               "trace_id": trace_id, "question": question, "domain": domain, "shown": shown,
               "note": (note or "")[:500] or None, "answer": None}
        stored = self.repository.add_requests([new])[0]
        if stored["id"] == new["id"]:  # si ya existía (misma respuesta y usuario), no se avisa otra vez
            self._notify(domain)
        return stored

    def answer_request(self, request_id: str, by: str, kind: str, asset_key: str | None, note: str | None) -> dict:
        answer = {"by": by, "at": _now(), "kind": kind, "asset_key": asset_key, "note": (note or "")[:1000] or None}
        return self.repository.answer_request(request_id, "answered" if kind == "asset" else "no_source", answer)

    def _notify(self, domain: str) -> None:
        """Webhook (Teams u otro) con el dominio y el enlace; el texto de la pregunta se lee dentro de la aplicación."""
        if not self.notify_webhook:
            return
        body = json.dumps({"text": f"DiscoveryDataAgent: nueva duda escalada en el dominio «{domain}». Revísala en {self.public_url}/curacion"})

        def send():
            try:
                req = urllib.request.Request(self.notify_webhook, data=body.encode("utf-8"),
                                             headers={"content-type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10).close()
            except Exception as exc:  # la solicitud ya quedó guardada; solo se pierde el aviso
                log.warning("no se pudo notificar la solicitud: %s", type(exc).__name__)

        threading.Thread(target=send, daemon=True).start()


def demand_by_asset(audit_rows: list[dict]) -> Counter:
    """Número de preguntas en las que apareció cada activo (y su tabla): ordena la cola de revisión (F24)."""
    demand: Counter = Counter()
    for row in audit_rows:
        seen = set()
        for d in row.get("discovery") or []:
            key = d.get("asset_key") or ""
            if "->" in key:
                continue
            seen.update({key, table_key(key)})
        demand.update(seen)
    return demand


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def metrics_report(rows: list[dict], requests: list[dict], days: int) -> dict:
    """Scorecard de F25 desde la auditoría: adopción, calidad percibida, escalamientos y latencia, sin leer SQL ni datos."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    def ts(row):
        return dt.datetime.fromisoformat(row["ts"])

    rows = [r for r in rows if ts(r) >= since]
    questions = [r for r in rows if r["type"] == "question"]
    feedback = [r for r in rows if r["type"] == "feedback"]
    asked = {q["trace_id"]: ts(q) for q in questions}
    confirmed_traces = {f["trace_id"] for f in feedback if f.get("verdict") == "confirm"}
    escalated = {r["trace_id"] for r in requests if dt.datetime.fromisoformat(r["created_at"]) >= since}
    to_verdict = [
        (ts(f) - asked[f["trace_id"]]).total_seconds() for f in feedback
        if f.get("verdict") == "confirm" and f["trace_id"] in asked
    ]
    latencies = [q["duration_ms"] for q in questions if q.get("duration_ms") is not None]
    with_answer = [q for q in questions if q.get("status") == "ok"]
    gaps = [q for q in with_answer if (q.get("confidence") or 0) < 0.6]
    per_day: dict[str, dict] = defaultdict(lambda: {"questions": 0, "users": set(), "confirmed": 0})
    for q in questions:
        day = ts(q).date().isoformat()
        per_day[day]["questions"] += 1
        per_day[day]["users"].add(q["user_id"])
        per_day[day]["confirmed"] += q["trace_id"] in confirmed_traces
    databases: Counter = Counter()
    for q in questions:
        databases.update(q.get("databases") or [])
    n = len(questions)
    return {
        "days": days,
        "questions": n,
        "active_users": len({q["user_id"] for q in questions}),
        "confirmed_rate": len(confirmed_traces & set(asked)) / n if n else None,
        "rejections": sum(f.get("verdict") == "reject" for f in feedback),
        "escalations": len(escalated),
        "resolved_without_escalation": (n - len(escalated & set(asked))) / n if n else None,
        "gap_rate": len(gaps) / len(with_answer) if with_answer else None,
        "time_to_confirm_s": {"p50": percentile(to_verdict, 0.5), "p95": percentile(to_verdict, 0.95)},
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)},
        "status": dict(Counter(q.get("status") for q in questions)),
        "per_day": [
            {"day": d, "questions": v["questions"], "users": len(v["users"]), "confirmed": v["confirmed"]}
            for d, v in sorted(per_day.items())
        ],
        "top_databases": databases.most_common(8),
        "requests_open": sum(r["status"] == "open" for r in requests),
    }
