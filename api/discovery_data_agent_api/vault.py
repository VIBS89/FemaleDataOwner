"""`SessionVault` de OP-03: sesiones en memoria con las credenciales SQL cifradas con una clave efímera.

Las contraseñas nunca se escriben a disco ni a logs; al reiniciar el proceso ningún token anterior es válido (OP-03-CA2).
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class Credential:
    """Credencial de un usuario en un servidor. `login=None` es autenticación de Windows (cuenta del proceso)."""

    server_id: str
    login: str | None
    password: str | None = None

    def __repr__(self) -> str:  # nunca muestra la contraseña
        return f"Credential(server_id={self.server_id!r}, login={self.login!r})"


@dataclass
class Session:
    id: str = field(repr=False)  # el token nunca sale en un repr ni en una traza
    user_id: str
    servers: list[str]
    roles: list[str]
    groups: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    _secrets: dict[str, tuple[str | None, bytes | None]] = field(default_factory=dict, repr=False)

    @property
    def is_admin(self) -> bool:
        return "data_admin" in self.roles


class SessionVault:
    def __init__(self, ttl_s: int = 8 * 3600, clock=time.time, max_age_s: int = 12 * 3600, max_per_user: int = 5):
        self._fernet = Fernet(Fernet.generate_key())  # clave efímera por proceso
        self._ttl = ttl_s  # inactividad (deslizante)
        self._max_age = max_age_s  # vida total: una sesión activa también caduca (0 = sin tope)
        self._max_per_user = max_per_user  # 0 = sin tope
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user_id: str, credentials: list[Credential], roles: list[str]) -> Session:
        token = secrets.token_urlsafe(32)  # 256 bits
        session = Session(id=token, user_id=user_id, servers=[c.server_id for c in credentials], roles=roles,
                          created_at=self._clock(), last_seen=self._clock())
        for c in credentials:
            self._store(session, c)
        with self._lock:
            self._purge()
            if self._max_per_user > 0:  # la más antigua cede su lugar: un token robado no convive indefinidamente
                mine = sorted((s for s in self._sessions.values() if s.user_id.lower() == user_id.lower()),
                              key=lambda s: s.created_at)
                for old in mine[: max(0, len(mine) - self._max_per_user + 1)]:
                    self._forget(old)
            self._sessions[token] = session
        return session

    def _expired(self, session: Session, now: float) -> bool:
        return now - session.last_seen > self._ttl or (self._max_age > 0 and now - session.created_at > self._max_age)

    def _forget(self, session: Session) -> None:
        self._sessions.pop(session.id, None)
        session._secrets.clear()  # las credenciales cifradas no sobreviven a la sesión

    def _purge(self) -> None:
        now = self._clock()
        for session in [s for s in self._sessions.values() if self._expired(s, now)]:
            self._forget(session)

    def add_credential(self, session: Session, credential: Credential) -> None:
        self._store(session, credential)
        if credential.server_id not in session.servers:
            session.servers.append(credential.server_id)

    def _store(self, session: Session, c: Credential) -> None:
        enc = self._fernet.encrypt(c.password.encode("utf-8")) if c.password is not None else None
        session._secrets[c.server_id] = (c.login, enc)

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            now = self._clock()
            if self._expired(session, now):
                self._forget(session)
                return None
            session.last_seen = now
            return session

    def expires_at(self, session: Session) -> float:
        """Momento (reloj del vault) en que caduca si no hay más actividad."""
        idle = session.last_seen + self._ttl
        return min(idle, session.created_at + self._max_age) if self._max_age > 0 else idle

    def credential(self, session: Session, server_id: str) -> Credential | None:
        """La contraseña solo vive descifrada mientras se abre la conexión."""
        entry = session._secrets.get(server_id)
        if entry is None:
            return None
        login, enc = entry
        return Credential(server_id, login, self._fernet.decrypt(enc).decode("utf-8") if enc is not None else None)

    def drop(self, token: str) -> None:
        with self._lock:
            session = self._sessions.get(token)
            if session is not None:
                self._forget(session)

    def drop_user(self, user_id: str) -> int:
        """Revoca todas las sesiones de un usuario (baja, incidente). Devuelve cuántas cerró."""
        with self._lock:
            mine = [s for s in self._sessions.values() if s.user_id.lower() == user_id.lower()]
            for session in mine:
                self._forget(session)
            return len(mine)

    def sessions(self) -> list[Session]:
        with self._lock:
            self._purge()
            return list(self._sessions.values())
