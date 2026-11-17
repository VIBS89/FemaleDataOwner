"""Auditoría base (F11) en archivos JSONL diarios: preguntas con sus pasos y candidatos, y eventos de la API.

Es el `AuditSink` del DiscoverFlow, así que hereda su comportamiento fail-closed. Nunca registra contraseñas.
Es el destino de desarrollo: con `CONVERDATA_DB` definida la API usa `converdata.audit.sqlserver.SqlServerAuditSink`
(esquema `audit` de la BD `ConverData`, OP-05), que tiene la misma interfaz. `open_audit` elige uno u otro.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from collections import deque
from pathlib import Path

from converdata.audit.chain import GENESIS, ChainReport, last_hash, normalize, previous_file, seal, verify_directory
from converdata.audit.recorder import TraceRecord, question_row  # noqa: F401  (reexportado)


def _iso(when: dt.datetime | None = None) -> str:
    return (when or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="milliseconds")


class FileAuditSink:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._tails: dict[str, str] = {}  # archivo → hash de su última fila (este proceso es el único que escribe)

    def append(self, row: dict, when: dt.datetime | None = None) -> None:
        """Escribe en el archivo del día de `when` (por defecto hoy, en UTC), encadenada con la fila anterior
        (`converdata.audit.chain`). Las filas de hoy se sincronizan a disco antes de devolver: si la respuesta salió,
        su registro existe."""
        self.directory.mkdir(parents=True, exist_ok=True)
        day = (when or dt.datetime.now(dt.timezone.utc)).date().isoformat()
        path = self.directory / f"audit-{day}.jsonl"
        row = normalize(row)
        with self._lock:
            prev = self._tails.get(path.name) or last_hash(path)
            if prev is None:  # primera fila encadenada del archivo: enlaza con el día anterior
                prev = GENESIS
                earlier = previous_file(path)
                earlier_hash = last_hash(earlier) if earlier else None
                if earlier_hash:
                    row = {**row, "prev_file": {"name": earlier.name, "hash": earlier_hash}}
            sealed = seal(row, prev)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(sealed, ensure_ascii=False) + "\n")
                if when is None:  # lo sembrado en el modo demo (con fecha) no necesita durabilidad
                    fh.flush()
                    os.fsync(fh.fileno())
            self._tails[path.name] = sealed["hash"]

    def verify(self) -> ChainReport:
        with self._lock:
            return verify_directory(self.directory)

    def write(self, record: TraceRecord) -> None:
        self.append(question_row(record))

    def event(self, kind: str, user_id: str | None, **data) -> None:
        self.append({"ts": _iso(), "type": kind, "user_id": user_id, **data})

    def recent(self, limit: int = 100, user_id: str | None = None, kind: str | None = None, days: int = 7) -> list[dict]:
        """Últimos registros, del más reciente al más antiguo, de los archivos de los últimos `days` días."""
        out: deque[dict] = deque(maxlen=limit)
        files = sorted(self.directory.glob("audit-*.jsonl"))[-max(1, days):] if self.directory.exists() else []
        for path in files:
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (user_id is None or row.get("user_id") == user_id) and (kind is None or row.get("type") == kind):
                    rows.append(row)
            out.extend(sorted(rows, key=lambda r: r.get("ts", "")))  # lo sembrado se escribe fuera de orden
        return list(reversed(out))


def open_audit(settings):
    """Destino de la auditoría según la configuración: la BD `ConverData` si `CONVERDATA_DB` está definida; si no, archivos."""
    if settings.db:
        from converdata.audit.sqlserver import SqlServerAuditSink
        from converdata.storage.connection import connector

        return SqlServerAuditSink(connector(settings.db))
    return FileAuditSink(settings.audit_dir)
