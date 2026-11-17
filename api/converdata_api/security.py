"""Controles de seguridad transversales de ConverData-API (OP-03, OP-04, OP-05).

- `LoginThrottle`: bloqueo temporal por login y por origen tras varios intentos fallidos (fuerza bruta, relleno de credenciales).
- `SecurityMiddleware`: cabeceras de seguridad, tope del tamaño del cuerpo y verificación de `Origin` en peticiones que
  cambian estado y se autentican con cookie (CSRF).
- `production_violations`: lo que impide arrancar con `CONVERDATA_ENV=qa|prod` (modo demo, cookie sin `Secure`, CORS abierto…).
- `valid_login`, `valid_host`, `valid_identifier`: lo que puede entrar en una cadena de conexión ODBC.

Todo en memoria del proceso: la API corre con un solo worker (OP-03).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from converdata_api.settings import ApiSettings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_COOKIE = "cd_session"
DOCS_PATHS = frozenset({"/docs", "/redoc"})  # Swagger UI carga scripts; en producción estas rutas no existen


# Un login o un host van dentro de una cadena de conexión ODBC: `;`, `{`, `}` y `=` permitirían añadir atributos
# (p. ej. `x;Trusted_Connection=yes` entraría con la cuenta del proceso). El conector además los envuelve en llaves.
_LOGIN = re.compile(r"^[^;{}=\x00-\x1f\x7f]{1,128}$")
_HOST = re.compile(r"^(?:tcp:|np:|lpc:)?[A-Za-z0-9_.\-]+(?:\\[A-Za-z0-9_$\-]+)?(?:,\d{1,5})?$")
_IDENTIFIER = re.compile(r"^[^;{}=\x00-\x1f\x7f/\\]{1,128}$")


def valid_login(value: str) -> bool:
    return bool(_LOGIN.match(value))


def valid_host(value: str) -> bool:
    """`servidor`, `servidor\\INSTANCIA`, `servidor,1433`, `tcp:servidor.banco.local,1433`."""
    return len(value) <= 256 and bool(_HOST.match(value))


def valid_identifier(value: str) -> bool:
    """Nombre de base de datos tal como va en `DATABASE=` (o `*`)."""
    return bool(_IDENTIFIER.match(value))


class LoginThrottle:
    """Cuenta fallos por clave (`login:<usuario>`, `ip:<origen>`) en una ventana; al llegar al máximo, bloquea la clave.

    Un login correcto limpia los fallos del usuario pero no los del origen: quien prueba muchas cuentas desde la misma
    máquina sigue bloqueado aunque acierte una."""

    def __init__(self, max_failures: int = 5, window_s: int = 900, lockout_s: int = 900, clock=time.monotonic,
                 max_keys: int = 10_000):
        self.max_failures, self.window_s, self.lockout_s = max_failures, window_s, lockout_s
        self._clock = clock
        self._max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_failures > 0

    def retry_after(self, *keys: str) -> int:
        """Segundos que faltan para poder intentar de nuevo con cualquiera de las claves; 0 si ninguna está bloqueada."""
        if not self.enabled:
            return 0
        now = self._clock()
        with self._lock:
            wait = 0.0
            for key in keys:
                until = self._locked_until.get(key)
                if until is None:
                    continue
                if until <= now:
                    del self._locked_until[key]
                    self._failures.pop(key, None)
                else:
                    wait = max(wait, until - now)
            return int(wait) + 1 if wait > 0 else 0

    def failure(self, *keys: str) -> bool:
        """Registra un intento fallido; devuelve True si alguna clave quedó bloqueada con este intento."""
        if not self.enabled:
            return False
        now = self._clock()
        locked = False
        with self._lock:
            if len(self._failures) > self._max_keys:  # no crece sin límite ante un barrido de usuarios
                self._prune(now)
            for key in keys:
                q = self._failures.setdefault(key, deque())
                while q and now - q[0] > self.window_s:
                    q.popleft()
                q.append(now)
                if len(q) >= self.max_failures:
                    self._locked_until[key] = now + self.lockout_s
                    locked = True
        return locked

    def success(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)

    def _prune(self, now: float) -> None:
        for key in [k for k, q in self._failures.items() if not q or now - q[-1] > self.window_s]:
            if key not in self._locked_until:
                del self._failures[key]


def security_headers(settings: ApiSettings) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
        (b"cache-control", b"no-store"),  # las respuestas llevan metadatos filtrados por permisos: nunca en cachés
        (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
    ]
    if settings.cookie_secure:  # solo detrás de HTTPS
        headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
    return headers


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


class SecurityMiddleware:
    """ASGI. Rechaza antes de llegar a las rutas y añade las cabeceras a todas las respuestas, incluidos los errores."""

    def __init__(self, app, settings: ApiSettings, on_block=None):
        self.app = app
        self.settings = settings
        self.headers = security_headers(settings)
        self.allowed_origins = {o.lower().rstrip("/") for o in settings.cors_origins}
        if settings.public_url:
            self.allowed_origins.add(_origin_of(settings.public_url))
        self.on_block = on_block or (lambda reason: None)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers if k not in present
                         and not (k == b"content-security-policy" and scope["path"] in DOCS_PATHS)]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        async def reject(status: int, detail: str, reason: str):
            self.on_block(reason)
            body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
            await send_with_headers({"type": "http.response.start", "status": status, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        method = scope["method"].upper()
        if method not in SAFE_METHODS:
            if self._cross_site(headers):
                return await reject(403, "Origen no permitido", "csrf_blocked")
            limit = self.settings.max_body_bytes
            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                return await reject(413, "La petición es demasiado grande", "body_too_large")
            received = 0

            async def limited_receive():
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:  # sin Content-Length (chunked): se corta al pasar el tope
                        raise BodyTooLarge()
                return message

            try:
                return await self.app(scope, limited_receive, send_with_headers)
            except BodyTooLarge:
                return await reject(413, "La petición es demasiado grande", "body_too_large")
        await self.app(scope, receive, send_with_headers)

    def _cross_site(self, headers: dict[str, str]) -> bool:
        """Cambio de estado autenticado por cookie desde un origen que no es el del sitio. Con `Bearer` no aplica:
        un sitio ajeno no puede añadir esa cabecera sin pasar por CORS."""
        if headers.get("authorization", "").lower().startswith("bearer "):
            return False
        if f"{SESSION_COOKIE}=" not in headers.get("cookie", ""):
            return False
        origin = headers.get("origin")
        if origin is None:  # clientes que no son navegador (curl, pruebas); los navegadores la envían en POST/PUT/DELETE
            return headers.get("sec-fetch-site", "").lower() == "cross-site"
        origin = origin.lower().rstrip("/")
        if origin in self.allowed_origins:
            return False
        host = headers.get("host", "").lower()
        # Mismo origen que la propia API, o que el sitio que la sirve por proxy (Next.js reenvía `X-Forwarded-Host`;
        # un sitio ajeno no puede fijar esa cabecera desde el navegador sin pasar por CORS).
        forwarded = headers.get("x-forwarded-host", "").split(",")[0].strip().lower()
        return urlsplit(origin).netloc not in {host, forwarded} - {""}


class BodyTooLarge(Exception):
    pass


def production_violations(settings: ApiSettings) -> list[str]:
    """Ajustes que no se aceptan con `CONVERDATA_ENV=qa|prod`. Lista vacía = se puede arrancar."""
    problems = []
    if settings.allow_windows_auth:
        problems.append("CONVERDATA_ALLOW_WINDOWS_AUTH debe ser 0: esa opción abre sesión con la cuenta del servicio, "
                        "no con la de quien llama")
    if not settings.admins_only or not settings.admins:
        problems.append("CONVERDATA_ADMINS_ONLY=1 y CONVERDATA_ADMINS son obligatorios: el rol data_admin se asigna por "
                        "lista explícita, no por ser sysadmin de algún servidor")
    inventory = _yaml(settings.inventory_path)
    servers = (inventory or {}).get("servers") or []
    if not servers and not settings.setup_token:
        problems.append("Sin inventario de servidores hace falta CONVERDATA_SETUP_TOKEN para el primer arranque")
    for server in servers:
        if server.get("trust_server_certificate"):
            problems.append(f"El servidor {server.get('id')} tiene trust_server_certificate: el certificado TLS debe validarse")
    catalog_settings = _yaml(settings.data_root / "config" / "settings.yaml") or {}
    if (catalog_settings.get("audit") or {}).get("fail_open"):
        problems.append("config/settings.yaml tiene audit.fail_open: la auditoría debe ser fail-closed (F11)")
    if settings.models_path is not None:
        models = _yaml(settings.models_path) or {}
        if models.get("data_mode") != "real":
            problems.append("config/models.yaml debe declarar data_mode: real, para que el gateway rechace proveedores "
                            "que solo admiten datos de prueba (OP-06)")
        if "embed" in (models.get("roles") or {}):
            problems.append("config/models.yaml no debe declarar el rol embed: la búsqueda es léxica y los embeddings "
                            "no se despliegan (PRD §13, decisión 9)")
    if not settings.db:
        problems.append("CONVERDATA_DB es obligatorio: la auditoría debe escribirse en la BD ConverData, donde la cuenta "
                        "del servicio no puede modificarla ni borrarla (OP-05)")
    else:
        options = {k.strip().lower(): v.strip().lower() for k, _, v in
                   (chunk.partition("=") for chunk in settings.db.split(";")) if k.strip()}
        if "pwd" in options or "password" in options:
            problems.append("CONVERDATA_DB no puede llevar contraseña: la conexión usa la cuenta del servicio "
                            "(Trusted_Connection=yes con la gMSA, OP-03)")
        if options.get("trustservercertificate") in ("yes", "true", "1"):
            problems.append("CONVERDATA_DB tiene TrustServerCertificate: el certificado TLS de la BD ConverData debe validarse")
        if options.get("encrypt") in ("no", "false", "0", "optional"):
            problems.append("CONVERDATA_DB debe cifrar la conexión (Encrypt=yes): por ella viajan las preguntas auditadas")
    if settings.demo:
        problems.append("CONVERDATA_DEMO está activo: el modo demo usa servidores simulados y la contraseña 'demo'")
    if not settings.cookie_secure:
        problems.append("CONVERDATA_COOKIE_SECURE debe ser 1: la cookie de sesión solo puede viajar por HTTPS")
    for origin in settings.cors_origins:
        if origin == "*" or not origin.lower().startswith("https://"):
            problems.append(f"CONVERDATA_CORS_ORIGINS admite solo orígenes https explícitos (encontrado: {origin})")
    if settings.mcp_enabled and not settings.mcp_allowed_hosts:
        problems.append("CONVERDATA_MCP_HOSTS es obligatorio con /mcp activo (protección contra DNS rebinding)")
    if settings.login_max_failures <= 0:
        problems.append("CONVERDATA_LOGIN_MAX_FAILURES debe ser mayor que 0 (bloqueo por intentos fallidos)")
    if settings.log_dir is None:
        problems.append("CONVERDATA_LOG_DIR es obligatorio: los logs operativos alimentan el monitoreo (OP-05)")
    if settings.session_ttl_s > 8 * 3600 or settings.session_max_age_s > 12 * 3600:
        problems.append("La sesión no puede durar más de 8 h de inactividad ni 12 h en total (OP-03)")
    if settings.notify_webhook and not settings.notify_webhook.lower().startswith("https://"):
        problems.append("CONVERDATA_NOTIFY_WEBHOOK debe ser https")
    return problems


def _yaml(path: Path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else None
    except (OSError, yaml.YAMLError):
        return None


class InsecureConfiguration(RuntimeError):
    def __init__(self, problems: list[str]):
        super().__init__("Configuración no apta para producción:\n- " + "\n- ".join(problems))
        self.problems = problems
