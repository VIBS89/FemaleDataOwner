"""`SqlServerAuditSink`: auditoría de F11 en el esquema `audit` de la BD ConverData (OP-05, HU-20).

- Una pregunta se escribe en **una sola transacción** (`audit_question`, `audit_step`, `audit_discovery`); si algo falla
  se hace rollback y se relanza la excepción, y el DiscoverFlow no entrega la respuesta (fail-closed).
- Los eventos de la API (inicios de sesión, accesos denegados, cambios de curación e inventario) van a `audit_event`; como
  se escriben antes de aplicar el cambio, si la BD no responde el cambio no ocurre.
- La cuenta del servicio pertenece a `converdata_app`: inserta y lee en `audit`, pero no puede modificar ni borrar
  (db/converdata/001_esquemas.sql). `verify()` comprueba ese permiso, que es el control equivalente a la cadena de hashes
  de la auditoría en archivos.

Nunca recibe credenciales. Tiene la misma interfaz que `converdata_api.audit.FileAuditSink`, así la API no cambia.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Callable

from converdata.audit.chain import ChainReport, FileCheck
from converdata.audit.recorder import FeedbackRecord, TraceRecord, question_row

CLIENTS = {"ui", "web", "api", "mcp", "cli", "demo-seed"}  # lo demás se registra como "api"
QUESTION_FIELDS = {"ts", "type", "trace_id", "user_id", "client", "question", "intent", "status", "confidence",
                   "databases", "duration_ms", "steps", "discovery", "flow"}

INSERT_QUESTION = """INSERT INTO audit.audit_question
    (trace_id, user_id, client, flow, question, intent, databases_json, status, confidence, total_ms, ts)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, SYSUTCDATETIME()))"""
INSERT_STEP = """INSERT INTO audit.audit_step
    (trace_id, step, attempt, started_at, duration_ms, model, ok, error, detail)
VALUES (?, ?, ?, COALESCE(?, SYSUTCDATETIME()), ?, ?, ?, ?, ?)"""
INSERT_DISCOVERY = """INSERT INTO audit.audit_discovery
    (trace_id, rank, asset_key, environment, confidence, description_source, kind)
VALUES (?, ?, ?, ?, ?, ?, ?)"""
INSERT_FEEDBACK = """INSERT INTO audit.audit_discovery_feedback
    (trace_id, asset_key, verdict, correct_asset_key, actor_role, time_to_verdict_ms, user_id, ts)
VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, SYSUTCDATETIME()))"""
INSERT_EVENT = """INSERT INTO audit.audit_event (kind, user_id, trace_id, data_json, ts)
VALUES (?, ?, ?, ?, COALESCE(?, SYSUTCDATETIME()))"""

# Lo que la cuenta de la API no debe poder hacer (comprobado por `verify`), a nivel de esquema y de cada tabla de `audit`.
FORBIDDEN = [("UPDATE", "modificar"), ("DELETE", "borrar"), ("ALTER", "alterar")]
VERIFY_PERMISSIONS = """
SELECT 'audit' AS target, p.name AS permission
FROM (VALUES ('UPDATE'), ('DELETE'), ('ALTER')) AS p(name)
WHERE HAS_PERMS_BY_NAME('audit', 'SCHEMA', p.name) = 1
UNION ALL
SELECT 'audit.' + o.name, p.name
FROM sys.objects o CROSS JOIN (VALUES ('UPDATE'), ('DELETE'), ('ALTER')) AS p(name)
WHERE o.schema_id = SCHEMA_ID('audit') AND o.type = 'U'
  AND HAS_PERMS_BY_NAME('audit.' + QUOTENAME(o.name), 'OBJECT', p.name) = 1
UNION ALL
SELECT 'audit.usp_purge', 'EXECUTE' WHERE HAS_PERMS_BY_NAME('audit.usp_purge', 'OBJECT', 'EXECUTE') = 1
UNION ALL
SELECT s.name, 'ALTER' FROM (VALUES ('catalog'), ('knowledge')) AS s(name)
WHERE HAS_PERMS_BY_NAME(s.name, 'SCHEMA', 'ALTER') = 1
"""


def _cut(text: str | None, limit: int) -> str | None:
    return text[:limit] if text else text


def _guid(value) -> str | None:
    """`trace_id` como GUID canónico, o None si no lo es (un cliente puede enviar cualquier texto)."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _moment(value) -> dt.datetime | None:
    """Instante en UTC sin zona (lo que guarda `datetime2`), desde un datetime o un texto ISO."""
    if value is None:
        return None
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value)
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def _iso(value: dt.datetime) -> str:
    return value.replace(tzinfo=dt.timezone.utc).isoformat(timespec="milliseconds")


