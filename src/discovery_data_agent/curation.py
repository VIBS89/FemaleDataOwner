"""Reglas de la curación (F24) y puertos de su almacenamiento. Sin E/S: lo usan la API y los repositorios.

- Plantilla de una pregunta confirmada: la pregunta normalizada y sin literales (toda palabra con dígitos o arroba
  que no sea vocabulario del banco; `discovery_data_agent.memory.text.strip_literals`). Es lo único que entra al índice y a `knowledge.golden_discovery` (F17, clase D4).
  No reconoce nombres de personas: eso lo cubre la retención, no la plantilla.
- Regla de votos: qué confirmación resulta de los votos de los usuarios y de los responsables.
- Ediciones de descripciones: de una edición humana o de un diccionario CSV salen `DescriptionEdit`, una por copia física.
- Puertos: `KnowledgeWriter` (escrituras puntuales del conocimiento) y `CurationRepository` (responsables, dudas
  escaladas y votos). Los implementan `discovery_data_agent.storage` (BD `DiscoveryDataAgent`) y, en desarrollo,
  los archivos de `discovery_data_agent.storage.files`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Protocol

from discovery_data_agent.catalog.ids import table_key
from discovery_data_agent.catalog.store import Catalog
from discovery_data_agent.memory.text import has_literals, strip_literals  # noqa: F401  (parte de la interfaz de la curación)
from discovery_data_agent.models.knowledge import BusinessRule, GoldenDiscovery

MAX_SYNONYMS = 12
STEWARD_SOURCE = "steward:"  # `source` de las reglas que gestionan los responsables desde la vista Curación

def normalize_question(text: str) -> str:
    """Minúsculas, sin tildes ni puntuación y con un solo espacio entre palabras."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


def question_template(question: str, known=frozenset()) -> str:
    """Plantilla anonimizada: la pregunta normalizada sin sus literales. Dos preguntas que solo difieren en el número de
    documento o en la fecha dan la misma plantilla. `known`: el vocabulario con dígitos del banco (nombres del
    catálogo y códigos del glosario), que sí se conserva."""
    return normalize_question(strip_literals(question, known))


