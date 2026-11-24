"""Contadores en memoria para `/health/metrics` (HU-22, OP-05): peticiones, errores, latencia p50/p95 y tokens.

Solo números y nombres fijos (D5): nunca preguntas, SQL ni filas. Los percentiles se calculan sobre una ventana de las
últimas `window` peticiones por ruta. El proceso de la API es uno solo (OP-03), así que basta un registro por proceso.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


def _check(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"nombre de métrica inválido: {name!r}")
    return name


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1, round(p / 100 * len(sorted_values)) - 1))
    return sorted_values[idx]


class Metrics:
    def __init__(self, window: int = 1000, clock=time.monotonic):
        self._clock = clock
        self._started = clock()
        self._window = window
        self._lock = threading.Lock()
        self._requests: dict[str, int] = defaultdict(int)
        self._errors: dict[str, int] = defaultdict(int)
        self._latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=self._window))
        self._tokens = {"in": 0, "out": 0}
        self._counters: dict[str, int] = defaultdict(int)

    def observe_request(self, route: str, duration_ms: float, *, ok: bool, tokens_in: int = 0, tokens_out: int = 0) -> None:
        route = _check(route)
        with self._lock:
            self._requests[route] += 1
            if not ok:
                self._errors[route] += 1
            self._latency[route].append(duration_ms)
            self._tokens["in"] += tokens_in
            self._tokens["out"] += tokens_out

    def add_tokens(self, tokens_in: int, tokens_out: int) -> None:
        with self._lock:
            self._tokens["in"] += tokens_in
            self._tokens["out"] += tokens_out

    def increment(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counters[_check(name)] += by

    def snapshot(self) -> dict:
        with self._lock:
            routes = {}
            for route, count in self._requests.items():
                values = sorted(self._latency[route])
                routes[route] = {"requests": count, "errors": self._errors[route],
                                 "p50_ms": _percentile(values, 50), "p95_ms": _percentile(values, 95)}
            return {"uptime_s": int(self._clock() - self._started), "routes": routes, "tokens": dict(self._tokens),
                    "counters": dict(self._counters)}
