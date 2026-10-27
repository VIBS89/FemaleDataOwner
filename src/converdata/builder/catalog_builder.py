"""Pasos deterministas del Catalog Builder (F1): conversión, PII, enriquecimiento por reglas, fusión con lo existente,
entidades entre BDs (F19), linaje de vistas y escritura en el formato lógico de F1.

Reglas de F1 que se cumplen aquí:
- nunca se sobrescribe una descripción `human` (ni `data_dictionary`) en un refresco;
- el catálogo no contiene valores (el modelo `CatalogObject` rechaza cualquier campo de valores);
- un objeto sin cambios (mismo `schema_hash`) se reutiliza tal cual: no se vuelve a enriquecer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from converdata.catalog.ids import asset_key_of, physical_id
from converdata.config import Inventory, ServerConfig
from converdata.discovery.expansion import LEXICON
from converdata.memory.text import normalized_name, strip_accents
from converdata.metadata.ports import RawObject
from converdata.models.catalog import CatalogObject, Column, ForeignKey, Parameter
from converdata.models.knowledge import BusinessEntity, LineageEdge, LineageVia

_PROTECTED_SOURCES = {"human", "data_dictionary"}
_PII_NAME = re.compile(
    r"(dui|nit|pasaporte|passport|email|correo|telefono|celular|phone|nombres?$|apellidos?|direccion|address|"
    r"fechanacimiento|birth|numerotarjeta|cardnumber|^pan$|numerocuenta|accountnumber|cvv|password|clave)",
    re.I,
)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[_\s]+")
_EN_TO_ES = defaultdict(list)
for _es, _ens in LEXICON.items():
    for _en in _ens:
        _EN_TO_ES[_en].append(_es)


def words_of(identifier: str) -> list[str]:
    return [w.lower() for w in _CAMEL.split(identifier) if w]


def schema_hash(raw: RawObject) -> str:
    payload = {
        "kind": raw.kind,
        "columns": [(c.name, c.type, c.nullable) for c in raw.columns],
        "pk": raw.primary_key,
        "fks": sorted((fk["name"], tuple(fk["columns"]), fk["ref_table"]) for fk in raw.foreign_keys),
        "params": [(p["name"], p["type"]) for p in raw.parameters],
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def is_pii(name: str, sensitivity: str | None) -> bool:
    return bool(sensitivity) or bool(_PII_NAME.search(strip_accents(name)))


def domain_of(database: str) -> str:
    words = [w for w in words_of(database) if w not in ("banca", "bd", "db")]
    return "_".join(strip_accents(w) for w in words) or database.lower()


def rule_synonyms(identifier: str) -> list[str]:
    """Sinónimos por reglas: el identificador separado en palabras y, si está en inglés, su traducción al español."""
    words = words_of(identifier)
    out = []
    spaced = " ".join(words)
    if spaced and spaced != identifier.lower():
        out.append(spaced)
    translated = [(_EN_TO_ES.get(w) or [None])[0] for w in words]
    if any(translated):
        out.append(" ".join(t or w for t, w in zip(translated, words)))
    return list(dict.fromkeys(out))


def to_catalog_object(raw: RawObject, server: ServerConfig) -> CatalogObject:
    columns = [
        Column(
            name=c.name,
            type=c.type,
            nullable=c.nullable,
            description=c.ms_description,
            description_source="ms_description" if c.ms_description else "generated",
            synonyms=rule_synonyms(c.name),
            pii=is_pii(c.name, c.sensitivity),
        )
        for c in raw.columns
    ]
    fks = [
        ForeignKey(columns=fk["columns"], ref=asset_key_of(raw.database, fk["ref_schema"], fk["ref_table"]),
                   ref_columns=fk["ref_columns"])
        for fk in raw.foreign_keys
    ]
    return CatalogObject(
        id=physical_id(server.environment, server.id, raw.database, raw.schema, raw.name),
        asset_key=asset_key_of(raw.database, raw.schema, raw.name),
        environment=server.environment,
        server=server.id,
        kind=raw.kind,
        database=raw.database,
        schema=raw.schema,
        name=raw.name,
        description=raw.ms_description,
        description_source="ms_description" if raw.ms_description else "generated",
        domain=domain_of(raw.database),
        synonyms=rule_synonyms(raw.name),
        row_count=raw.row_count,
        primary_key=raw.primary_key,
        columns=columns,
        foreign_keys=fks,
        parameters=[Parameter(**p) for p in raw.parameters],
        schema_hash=schema_hash(raw),
    )


def merge_existing(new: CatalogObject, old: CatalogObject | None) -> tuple[CatalogObject, bool]:
    """Devuelve (objeto, necesita_enriquecimiento). Sin cambios de estructura se reutiliza el anterior completo."""
    if old is None:
        return new, True
    if old.schema_hash == new.schema_hash:
        return old, False
    data = new.model_copy(deep=True)
    if old.description_source in _PROTECTED_SOURCES or (old.description and new.description_source == "generated"):
        data.description, data.description_source, data.reviewed = old.description, old.description_source, old.reviewed
        data.synonyms = list(dict.fromkeys([*old.synonyms, *data.synonyms]))
        data.domain = old.domain or data.domain
    old_cols = {c.name: c for c in old.columns}
    for col in data.columns:
        prev = old_cols.get(col.name)
        if prev and (prev.description_source in _PROTECTED_SOURCES or (prev.description and col.description_source == "generated")):
            col.description, col.description_source, col.reviewed = prev.description, prev.description_source, prev.reviewed
            col.synonyms = list(dict.fromkeys([*prev.synonyms, *col.synonyms]))
    return data, any(c.description is None for c in data.columns) or data.description is None


def singular(name: str) -> str:
    """Clientes → Cliente, Agencias → Agencia, Ejecutivos → Ejecutivo, Proveedores → Proveedor."""
    low = name.lower()
    if low.endswith("s") and len(name) > 3 and low[-2] in "aeiou" and not low.endswith("res"):
        return name[:-1]
    if low.endswith("es") and len(name) > 4:
        return name[:-2]
    return name


def detect_entities(objects: list[CatalogObject], min_overlap: float = 0.6) -> list[BusinessEntity]:
    """F19: la misma tabla (nombre normalizado y columnas parecidas) en varias BDs es una entidad de negocio.
    La canónica es la más referenciada por FKs; a igualdad, la de más filas y luego por nombre."""
    tables = [o for o in objects if o.kind == "table"]
    incoming: dict[str, int] = defaultdict(int)
    for o in objects:
        for fk in o.foreign_keys:
            incoming[fk.ref] += 1
    groups: dict[str, list[CatalogObject]] = defaultdict(list)
    for t in tables:
        groups[normalized_name(t.name)].append(t)
    entities = []
    for _, group in sorted(groups.items()):
        by_db = {t.database: t for t in group}
        if len(by_db) < 2:
            continue
        ref = next(iter(by_db.values()))
        ref_cols = {normalized_name(c.name) for c in ref.columns}
        members = [
            t for t in by_db.values()
            if len(ref_cols & {normalized_name(c.name) for c in t.columns}) / max(len(ref_cols | {normalized_name(c.name) for c in t.columns}), 1) >= min_overlap
        ]
        if len(members) < 2:
            continue
        canonical = sorted(members, key=lambda t: (-incoming[t.asset_key], -(t.row_count or 0), t.asset_key))[0]
        name = singular(ref.name)
        entities.append(BusinessEntity(
            name=name,
            synonyms=list(dict.fromkeys([ref.name.lower(), *rule_synonyms(ref.name)])),
            definition=f"Entidad presente en {len(members)} bases de datos con la misma estructura.",
            tables=sorted(t.asset_key for t in members),
            canonical=canonical.asset_key,
        ))
    return entities


def view_lineage(objects: list[CatalogObject], raws: dict[str, RawObject]) -> list[LineageEdge]:
    """Linaje de un salto a nivel de tabla: tabla → vista que la lee (F23, `sys.sql_expression_dependencies`)."""
    known = {o.asset_key for o in objects}
    edges = []
    for o in objects:
        raw = raws.get(o.id)
        if raw is None or o.kind != "view":
            continue
        for dep in raw.dependencies:
            if dep in known and dep != o.asset_key:
                edges.append(LineageEdge(**{"from": dep, "to": o.asset_key, "via": LineageVia(kind="view", name=o.name)}))
    return edges


# --- persistencia en el formato lógico de F1 ------------------------------------------------------
def object_path(root: Path, obj: CatalogObject) -> Path:
    return root / "catalog" / obj.environment / obj.server / obj.database / f"{obj.schema_}.{obj.name}.yaml"


def load_existing(root: Path) -> dict[str, CatalogObject]:
    out = {}
    for path in (root / "catalog").rglob("*.yaml") if (root / "catalog").exists() else []:
        if path.name.startswith("_"):
            continue
        obj = CatalogObject.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        out[obj.id] = obj
    return out


def write_output(root: Path, inventory: Inventory, objects: list[CatalogObject], entities: list[BusinessEntity],
                 lineage: list[LineageEdge]) -> list[Path]:
    """Escribe un directorio completo que el DiscoverFlow puede cargar (`converdata discover --root <dir>`)."""
    written = []
    current = {object_path(root, o) for o in objects}
    for stale in (root / "catalog").rglob("*.yaml") if (root / "catalog").exists() else []:
        if stale not in current and not stale.name.startswith("_"):
            stale.unlink()  # objeto eliminado en la BD: sale del catálogo (F1: deprecated)
    for obj in objects:
        path = object_path(root, obj)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(obj.model_dump(by_alias=True, exclude_defaults=True, mode="json"), allow_unicode=True,
                              sort_keys=False)
        if not path.exists() or path.read_text(encoding="utf-8") != text:  # F1-CA2: sin cambios no se reescribe
            path.write_text(text, encoding="utf-8")
            written.append(path)
    (root / "knowledge" / "estate").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "lineage").mkdir(parents=True, exist_ok=True)
    _dump(root / "knowledge" / "estate" / "entities.yaml", [e.model_dump(exclude_defaults=True) for e in entities])
    _dump(root / "knowledge" / "lineage" / "views.yaml",
          [e.model_dump(by_alias=True, exclude_defaults=True) for e in lineage])
    (root / "config").mkdir(parents=True, exist_ok=True)
    _dump(root / "config" / "databases.yaml", {"servers": [
        s.model_dump(include={"id", "alias", "environment", "platform", "is_reference", "databases"}) for s in inventory.servers
    ]})
    if not (root / "config" / "owners.yaml").exists():
        _dump(root / "config" / "owners.yaml", [])
    return written


def _dump(path: Path, data) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