def golden_id(template: str, asset_key: str) -> str:
    return "u-" + hashlib.sha1(f"{template}|{asset_key}".encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Tally:
    confirms: int
    rejects: int


def tally(votes: dict[str, str]) -> Tally:
    """`votes`: último voto de cada usuario para una pareja pregunta-activo."""
    return Tally(sum(v == "confirm" for v in votes.values()), sum(v == "reject" for v in votes.values()))


def resolve_golden(template: str, asset_key: str, votes: dict[str, str], *, steward: bool, verdict: str,
                   current: GoldenDiscovery | None) -> GoldenDiscovery:
    """La confirmación que resulta de un voto nuevo (F24 §Captura desde el uso).

    - Voto de un responsable del dominio: entra de inmediato, y su "✖" retira la pareja.
    - Votos de usuarios: cuentan las confirmaciones netas (confirmaciones menos rechazos). Con 2 o más pesa en la
      confianza (F22); con 0 o menos la pareja se retira. Un solo "✖" no retira lo que confirmaron varios.
    - Si ya la confirmó un responsable, los votos de usuarios no cambian su decisión."""
    counted = tally(votes)
    gid = golden_id(template, asset_key)
    if steward:
        return GoldenDiscovery(id=gid, template=template, asset_keys=[asset_key], confirmed_by="steward",
                               confirmations=max(counted.confirms, 1), rejected=verdict == "reject")
    if current is not None and current.confirmed_by == "steward":
        return current.model_copy(update={"confirmations": max(counted.confirms, 1)})
    net = counted.confirms - counted.rejects
    return GoldenDiscovery(id=gid, template=template, asset_keys=[asset_key], confirmed_by="users",
                           confirmations=max(net, 1), rejected=net <= 0)


# --- ediciones de descripciones --------------------------------------------------------------------
@dataclass(frozen=True)
class DescriptionEdit:
    """Nueva descripción de una copia física de una tabla (`column=None`) o de una de sus columnas."""

    physical_id: str
    column: str | None
    description: str
    source: str  # human | data_dictionary
    reviewed: bool
    synonyms: tuple[str, ...] | None = None  # None = no se tocan
    keep_human: bool = False  # no reemplaza una descripción `human` (diccionarios)


def clean_synonyms(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(s.strip() for s in values if s and s.strip()))[:MAX_SYNONYMS]


def _target(obj, column: str | None):
    if column is None:
        return obj
    return next((c for c in obj.columns if c.name.lower() == column.lower()), None)


def human_edits(catalog: Catalog, asset_key: str, description: str, synonyms: list[str] | None) -> list[DescriptionEdit]:
    """Una edición del responsable se escribe en todas las copias físicas del activo (F24 §Revisión del catálogo)."""
    column = ".".join(asset_key.split(".")[3:]) or None
    edits = []
    for obj in catalog.copies(table_key(asset_key)):
        target = _target(obj, column)
        if target is None:
            continue
        edits.append(DescriptionEdit(obj.id, target.name if column else None, description.strip(), "human", True,
                                     clean_synonyms(synonyms) if synonyms is not None else None))
    return edits


@dataclass
class DictionaryPlan:
    rows: int = 0
    skipped_human: int = 0
    same: int = 0
    unknown: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    edits: list[DescriptionEdit] = field(default_factory=list)

    def report(self, applied: int) -> dict:
        """`unchanged`: el diccionario ya estaba aplicado (nada que escribir y al menos una fila igual)."""
        return {"unchanged": applied == 0 and self.same > 0, "applied": applied, "skipped_human": self.skipped_human,
                "same": self.same, "unknown": self.unknown, "forbidden": self.forbidden, "rows": self.rows}


def plan_dictionary(catalog: Catalog, text: str, allowed: Callable[[str], bool]) -> DictionaryPlan:
    """Lee un diccionario CSV (`asset_key` o `database,schema,table[,column]`, `description`, `synonyms` con `;`) y
    decide qué se escribiría (HU-25, F23 CA1). Las descripciones entran como `data_dictionary` sin pisar las `human`.
    `allowed(asset_key)` limita el alcance al dominio del responsable. No llama al LLM.

    Aplicar dos veces el mismo archivo no hace nada (F23 CA5) porque la segunda vez no queda nada que escribir; no se
    recuerda el archivo, así que otro responsable puede aplicar después las filas de su dominio, y las de un activo
    que aún no estaba en el catálogo entran cuando exista."""
    plan = DictionaryPlan()
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    plan.rows = len(rows)
    for row in rows:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        key = row.get("asset_key") or ".".join(
            p for p in (row.get("database"), row.get("schema"), row.get("table"), row.get("column")) if p)
        description = row.get("description", "")
        if not key or not description:
            continue
        copies = catalog.copies(table_key(key))
        if not copies or not catalog.exists(key):
            plan.unknown.append(key)
            continue
        if not allowed(key):
            plan.forbidden.append(key)
            continue
        new_synonyms = [x.strip() for x in row.get("synonyms", "").split(";") if x.strip()]
        column = ".".join(key.split(".")[3:]) or None
        for obj in copies:
            target = _target(obj, column)
            if target is None:
                continue
            if target.description_source == "human":
                plan.skipped_human += 1
                continue
            if target.description == description and target.description_source == "data_dictionary":
                plan.same += 1
                continue
            synonyms = clean_synonyms([*target.synonyms, *new_synonyms]) if new_synonyms else None
            plan.edits.append(DescriptionEdit(obj.id, target.name if column else None, description, "data_dictionary",
                                              target.reviewed, synonyms, keep_human=True))
    return plan


def steward_rules(rules: list[BusinessRule]) -> list[BusinessRule]:
    """Las reglas que gestionan los responsables (HU-28), a diferencia de las importadas con el catálogo."""
    return [r for r in rules if (r.source or "").startswith(STEWARD_SOURCE)]


# --- puertos ---------------------------------------------------------------------------------------
class KnowledgeWriter(Protocol):
    """Escrituras puntuales del conocimiento curado. Cada una es atómica y deja constancia de quién la hizo."""

    def write_descriptions(self, edits: list[DescriptionEdit], *, by: str, reason: str) -> int:
        """Devuelve cuántas copias cambió."""

    def upsert_rule(self, rule: BusinessRule, *, by: str) -> None: ...

    def delete_rule(self, rule_id: str, *, by: str) -> bool: ...

    def upsert_golden(self, golden: GoldenDiscovery, *, by: str, question: str | None = None) -> None:
        """`question`: texto original (D2); solo se guarda la primera vez y nunca entra al índice."""


class CurationRepository(Protocol):
    """Estado de la curación que no es catálogo: responsables por login, dudas escaladas y votos."""

    def stewards(self) -> list[dict]: ...  # [{login, domains}]

    def save_stewards(self, items: list[dict], *, by: str) -> None: ...

    def requests(self) -> list[dict]: ...  # en orden de creación

    def add_requests(self, items: list[dict]) -> list[dict]:
        """Guarda las que no existan (misma respuesta y mismo usuario) y devuelve cómo quedó cada una."""

    def answer_request(self, request_id: str, status: str, answer: dict) -> dict:
        """`KeyError` si no existe."""

    def add_vote(self, vote: dict) -> dict[str, str]:
        """Guarda el voto y devuelve el último voto de cada usuario para su `golden_id`."""
