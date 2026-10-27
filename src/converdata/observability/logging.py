"""Logs JSON con la lista blanca D5 de F17 (OP-05 §Observabilidad).

- Cada línea es un evento con nombre fijo (`discover.done`, `audit.write_failed`…) y solo campos D5. Lo que no está en
  la lista blanca se descarta, en particular `question`, `sql`, `rows`, `prompt` y `completion`.
- Los argumentos del mensaje no se interpolan y de las excepciones solo queda el tipo: su texto puede llevar SQL o valores.
- Errores y arranques o paradas también van al **Visor de eventos de Windows** (origen `ConverData`).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from logging.handlers import NTEventLogHandler, RotatingFileHandler
from pathlib import Path

D5_FIELDS = frozenset({
    "trace_id", "step", "attempt", "duration_ms", "status", "http_status", "route", "method", "client", "model",
    "role", "tokens_in", "tokens_out", "tables", "databases", "server_id", "count", "error_type", "error_code",
    "version", "environment", "job", "files", "seconds",
})
EVENT_SOURCE = "ConverData"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": str(record.msg),  # sin interpolar `args`
        }
        for key in D5_FIELDS:
            if key in record.__dict__:
                line[key] = record.__dict__[key]
        if record.exc_info and record.exc_info[0] is not None:
            line["error_type"] = record.exc_info[0].__name__
        return json.dumps(line, ensure_ascii=False, default=str)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Registra un evento con solo los campos D5; el resto se descarta antes de llegar a cualquier handler."""
    logger.log(level, event, extra={k: v for k, v in fields.items() if k in D5_FIELDS})


def configure_logging(
    log_dir: str | Path, *, level: int = logging.INFO, event_log: bool = True, logger_name: str = "converdata",
    max_bytes: int = 20 * 1024 * 1024, backups: int = 10,
) -> logging.Logger:
    """Archivo JSON rotado en `log_dir` y, en Windows, el Visor de eventos para errores."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    file_handler = RotatingFileHandler(log_dir / "converdata.log", maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)
    if event_log and sys.platform == "win32":
        try:
            nt = NTEventLogHandler(EVENT_SOURCE)
        except Exception:  # sin pywin32 o sin permiso para registrar el origen: solo archivo
            nt = None
        if nt is not None:
            nt.setLevel(logging.ERROR)
            nt.setFormatter(JsonFormatter())
            logger.addHandler(nt)
    return logger
