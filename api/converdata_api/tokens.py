"""Tope diario de tokens por usuario (HU-19, OP-04 tras HU-02).

El gateway de LLM informa cada llamada; `TokenLedger` la atribuye al usuario que está preguntando (variable de contexto) y suma
por día UTC. Solo guarda números por usuario, nunca preguntas ni respuestas. En memoria: un solo proceso (OP-03).
"""

from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import threading

_CURRENT_USER: contextvars.ContextVar[str | None] = contextvars.ContextVar("converdata_token_user", default=None)


class TokenLedger:
    def __init__(self, limit_per_day: int = 0, clock=lambda: dt.datetime.now(dt.timezone.utc)):
        self.limit = limit_per_day  # 0 = sin tope
        self._clock = clock
        self._lock = threading.Lock()
        self._day = self._today()
        self._used: dict[str, int] = {}

    def _today(self) -> dt.date:
        return self._clock().date()

    def _roll(self) -> None:
        if self._today() != self._day:
            self._day, self._used = self._today(), {}

    @contextlib.contextmanager
    def as_user(self, user_id: str):
        token = _CURRENT_USER.set(user_id)
        try:
            yield
        finally:
            _CURRENT_USER.reset(token)

    def add(self, user_id: str, tokens: int) -> None:
        with self._lock:
            self._roll()
            self._used[user_id] = self._used.get(user_id, 0) + tokens

    def record_call(self, _role: str, tokens_in: int, tokens_out: int) -> None:
        """Gancho del gateway: atribuye la llamada al usuario del contexto actual."""
        user = _CURRENT_USER.get()
        if user:
            self.add(user, tokens_in + tokens_out)

    def used(self, user_id: str) -> int:
        with self._lock:
            self._roll()
            return self._used.get(user_id, 0)

    def exceeded(self, user_id: str) -> bool:
        return self.limit > 0 and self.used(user_id) >= self.limit
