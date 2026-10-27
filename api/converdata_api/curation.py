"""Curación y captura del conocimiento (F24) sobre archivos del directorio de datos.

- Solicitudes escaladas ("Preguntar al responsable"): `curation/requests.json`. La notificación lleva solo el dominio y el
  enlace a la vista Curación, nunca el texto de la pregunta (OP-04 CA7).
- Ediciones humanas de descripciones: en el YAML del catálogo con `description_source: human` y `reviewed: true`; el
  CatalogBuildFlow nunca las sobrescribe en un refresco (F24 CA3, `merge_existing`).
- Reglas de negocio curadas: `knowledge/rules/curadas.yaml` (HU-28).
- Golden discovery de responsables: `knowledge/golden/confirmaciones_usuarios.yaml`, con `confirmed_by: steward` (F24 CA1, CA2).
- Responsables (`steward`) por login SQL y dominio: `curation/stewards.yaml` (OP-04: en su defecto, logins SQL).

On-premise estas piezas viven en los esquemas `curation` y `knowledge` de la BD `ConverData` (OP-02); la API no cambia.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import urllib.request
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from converdata.builder.catalog_builder import object_path
from converdata.catalog.ids import table_key
from converdata.models.knowledge import BusinessRule

log = logging.getLogger(__name__)
CURATED_RULES = "curadas.yaml"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class CurationStore:
    def __init__(self, curation_dir: Path, data_root: Path, notify_webhook: str | None = None, public_url: str = ""):
        self.dir = Path(curation_dir)
        self.data_root = Path(data_root)
        self.notify_webhook = notify_webhook
        self.public_url = public_url.rstrip("/")
        self._lock = threading.RLock()

    # --- responsables -------------------------------------------------------------------------------
    def stewards(self) -> list[dict]:
        path = self.dir / "stewards.yaml"
        if not path.is_file():
            return []
        return [{"login": str(s["login"]).lower(), "domains": list(s.get("domains") or ["*"])}
                for s in (yaml.safe_load(path.read_text(encoding="utf-8")) or [])]

    def save_stewards(self, items: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        clean = [{"login": i["login"].strip().lower(), "domains": i.get("domains") or ["*"]} for i in items if i["login"].strip()]
        (self.dir / "stewards.yaml").write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def steward_domains(self, login: str) -> list[str] | None:
        """Dominios de un responsable (`["*"]` = todos); None si no es responsable."""
        for s in self.stewards():
            if s["login"] == login.lower():
                return s["domains"]
        return None

    # --- solicitudes escaladas (F24 §Escalamiento) ---------------------------------------------------
    def _requests_path(self) -> Path:
        return self.dir / "requests.json"

    def requests(self) -> list[dict]:
        path = self._requests_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def _save_requests(self, items: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._requests_path().write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def create_request(self, user_id: str, trace_id: str, question: str, domain: str, shown: list[str],
                       note: str | None) -> dict:
        with self._lock:
            items = self.requests()
            existing = next((r for r in items if r["trace_id"] == trace_id and r["user_id"] == user_id), None)
            if existing:
                return existing
            req = {
                "id": uuid.uuid4().hex[:10], "created_at": _now(), "status": "open", "user_id": user_id, "trace_id": trace_id,
                "question": question, "domain": domain, "shown": shown, "note": (note or "")[:500] or None, "answer": None,
            }
            items.append(req)
            self._save_requests(items)
        self._notify(domain)
        return req

    def append_requests(self, new: list[dict]) -> None:
        """Agrega solicitudes ya formadas sin notificar (historial simulado del modo demo)."""
        if not new:
            return
        with self._lock:
            self._save_requests(self.requests() + new)

    def answer_request(self, request_id: str, by: str, kind: str, asset_key: str | None, note: str | None) -> dict:
        with self._lock:
            items = self.requests()
            req = next((r for r in items if r["id"] == request_id), None)
            if req is None:
                raise KeyError(request_id)
            req["status"] = "answered" if kind == "asset" else "no_source"
            req["answer"] = {"by": by, "at": _now(), "kind": kind, "asset_key": asset_key, "note": (note or "")[:1000] or None}
            self._save_requests(items)
            return req

    def _notify(self, domain: str) -> None:
        """Webhook (Teams u otro) con el dominio y el enlace; el texto de la pregunta se lee dentro de la aplicación."""
        if not self.notify_webhook:
            return
        body = json.dumps({"text": f"ConverData: nueva duda escalada en el dominio «{domain}». Revísala en {self.public_url}/curacion"})

        def send():
            try:
                req = urllib.request.Request(self.notify_webhook, data=body.encode("utf-8"),
                                             headers={"content-type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10).close()
            except Exception as exc:  # la solicitud ya quedó guardada; solo se pierde el aviso
                log.warning("no se pudo notificar la solicitud: %s", type(exc).__name__)

        threading.Thread(target=send, daemon=True).start()

    # --- ediciones humanas del catálogo (F24 §Revisión del catálogo) ---------------------------------
    def set_description(self, catalog, asset_key: str, description: str, synonyms: list[str] | None) -> int:
        """Escribe la descripción en todas las copias físicas del activo (tabla o columna). Devuelve las copias editadas."""
        parts = asset_key.split(".")
        column = ".".join(parts[3:]) if len(parts) > 3 else None
        edited = 0
        with self._lock:
            for obj in catalog.copies(table_key(asset_key)):
                path = object_path(self.data_root, obj)
                if not path.is_file():
                    continue
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                target = data
                if column:
                    target = next((c for c in data.get("columns", []) if c["name"].lower() == column.lower()), None)
                    if target is None:
                        continue
                target["description"] = description.strip()
                target["description_source"] = "human"
                target["reviewed"] = True
                if synonyms is not None:
                    target["synonyms"] = list(dict.fromkeys(s.strip() for s in synonyms if s.strip()))[:12]
                path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
                edited += 1
        return edited

    # --- reglas de negocio curadas (HU-28) ----------------------------------------------------------
    def _rules_path(self) -> Path:
        return self.data_root / "knowledge" / "rules" / CURATED_RULES

    def curated_rules(self) -> list[BusinessRule]:
        path = self._rules_path()
        if not path.is_file():
            return []
        return [BusinessRule.model_validate(r) for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or [])]

    def upsert_rule(self, rule: BusinessRule) -> None:
        with self._lock:
            rules = [r for r in self.curated_rules() if r.id != rule.id] + [rule]
            path = self._rules_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump([r.model_dump(exclude_none=True) for r in rules], allow_unicode=True,
                                           sort_keys=False), encoding="utf-8")

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock:
            rules = self.curated_rules()
            kept = [r for r in rules if r.id != rule_id]
            if len(kept) == len(rules):
                return False
            self._rules_path().write_text(yaml.safe_dump([r.model_dump(exclude_none=True) for r in kept],
                                                         allow_unicode=True, sort_keys=False), encoding="utf-8")
            return True


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