class SqlServerAuditSink:
    def __init__(self, connect: Callable[[], object]):
        self._connect = connect  # conexión a la BD ConverData con la cuenta del servicio (gMSA)

    # --- escritura ---------------------------------------------------------------------------------
    def write(self, record: TraceRecord) -> None:
        self._transaction(self._question_statements(question_row(record), None))

    def write_feedback(self, fb: FeedbackRecord, user_id: str | None = None, when: dt.datetime | None = None) -> None:
        self._transaction([self._feedback_statement(fb, user_id, when)])

    def event(self, kind: str, user_id: str | None, **data) -> None:
        self.append({"type": kind, "user_id": user_id, **data})

    def append(self, row: dict, when: dt.datetime | None = None) -> None:
        """Escribe una fila con la forma de la auditoría en archivos (pregunta o evento). `when` fecha lo sembrado
        por el modo demo; sin él, la hora la pone SQL Server."""
        ts = _moment(when)
        if row.get("type") == "question":
            self._transaction(self._question_statements(row, ts))
            return
        self._transaction(self._event_statements(row, ts))

    def _question_statements(self, row: dict, ts: dt.datetime | None) -> list[tuple[str, tuple]]:
        trace_id = row["trace_id"]
        client = row.get("client") if row.get("client") in CLIENTS else "api"
        statements = [(
            INSERT_QUESTION,
            (trace_id, row["user_id"], client, row.get("flow") or "discover", _cut(row["question"], 2000),
             _cut(row.get("intent"), 30), json.dumps(row.get("databases") or []), row["status"], row.get("confidence"),
             row.get("duration_ms"), ts),
        )]
        statements += [
            (INSERT_STEP, (trace_id, _cut(s["step"], 20), s["attempt"], _moment(s.get("started_at")), s["duration_ms"],
                           _cut(s.get("model"), 200), int(bool(s["ok"])), _cut(s.get("error"), 400),
                           _cut(s.get("detail"), 200)))
            for s in row.get("steps") or []
        ]
        statements += [
            (INSERT_DISCOVERY, (trace_id, d["rank"], _cut(d["asset_key"], 850), d["environment"], d["confidence"],
                                d["description_source"], d["kind"]))
            for d in row.get("discovery") or []
        ]
        extra = {k: v for k, v in row.items() if k not in QUESTION_FIELDS}
        if extra:  # p. ej. `simulated` en lo sembrado por el modo demo
            statements.append((INSERT_EVENT, ("question_note", row["user_id"], trace_id, self._json(extra), ts)))
        return statements

    def _event_statements(self, row: dict, ts: dt.datetime | None) -> list[tuple[str, tuple]]:
        data = {k: v for k, v in row.items() if k not in ("type", "user_id", "ts")}
        trace_id = _guid(data.get("trace_id")) if data.get("trace_id") is not None else None
        if trace_id is not None:
            data.pop("trace_id")
        kind = _cut(str(row.get("type") or "event"), 60)
        statements = [(INSERT_EVENT, (kind, _cut(row.get("user_id"), 128), trace_id, self._json(data), ts))]
        if kind == "feedback" and trace_id and data.get("verdict") in ("confirm", "reject"):
            fb = FeedbackRecord(trace_id=trace_id, asset_key=data["asset_key"], verdict=data["verdict"],
                                actor_role="steward" if data.get("steward") else "consumer",
                                time_to_verdict_ms=data.get("time_to_verdict_ms"))
            statements.append(self._feedback_statement(fb, row.get("user_id"), ts))
        return statements

    @staticmethod
    def _feedback_statement(fb: FeedbackRecord, user_id: str | None, ts) -> tuple[str, tuple]:
        return (INSERT_FEEDBACK, (fb.trace_id, _cut(fb.asset_key, 400), fb.verdict, fb.correct_asset_key,
                                  fb.actor_role, fb.time_to_verdict_ms, _cut(user_id, 128), _moment(ts)))

    @staticmethod
    def _json(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

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

    # --- lectura (Administración, historial propio, métricas) ---------------------------------------
    def recent(self, limit: int = 100, user_id: str | None = None, kind: str | None = None, days: int = 7) -> list[dict]:
        """Últimos registros, del más reciente al más antiguo, de los últimos `days` días."""
        limit = max(1, int(limit))
        since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=max(1, days))
        conn = self._connect()
        try:
            cur = conn.cursor()
            rows: list[dict] = []
            if kind in (None, "question"):
                rows += self._questions(cur, limit, since, user_id)
            if kind != "question":
                rows += self._events(cur, limit, since, user_id, kind)
            rows.sort(key=lambda r: r["ts"], reverse=True)
            rows = rows[:limit]
            self._attach_details(cur, [r for r in rows if r["type"] == "question"])
            return rows
        finally:
            conn.close()

    @staticmethod
    def _questions(cur, limit: int, since, user_id: str | None) -> list[dict]:
        sql = ("SELECT TOP (?) ts, trace_id, user_id, client, question, intent, status, confidence, databases_json, "
               "total_ms FROM audit.audit_question WHERE ts >= ?")
        params: list = [limit, since]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        cur.execute(sql + " ORDER BY ts DESC", *params)
        return [
            {"ts": _iso(ts), "type": "question", "trace_id": str(trace_id).lower(), "user_id": user, "client": client,
             "question": question, "intent": intent, "status": status, "confidence": confidence,
             "databases": json.loads(databases or "[]"), "duration_ms": total_ms, "steps": [], "discovery": []}
            for ts, trace_id, user, client, question, intent, status, confidence, databases, total_ms in cur.fetchall()
            # La colación de la BD puede no distinguir mayúsculas ni tildes: cada usuario ve solo lo suyo, exacto.
            if user_id is None or user == user_id
        ]

    @staticmethod
    def _events(cur, limit: int, since, user_id: str | None, kind: str | None) -> list[dict]:
        sql = "SELECT TOP (?) ts, kind, user_id, trace_id, data_json FROM audit.audit_event WHERE ts >= ?"
        params: list = [limit, since]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        else:
            sql += " AND kind <> 'question_note'"
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        cur.execute(sql + " ORDER BY ts DESC", *params)
        out = []
        for ts, event_kind, user, trace_id, data in cur.fetchall():
            if user_id is not None and user != user_id:
                continue
            row = {"ts": _iso(ts), "type": event_kind, "user_id": user, **json.loads(data or "{}")}
            if trace_id is not None:
                row["trace_id"] = str(trace_id).lower()
            out.append(row)
        return out

    @staticmethod
    def _attach_details(cur, questions: list[dict], chunk: int = 500) -> None:
        by_trace = {q["trace_id"]: q for q in questions}
        ids = list(by_trace)
        for start in range(0, len(ids), chunk):
            part = ids[start:start + chunk]
            marks = ",".join("?" * len(part))
            cur.execute(
                "SELECT trace_id, rank, asset_key, environment, confidence, description_source, kind "
                f"FROM audit.audit_discovery WHERE trace_id IN ({marks}) ORDER BY id", *part)
            for trace_id, rank, asset_key, environment, confidence, source, kind in cur.fetchall():
                by_trace[str(trace_id).lower()]["discovery"].append(
                    {"rank": rank, "asset_key": asset_key, "environment": environment, "confidence": confidence,
                     "description_source": source, "kind": kind})
            cur.execute(
                "SELECT trace_id, step, attempt, duration_ms, model, ok, error, detail "
                f"FROM audit.audit_step WHERE trace_id IN ({marks}) ORDER BY id", *part)
            for trace_id, step, attempt, duration_ms, model, ok, error, detail in cur.fetchall():
                by_trace[str(trace_id).lower()]["steps"].append(
                    {"step": step, "attempt": attempt, "duration_ms": duration_ms, "model": model, "ok": bool(ok),
                     "error": error, "detail": detail})

    # --- integridad --------------------------------------------------------------------------------
    def verify(self) -> ChainReport:
        """La auditoría en SQL Server es íntegra si la cuenta que la escribe no puede modificarla, borrarla ni purgarla,
        ni alterar el historial temporal del catálogo. Se comprueba el esquema y cada tabla, por si alguien concedió un
        permiso a nivel de objeto."""
        check = FileCheck("audit (SQL Server)")
        verbs = dict(FORBIDDEN) | {"EXECUTE": "ejecutar"}
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT (SELECT COUNT_BIG(*) FROM audit.audit_question) + (SELECT COUNT_BIG(*) FROM audit.audit_event)")
            check.rows = int(cur.fetchone()[0])
            cur.execute(VERIFY_PERMISSIONS)
            for target, permission in cur.fetchall():
                what = "la auditoría" if target == "audit" else target
                check.errors.append(f"la cuenta del servicio puede {verbs[permission]} {what}: "
                                    "debe pertenecer solo al rol converdata_app")
        finally:
            conn.close()
        return ChainReport([check])
