"""Historial simulado del modo demo para el tablero de impacto (`/admin/metrics`, pantalla Métricas).

Siembra una sola vez, al terminar el primer build demo con `CONVERDATA_DEMO_HISTORY` activo, `days` días de actividad:
preguntas de los sets de evaluación de los fixtures con respuestas reales del DiscoverFlow, confirmaciones a los
20–90 s, algunos rechazos y dudas escaladas (algunas respondidas).

Todo lleva `client: "demo-seed"` y `simulated: true`, y nada entra al conocimiento (golden ni catálogo), para que nunca
se confunda con un piloto real ni cambie las respuestas de la demo.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import random
import uuid
from pathlib import Path

import yaml

from converdata.audit.recorder import InMemoryAuditSink, TraceRecord
from converdata.flows.discover import DiscoverService
from converdata.models.identity import UserContext

from converdata_api.audit import question_row

HISTORY_MARKER = ".demo_history.json"
SEED_CLIENT = "demo-seed"


def seed_history(service, audit, curation, fixtures: list[Path], *, days: int = 30, users: int = 7, seed: int = 7,
                 now: dt.datetime | None = None) -> dict | None:
    marker = Path(curation.dir) / HISTORY_MARKER
    if marker.exists():
        return None
    questions = eval_questions(fixtures)
    if not questions:
        return None
    rng = random.Random(seed)
    now = now or dt.datetime.now(dt.timezone.utc)
    names = [f"analista{i:02d}" for i in range(1, users + 1)]
    quiet = DiscoverService(dataclasses.replace(service.deps, audit=InMemoryAuditSink()))  # no escribe en la auditoría real
    all_ids = frozenset(o.id for o in service.deps.catalog.objects)
    answers: dict[str, object] = {}
    n_questions = n_feedback = 0
    gaps: list[tuple[dt.datetime, str, dict]] = []
    for back in range(days, 0, -1):
        day = (now - dt.timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        progress = (days - back) / days  # la adopción crece durante el piloto
        active = names[: max(2, round(len(names) * (0.4 + 0.6 * progress)))]
        weekend = day.weekday() >= 5
        count = rng.randint(1, 4) if weekend else rng.randint(8, 12) + round(13 * progress * rng.random())
        for _ in range(count):
            question, user = rng.choice(questions), rng.choice(active)
            if question not in answers:
                answers[question] = quiet.run(question, UserContext(user_id=user, visible_ids=all_ids), client="api")
            env = answers[question]
            when = day + dt.timedelta(hours=rng.randint(8, 17), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
            trace_id = str(uuid.uuid4())
            record = TraceRecord(trace_id=trace_id, user_id=user, client=SEED_CLIENT, question=question, envelope=env,
                                 intent="discovery", steps=[])
            row = question_row(record, when)
            row.update(simulated=True, duration_ms=int(rng.lognormvariate(7.4, 0.35)))  # mediana ≈ 1,6 s con LLM
            audit.append(row, when)
            n_questions += 1
            disc = env.discovery
            if disc and disc.candidates and not disc.knowledge_gap:
                roll = rng.random()
                verdict = "confirm" if roll < 0.8 else "reject" if roll < 0.87 else None
                if verdict:
                    delay = rng.uniform(20, 90)
                    fb_when = when + dt.timedelta(seconds=delay)
                    audit.append({
                        "ts": fb_when.isoformat(timespec="milliseconds"), "type": "feedback", "user_id": user,
                        "trace_id": trace_id, "asset_key": disc.candidates[0].asset_key, "verdict": verdict,
                        "steward": False, "time_to_verdict_ms": int(delay * 1000), "client": SEED_CLIENT,
                        "simulated": True,
                    }, fb_when)
                    n_feedback += 1
            elif disc is not None:
                gaps.append((when, user, {"trace_id": trace_id, "question": question,
                                          "shown": sorted(c.asset_key for c in disc.candidates)}))
    requests = seed_requests(rng, gaps, service)
    curation.append_requests(requests)
    summary = {"days": days, "users": len(names), "questions": n_questions, "feedback": n_feedback,
               "requests": len(requests), "seeded_at": now.isoformat(timespec="seconds")}
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return summary


def eval_questions(fixtures: list[Path]) -> list[str]:
    out: list[str] = []
    for fixture in map(Path, fixtures):
        path = fixture / "eval" / "discovery.yaml"
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out += [c["question"] for c in data.get("cases", []) if c.get("question")]
    return list(dict.fromkeys(out))


def seed_requests(rng: random.Random, gaps: list, service, count: int = 5) -> list[dict]:
    """Dudas escaladas de preguntas con brecha: las 3 primeras respondidas (una sin fuente), el resto abiertas."""
    picked = sorted(rng.sample(gaps, k=min(len(gaps), count)), key=lambda g: g[0]) if gaps else []
    out = []
    for i, (when, user, info) in enumerate(picked):
        domain = next((c.domain for key in info["shown"] for c in service.deps.catalog.copies(key)[:1] if c.domain), None)
        answer, status = None, "open"
        if i < 3:
            kind = "asset" if info["shown"] and i != 1 else "no_source"
            answered_at = when + dt.timedelta(hours=rng.randint(2, 30))
            answer = {"by": "responsable", "at": answered_at.isoformat(timespec="seconds"), "kind": kind,
                      "asset_key": info["shown"][0] if kind == "asset" else None, "note": None}
            status = "answered" if kind == "asset" else "no_source"
        out.append({
            "id": uuid.uuid4().hex[:10], "created_at": when.isoformat(timespec="seconds"), "status": status,
            "user_id": user, "trace_id": info["trace_id"], "question": info["question"],
            "domain": domain or "sin_dominio", "shown": info["shown"], "note": None, "answer": answer,
            "simulated": True,
        })
    return out
