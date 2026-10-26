"""Identidad autenticada que viaja en el estado del grafo (F14). Nunca contiene credenciales."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str
    groups: list[str] = Field(default_factory=list)
    # Ids físicos (`<env>:<server>.<db>.<schema>.<obj>`) que el login del usuario puede leer o ejecutar.
    visible_ids: frozenset[str] = Field(default_factory=frozenset)
    roles: list[str] = Field(default_factory=lambda: ["consumer"])
