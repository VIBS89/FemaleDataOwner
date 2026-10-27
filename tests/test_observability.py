"""HU-21 y HU-22 · Logs JSON con lista blanca D5, Visor de eventos y contadores sin contenido (F17, OP-05)."""

import json
import logging

import pytest

from converdata.observability.logging import D5_FIELDS, JsonFormatter, configure_logging, log_event
from converdata.observability.metrics import Metrics

SECRET_Q = "¿dónde está el DUI 01234567-8 de Juan?"


def _format(**extra) -> dict:
    record = logging.LogRecord("converdata.test", logging.INFO, __file__, 1, "discover.done", (), None)
    for k, v in extra.items():
        setattr(record, k, v)
    return json.loads(JsonFormatter().format(record))


def test_solo_salen_campos_de_la_lista_blanca():
    line = _format(trace_id="t-1", duration_ms=120, question=SECRET_Q, sql="SELECT 1", rows=[1], prompt="p",
                   completion="c", password="x", user_id="analista")
    assert line["trace_id"] == "t-1" and line["duration_ms"] == 120 and line["event"] == "discover.done"
    for forbidden in ("question", "sql", "rows", "prompt", "completion", "password", "user_id"):
        assert forbidden not in line
    assert SECRET_Q not in json.dumps(line)


def test_las_excepciones_solo_dejan_el_tipo():
    try:
        raise ValueError(f"error en SELECT * FROM Clientes WHERE DUI='{SECRET_Q}'")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "audit.write_failed", (), __import__("sys").exc_info())
    line = json.loads(JsonFormatter().format(record))
    assert line["error_type"] == "ValueError"
    assert "SELECT" not in json.dumps(line) and "DUI" not in json.dumps(line)


def test_los_argumentos_del_mensaje_no_se_interpolan():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "pregunta %s", (SECRET_Q,), None)
    assert SECRET_Q not in JsonFormatter().format(record)


def test_log_event_descarta_campos_fuera_de_d5(caplog):
    logger = logging.getLogger("converdata.test.events")
    with caplog.at_level(logging.INFO, logger="converdata.test.events"):
        log_event(logger, "discover.done", trace_id="t-2", question=SECRET_Q, status="ok")
    [rec] = caplog.records
    assert rec.trace_id == "t-2" and rec.status == "ok" and not hasattr(rec, "question")


def test_lista_blanca_no_incluye_contenido():
    assert not {"question", "sql", "rows", "prompt", "completion", "password", "answer_text"} & D5_FIELDS


def test_configure_logging_escribe_json_rotado(tmp_path):
    root = configure_logging(tmp_path, event_log=False, logger_name="converdata.test.cfg")
    log_event(root, "service.start", status="ok")
    for h in root.handlers:
        h.flush()
    [line] = (tmp_path / "converdata.log").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["event"] == "service.start"
    assert any(type(h).__name__ == "RotatingFileHandler" for h in root.handlers)


def test_visor_de_eventos_solo_en_windows_y_para_errores(tmp_path, monkeypatch):
    created = []

    class FakeNT(logging.Handler):
        def __init__(self, appname):
            super().__init__()
            created.append(appname)

        def emit(self, record):
            pass

    monkeypatch.setattr("converdata.observability.logging.NTEventLogHandler", FakeNT)
    monkeypatch.setattr("converdata.observability.logging.sys.platform", "win32")
    root = configure_logging(tmp_path, event_log=True, logger_name="converdata.test.nt")
    nt = [h for h in root.handlers if isinstance(h, FakeNT)]
    assert created == ["ConverData"] and nt and nt[0].level == logging.ERROR


# --- métricas ------------------------------------------------------------------------------------


def test_metricas_cuentan_y_calculan_percentiles():
    m = Metrics(window=100)
    for ms in range(1, 101):
        m.observe_request("discover", ms, ok=ms % 10 != 0, tokens_in=10, tokens_out=5)
    snap = m.snapshot()
    d = snap["routes"]["discover"]
    assert d["requests"] == 100 and d["errors"] == 10
    assert d["p50_ms"] == pytest.approx(50, abs=1) and d["p95_ms"] == pytest.approx(95, abs=1)
    assert snap["tokens"] == {"in": 1000, "out": 500}


def test_metricas_ventana_acotada_y_sin_contenido():
    m = Metrics(window=10)
    for ms in range(1000):
        m.observe_request("discover", ms, ok=True)
    m.increment("guardrail_blocked")
    snap = m.snapshot()
    assert snap["routes"]["discover"]["p50_ms"] >= 990  # solo las 10 últimas
    assert snap["counters"]["guardrail_blocked"] == 1
    assert set(snap) == {"uptime_s", "routes", "tokens", "counters"}


def test_metricas_rechazan_nombres_con_espacios():
    with pytest.raises(ValueError):
        Metrics().increment("pregunta de Juan")
