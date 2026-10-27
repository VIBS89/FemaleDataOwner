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
    id: str
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
    def __init__(self, ttl_s: int = 8 * 3600, clock=time.time):
        self._fernet = Fernet(Fernet.generate_key())  # clave efímera por proceso
        self._ttl = ttl_s
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
            self._sessions[token] = session
        return session

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
            if now - session.last_seen > self._ttl:
                del self._sessions[token]
                return None
            session.last_seen = now
            return session

    def credential(self, session: Session, server_id: str) -> Credential | None:
        """La contraseña solo vive descifrada mientras se abre la conexión."""
        entry = session._secrets.get(server_id)
        if entry is None:
            return None
        login, enc = entry
        return Credential(server_id, login, self._fernet.decrypt(enc).decode("utf-8") if enc is not None else None)

    def drop(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def sessions(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())
