"""Registro de auditoría del DiscoverFlow (F11): `audit_question`, `audit_step` y `audit_discovery`.

La auditoría es fail-closed: si no se puede escribir, la respuesta no se entrega (salvo `audit.fail_open` en dev).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol

from discovery_data_agent.models.discovery import AnswerEnvelope


@dataclass
class StepRecord:
    trace_id: str
    step: str
    attempt: int
    started_at: dt.datetime
    duration_ms: int
    model: str | None = None
    ok: bool = True
    error: str | None = None
    detail: str | None = None  # decisión del paso sin ser error (p. ej. "cascada:sin_llm", "calidad:pobre→reintento")


@dataclass
class TraceRecord:
    """Todo lo que deja una pregunta; se escribe en una sola transacción al final."""

    trace_id: str
    user_id: str
    client: str
    question: str  # D2: solo vive en la auditoría on-premise (F17)
    envelope: AnswerEnvelope
    intent: str | None
    steps: list[StepRecord] = field(default_factory=list)


VERDICTS = {"confirm", "reject", "correct_is"}
ACTOR_ROLES = {"consumer", "steward"}


@dataclass(frozen=True)
class FeedbackRecord:
    """Fila de `audit_discovery_feedback`: un ✔/✖ sobre un activo mostrado en una respuesta (F11, F24)."""

    trace_id: str
    asset_key: str
    verdict: str  # confirm | reject | correct_is
    actor_role: str  # consumer | steward
    correct_asset_key: str | None = None
    time_to_verdict_ms: int | None = None

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"veredicto inválido: {self.verdict!r}")
        if self.actor_role not in ACTOR_ROLES:
            raise ValueError(f"rol inválido: {self.actor_role!r}")
        if (self.verdict == "correct_is") != bool(self.correct_asset_key):
            raise ValueError("correct_is exige correct_asset_key, y solo él")


class AuditSink(Protocol):
    def write(self, record: TraceRecord) -> None: ...


class InMemoryAuditSink:
    def __init__(self):
        self.records: list[TraceRecord] = []

    def write(self, record: TraceRecord) -> None:
        self.records.append(record)

    def discovery_rows(self, trace_id: str) -> list[dict]:
        """Filas de `audit_discovery`: una por candidato, alternativa y relación mostrados (F11-CA5)."""
        rec = next(r for r in self.records if r.trace_id == trace_id)
        return discovery_rows(rec.envelope)


def discovery_rows(envelope: AnswerEnvelope) -> list[dict]:
    disc = envelope.discovery
    if disc is None:
        return []
    rows = [
        {
            "rank": c.rank,
            "asset_key": c.asset_key,
            "environment": c.locations[0].environment if c.locations else None,
            "confidence": c.confidence,
            "description_source": c.description_source,
            "kind": "candidate",
        }
        for c in disc.candidates
    ]
    rows += [
        {"rank": None, "asset_key": a.asset_key, "environment": None, "confidence": a.confidence,
         "description_source": None, "kind": "alternative"}
        for a in disc.alternatives
    ]
    rows += [
        {"rank": None, "asset_key": f"{r.from_}->{r.to}", "environment": None, "confidence": None,
         "description_source": None, "kind": "related"}
        for r in disc.related
    ]
    return rows


def question_row(record: TraceRecord, when: dt.datetime | None = None) -> dict:
    """Forma común de una pregunta auditada: la escriben igual el destino en archivos y el de SQL Server, y es lo que
    leen Administración, el historial propio y las métricas."""
    env = record.envelope
    moment = when or dt.datetime.now(dt.timezone.utc)
    return {
        "ts": moment.isoformat(timespec="milliseconds"),
        "type": "question",
        "trace_id": record.trace_id,
        "user_id": record.user_id,
        "client": record.client,
        "question": record.question,
        "flow": env.flow,  # "ask" si se calculó una cifra sobre datos
        "intent": record.intent,
        "status": env.status,
        "confidence": env.confidence,
        "databases": env.databases,
        "duration_ms": env.timings_ms.get("total"),
        "steps": [
            {"step": s.step, "attempt": s.attempt, "started_at": s.started_at.isoformat(timespec="milliseconds"),
             "duration_ms": s.duration_ms, "model": s.model, "ok": s.ok, "error": s.error, "detail": s.detail}
            for s in record.steps
        ],
        "discovery": discovery_rows(env),
    }
