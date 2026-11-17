"""`SqlServerCurationRepository`: el estado de la curación en el esquema `curation` de la BD `ConverData` (OP-02).

Responsables por login, dudas escaladas y votos (puerto `CurationRepository`). Las preguntas de
las dudas son D2: este esquema no lo lee el Builder ni se exporta.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Callable


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _iso(value: dt.datetime) -> str:
    return value.replace(tzinfo=dt.timezone.utc).isoformat(timespec="seconds")


def _naive_utc(text: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(text)
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None) if value.tzinfo else value


REQUEST_COLUMNS = ("request_id, created_at, status, user_id, trace_id, question, domain, shown_json, note, simulated, "
                   "answer_json")


def _request(row) -> dict:
    rid, created, status, user_id, trace_id, question, domain, shown, note, simulated, answer = row
    out = {"id": rid, "created_at": _iso(created), "status": status, "user_id": user_id, "trace_id": trace_id,
           "question": question, "domain": domain, "shown": json.loads(shown), "note": note,
           "answer": json.loads(answer) if answer else None}
    if simulated:
        out["simulated"] = True
    return out


class SqlServerCurationRepository:
    def __init__(self, connect: Callable[[], object]):
        self._connect = connect

    def _run(self, work):
        """Ejecuta `work(cursor)` en una transacción."""
        conn = self._connect()
        try:
            conn.autocommit = False
            result = work(conn.cursor())
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- responsables ------------------------------------------------------------------------------
    def stewards(self) -> list[dict]:
        def work(cur):
            cur.execute("SELECT login, domains_json FROM curation.steward ORDER BY login")
            return [{"login": login, "domains": json.loads(domains)} for login, domains in cur.fetchall()]

        return self._run(work)

    def save_stewards(self, items: list[dict], *, by: str) -> None:
        wanted = {i["login"]: _j(i["domains"]) for i in items}

        def work(cur):
            cur.execute("SELECT login, domains_json FROM curation.steward WITH (UPDLOCK, HOLDLOCK)")
            current = dict(cur.fetchall())
            for login in current.keys() - wanted.keys():
                cur.execute("DELETE FROM curation.steward WHERE login = ?", login)
            for login, domains in wanted.items():
                if login not in current:
                    cur.execute("INSERT INTO curation.steward (login, domains_json, modified_by) VALUES (?, ?, ?)",
                                login, domains, by[:128])
                elif current[login] != domains:
                    cur.execute("UPDATE curation.steward SET domains_json = ?, modified_by = ? WHERE login = ?",
                                domains, by[:128], login)

        self._run(work)

    # --- dudas escaladas ---------------------------------------------------------------------------
    def requests(self) -> list[dict]:
        def work(cur):
            cur.execute(f"SELECT {REQUEST_COLUMNS} FROM curation.request ORDER BY seq")
            return [_request(row) for row in cur.fetchall()]

        return self._run(work)

    def add_requests(self, items: list[dict]) -> list[dict]:
        def work(cur):
            out = []
            for r in items:
                cur.execute(
                    "INSERT INTO curation.request (request_id, created_at, status, user_id, trace_id, question, domain, "
                    "shown_json, note, simulated, answer_json) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM curation.request WITH (UPDLOCK, HOLDLOCK) WHERE trace_id = ? AND user_id = ?)",
                    r["id"], _naive_utc(r["created_at"]), r["status"], r["user_id"], r["trace_id"], r["question"][:2000],
                    r["domain"], _j(r.get("shown") or []), r.get("note"), int(bool(r.get("simulated"))),
                    _j(r["answer"]) if r.get("answer") else None, r["trace_id"], r["user_id"])
                cur.execute(f"SELECT {REQUEST_COLUMNS} FROM curation.request WHERE trace_id = ? AND user_id = ?",
                            r["trace_id"], r["user_id"])
                out.append(_request(cur.fetchone()))
            return out

        return self._run(work)

    def answer_request(self, request_id: str, status: str, answer: dict) -> dict:
        def work(cur):
            cur.execute("UPDATE curation.request SET status = ?, answer_json = ? WHERE request_id = ?",
                        status, _j(answer), request_id)
            if cur.rowcount == 0:
                raise KeyError(request_id)
            cur.execute(f"SELECT {REQUEST_COLUMNS} FROM curation.request WHERE request_id = ?", request_id)
            return _request(cur.fetchone())

        return self._run(work)

    # --- votos -------------------------------------------------------------------------------------
    def add_vote(self, vote: dict) -> dict[str, str]:
        def work(cur):
            # El bloqueo de aplicación ordena los votos de una misma pareja: el recuento incluye siempre el propio.
            cur.execute("DECLARE @rc int; EXEC @rc = sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
                        "@LockOwner = 'Transaction', @LockTimeout = 15000; SELECT @rc", f"converdata_vote:{vote['golden_id']}")
            if cur.fetchone()[0] < 0:
                raise TimeoutError("No se pudo registrar el voto: hay otro en curso para la misma respuesta")
            cur.execute("INSERT INTO curation.vote (golden_id, user_id, trace_id, asset_key, verdict, steward) "
                        "VALUES (?, ?, ?, ?, ?, ?)", vote["golden_id"], vote["user_id"], vote["trace_id"],
                        vote["asset_key"], vote["verdict"], int(bool(vote.get("steward"))))
            cur.execute("SELECT user_id, verdict FROM curation.vote WHERE golden_id = ? ORDER BY id", vote["golden_id"])
            return {user_id: verdict for user_id, verdict in cur.fetchall()}  # el último de cada usuario gana

        return self._run(work)
