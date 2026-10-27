"""`SqlServerAuditSink`: auditoría de F11 en el esquema `audit` de la BD ConverData (OP-05).

Una pregunta se escribe en **una sola transacción** (`audit_question`, `audit_step`, `audit_discovery`); si algo falla
se hace rollback y se relanza la excepción, y el DiscoverFlow no entrega la respuesta (fail-closed). La cuenta del
servicio solo tiene `INSERT` en `audit` (db/converdata/001_esquemas.sql). Nunca recibe credenciales.
"""

from __future__ import annotations

import json
from typing import Callable

from converdata.audit.recorder import FeedbackRecord, TraceRecord, discovery_rows

CLIENTS = {"ui", "api", "mcp", "cli"}  # CHECK de audit_question.client

INSERT_QUESTION = """INSERT INTO audit.audit_question
    (trace_id, user_id, client, flow, question, intent, databases_json, status, confidence, total_ms)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
INSERT_STEP = """INSERT INTO audit.audit_step
    (trace_id, step, attempt, started_at, duration_ms, model, ok, error, detail)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
INSERT_DISCOVERY = """INSERT INTO audit.audit_discovery
    (trace_id, rank, asset_key, environment, confidence, description_source, kind)
VALUES (?, ?, ?, ?, ?, ?, ?)"""
INSERT_FEEDBACK = """INSERT INTO audit.audit_discovery_feedback
    (trace_id, asset_key, verdict, correct_asset_key, actor_role, time_to_verdict_ms)
VALUES (?, ?, ?, ?, ?, ?)"""


def _cut(text: str | None, limit: int) -> str | None:
    return text[:limit] if text else text


class SqlServerAuditSink:
    def __init__(self, connect: Callable[[], object]):
        self._connect = connect  # conexión a la BD ConverData con la gMSA del servicio

    def write(self, record: TraceRecord) -> None:
        env = record.envelope
        client = record.client if record.client in CLIENTS else "api"
        rows = [(
            INSERT_QUESTION,
            (record.trace_id, record.user_id, client, env.flow, _cut(record.question, 2000), record.intent,
             json.dumps(env.databases), env.status, env.confidence, env.timings_ms.get("total")),
        )]
        rows += [
            (INSERT_STEP, (record.trace_id, s.step, s.attempt, s.started_at, s.duration_ms, s.model, int(s.ok),
                           _cut(s.error, 400), _cut(s.detail, 200)))
            for s in record.steps
        ]
        rows += [
            (INSERT_DISCOVERY, (record.trace_id, r["rank"], r["asset_key"], r["environment"], r["confidence"],
                                r["description_source"], r["kind"]))
            for r in discovery_rows(env)
        ]
        self._transaction(rows)

    def write_feedback(self, fb: FeedbackRecord) -> None:
        self._transaction([(INSERT_FEEDBACK, (fb.trace_id, fb.asset_key, fb.verdict, fb.correct_asset_key,
                                              fb.actor_role, fb.time_to_verdict_ms))])

    def _transaction(self, rows: list[tuple[str, tuple]]) -> None:
        conn = self._connect()
        try:
            conn.autocommit = False
            cur = conn.cursor()
            for sql, params in rows:
                cur.execute(sql, *params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
