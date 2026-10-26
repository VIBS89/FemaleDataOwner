"""Gateway de LLM (F16): un único punto por el que pasan todas las llamadas a modelos.

- Resuelve cada **rol** (`planner`, `fast`, `judge`, `coder`, `embed`) al proveedor y modelo de `config/models.yaml`.
  Empezar con NVIDIA NIM y pasar a Bedrock es solo cambiar ese archivo (F16-CA1).
- **Respaldo** a otro proveedor solo ante throttling, indisponibilidad o timeout; nunca por errores de contenido.
- **Circuit breaker** por proveedor: 3 errores transitorios en 60 s lo abren 5 min.
- **Guarda de residencia** (F17, OP-06): con `data_mode: real`, se niega a arrancar si algún rol puede enviar datos a un
  proveedor marcado `allowed_data: test` (por ejemplo, la API alojada de NVIDIA).
- **Etiquetas para la auditoría**: qué `proveedor:modelo` atendió la última llamada de cada rol (`audit_step.model`).

Los nodos del grafo no saben qué proveedor hay detrás: reciben un `RoutedChat`, que se usa como un chat model de LangChain
(`invoke`, `with_structured_output`).
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from converdata.llm.factory import BUILDERS, LOCAL_ONLY_PROVIDERS, ModelsConfig, RoleConfig, load_models


class ResidencyError(RuntimeError):
    """La configuración enviaría datos reales a un proveedor no autorizado para ellos."""


class GatewayConfigError(RuntimeError):
    pass


class AllProvidersFailed(RuntimeError):
    pass


_TRANSIENT_NAMES = re.compile(r"(timeout|throttl|ratelimit|toomanyrequests|serviceunavailable|connect)", re.I)
# Solo códigos HTTP con forma explícita ("[503] …" de NIM, "status 503", "HTTP 502"); un número suelto no basta.
_TRANSIENT_STATUS = re.compile(r"\[(500|502|503|504)\]|\b(?:status|http)\D{0,3}(500|502|503|504)\b", re.I)
_TRANSIENT_CODES = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException",
                    "InternalServerException", "TooManyRequestsException"}


def classify_error(exc: BaseException) -> str | None:
    """`throttling` | `service_unavailable` | `timeout` si el error es transitorio; None si es de contenido o configuración."""
    name = type(exc).__name__
    code = getattr(getattr(exc, "response", None), "get", lambda *_: None)("Error", {}) or {}
    code = code.get("Code") if isinstance(code, dict) else None
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
    text = f"{name} {code or ''} {status or ''} {exc}"
    if "timeout" in name.lower() or isinstance(exc, TimeoutError):
        return "timeout"
    if code in _TRANSIENT_CODES:
        return "throttling" if "Throttl" in code or "TooMany" in code else "service_unavailable"
    if status == 429 or re.search(r"\[429\]|\b(?:status|http)\D{0,3}429\b|throttl|too many requests|rate limit", text, re.I):
        return "throttling"
    if (status and int(status) >= 500) or _TRANSIENT_STATUS.search(text) or _TRANSIENT_NAMES.search(name):
        return "service_unavailable"
    return None


class CircuitBreaker:
    def __init__(self, errors: int, window_s: float, open_s: float, clock: Callable[[], float]):
        self.errors, self.window_s, self.open_s, self._clock = errors, window_s, open_s, clock
        self._failures: dict[str, deque[float]] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, provider: str) -> bool:
        with self._lock:
            return self._clock() < self._open_until.get(provider, 0.0)

    def record_failure(self, provider: str) -> None:
        with self._lock:
            now = self._clock()
            q = self._failures.setdefault(provider, deque())
            q.append(now)
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.errors:
                self._open_until[provider] = now + self.open_s
                q.clear()

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._failures.pop(provider, None)


@dataclass(frozen=True)
class Route:
    provider: str
    role: RoleConfig

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.role.model}"


class RoutedChat:
    """Chat model enrutado por el gateway. Imita la parte de la interfaz de LangChain que usan los nodos."""

    def __init__(self, gateway: "LLMGateway", role: str, schema: Any = None, structured_kwargs: dict | None = None):
        self._gw, self.role, self._schema, self._skw = gateway, role, schema, structured_kwargs or {}

    def with_structured_output(self, schema, **kwargs) -> "RoutedChat":
        return RoutedChat(self._gw, self.role, schema, kwargs)

    def invoke(self, messages, **kwargs):
        return self._gw._invoke(self.role, messages, self._schema, self._skw, kwargs)


class _Labels(Mapping):
    """Vista viva rol → `proveedor:modelo` de la última llamada (o el primario si aún no hubo)."""

    def __init__(self, gateway: "LLMGateway"):
        self._gw = gateway

    def __getitem__(self, role):
        if role in self._gw._last_used:
            return self._gw._last_used[role]
        routes = self._gw.routes(role) if role in self._gw.config.roles else []
        if not routes:
            raise KeyError(role)
        return routes[0].label

    def __iter__(self):
        return iter(self._gw.config.roles)

    def __len__(self):
        return len(self._gw.config.roles)


class LLMGateway:
    def __init__(self, config: ModelsConfig, builders: dict | None = None, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self._builders = {**BUILDERS, **(builders or {})}
        c = config.circuit
        self.breaker = CircuitBreaker(c.errors, c.window_s, c.open_s, clock)
        self._cache: dict[tuple[str, str, str], Any] = {}
        self._last_used: dict[str, str] = {}
        self.labels = _Labels(self)
        self.validate()

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "LLMGateway":
        return cls(load_models(path), **kwargs)

    # --- validación ------------------------------------------------------------------------
    def validate(self) -> None:
        for role in self.config.roles:
            for route in self.routes(role):
                prov = self.config.provider(route.provider)
                if not prov.enabled:
                    raise GatewayConfigError(f"El rol {role!r} usa el proveedor {route.provider!r}, que está desactivado")
                if route.provider in LOCAL_ONLY_PROVIDERS and self.config.environment != "local":
                    raise GatewayConfigError(
                        f"El proveedor {route.provider!r} (rol {role!r}) solo se permite con environment: local "
                        f"(actual: {self.config.environment or 'sin definir'})"
                    )
                if self.config.data_mode == "real" and prov.allowed_data != "real":
                    raise ResidencyError(
                        f"data_mode=real pero el rol {role!r} puede enviar datos a {route.provider!r} "
                        f"(allowed_data={prov.allowed_data}); ver F17 y OP-06"
                    )

    def routes(self, role: str) -> list[Route]:
        if role not in self.config.roles:
            raise GatewayConfigError(f"Rol {role!r} no configurado en models.yaml")
        primary = self.config.roles[role]
        routes = [Route(primary.provider, primary)]
        fb = self.config.fallback
        # Los embeddings no tienen respaldo: otro modelo produce vectores incompatibles con el índice.
        if role != "embed" and fb and fb.provider != primary.provider and role in fb.models:
            prov_fb = self.config.provider(fb.provider)
            if prov_fb.enabled:
                routes.append(Route(fb.provider, primary.model_copy(update={"provider": fb.provider, "model": fb.models[role]})))
        return routes

    # --- API pública -----------------------------------------------------------------------
    def chat(self, role: str) -> RoutedChat:
        self.routes(role)  # valida que el rol exista
        return RoutedChat(self, role)

    def has_role(self, role: str) -> bool:
        return role in self.config.roles

    def embeddings(self):
        """Modelo de embeddings del rol `embed` (o None si no está configurado: búsqueda solo léxica)."""
        if "embed" not in self.config.roles:
            return None
        route = self.routes("embed")[0]
        return self._model(route, "embed")

    @property
    def embed_model(self) -> str:
        """Etiqueta que se guarda en el índice; la búsqueda verifica que coincida (F2)."""
        if "embed" not in self.config.roles:
            return "lexical-only"
        r = self.config.roles["embed"]
        return f"{r.provider}:{r.model}" + (f"@{r.dimensions}" if r.dimensions else "")

    # --- internos --------------------------------------------------------------------------
    def _model(self, route: Route, kind: str, schema=None, skw=None):
        key = (route.label, kind, repr(schema))
        if key not in self._cache:
            builder = self._builders.get((route.provider, kind))
            if builder is None:
                raise GatewayConfigError(f"Proveedor {route.provider!r} sin constructor para {kind}")
            model = builder(route.role, self.config.provider(route.provider))
            if schema is not None:
                model = model.with_structured_output(schema, **(skw or {}))
            self._cache[key] = model
        return self._cache[key]

    def _invoke(self, role: str, messages, schema, skw, kwargs):
        allowed = set(self.config.fallback.on) if self.config.fallback else set()
        errors: list[str] = []
        routes = self.routes(role)
        for i, route in enumerate(routes):
            if self.breaker.is_open(route.provider):
                errors.append(f"{route.provider}:circuito_abierto")
                continue
            model = self._model(route, "chat", schema, skw)
            try:
                result = model.invoke(messages, **kwargs)
            except Exception as exc:
                kind = classify_error(exc)
                if kind is None:
                    raise  # error de contenido o configuración: no se reintenta en otro proveedor
                self.breaker.record_failure(route.provider)
                errors.append(f"{route.provider}:{kind}")
                is_last = i == len(routes) - 1
                if is_last or kind not in allowed:
                    raise AllProvidersFailed("; ".join(errors)) from exc
                continue
            self.breaker.record_success(route.provider)
            self._last_used[role] = route.label + (" (respaldo)" if i > 0 else "")
            return result
        raise AllProvidersFailed("; ".join(errors) or f"sin rutas para {role}")
