"""Modo demo (CONVERDATA_DEMO=1): servidores simulados con los fixtures y el conocimiento curado que trae cada uno.

- El inventario arranca con la unión de `config/databases.yaml` de los fixtures (VBank: Producción Canales, QA Canales,
  Producción DWH; BancosSQL: SQL Express local).
- Tras cada build se copian `knowledge/` (reglas, golden, glosario, linaje ETL) y los responsables de cada fixture, y se
  superponen sus descripciones revisadas, para que la demo muestre "Revisada por un responsable", "Diccionario de
  datos", BR-ONB-004… El conocimiento que escribe el build (`estate/entities.yaml`, `lineage/views.yaml`) no se pisa,
  y tampoco lo que un responsable curó en la sesión.
- `responsable` es steward de todos los dominios.

Nunca se usa con datos reales: los fixtures solo tienen metadatos.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from converdata.builder.catalog_builder import object_path
from converdata.catalog.files import FileCatalogStore
from converdata.config import ServerConfig, load_inventory

KNOWLEDGE_DIRS = ("rules", "golden", "items", "lineage")
BUILD_OWNED = {("lineage", "views.yaml")}  # lo escribe el CatalogBuildFlow
DEMO_STEWARDS = [{"login": "responsable", "domains": ["*"]}]
OBJECT_FIELDS = ("description", "description_source", "reviewed", "synonyms", "domain")
COLUMN_FIELDS = ("description", "description_source", "reviewed", "synonyms")


def demo_inventory(fixtures: list[Path]) -> list[ServerConfig]:
    servers: dict[str, ServerConfig] = {}
    for fixture in fixtures:
        for s in load_inventory(Path(fixture) / "config" / "databases.yaml").servers:
            servers.setdefault(s.id, s.model_copy(update={"auth": "sql", "host": s.host or s.id.lower()}))
    return list(servers.values())


def seed_stewards(curation) -> None:
    current = curation.stewards()
    known = {s["login"] for s in current}
    missing = [s for s in DEMO_STEWARDS if s["login"] not in known]
    if missing:
        curation.save_stewards(current + missing)


def apply_fixture_knowledge(fixtures: list[Path], data_root: Path) -> dict:
    """Copia el conocimiento de los fixtures al directorio del catálogo y superpone sus descripciones curadas."""
    data_root = Path(data_root)
    copied = overlaid = 0
    for fixture in map(Path, fixtures):
        prefix = fixture.name
        for sub in KNOWLEDGE_DIRS:
            src = fixture / "knowledge" / sub
            if not src.is_dir():
                continue
            for f in sorted(src.glob("*.yaml")):
                if (sub, f.name) in BUILD_OWNED:
                    continue
                dest = data_root / "knowledge" / sub / f"{prefix}_{f.name}"
                if not dest.exists():  # no pisa lo que ya se curó en la demo
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, dest)
                    copied += 1
        _merge_owners(fixture / "config" / "owners.yaml", data_root / "config" / "owners.yaml")
        overlaid += _overlay_descriptions(fixture, data_root)
    return {"knowledge_files": copied, "objects_overlaid": overlaid}


def _merge_owners(src: Path, dest: Path) -> None:
    if not src.is_file():
        return
    incoming = yaml.safe_load(src.read_text(encoding="utf-8")) or []
    current = (yaml.safe_load(dest.read_text(encoding="utf-8")) or []) if dest.is_file() else []
    domains = {d["domain"] for d in current}
    merged = current + [d for d in incoming if d["domain"] not in domains]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _overlay_descriptions(fixture: Path, data_root: Path) -> int:
    inventory = load_inventory(fixture / "config" / "databases.yaml")
    count = 0
    for obj in FileCatalogStore(fixture).load_catalog(inventory).objects:
        path = object_path(data_root, obj)
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        changed = _apply(data, obj.model_dump(by_alias=True, mode="json"), OBJECT_FIELDS)
        columns = {c["name"].lower(): c for c in data.get("columns", [])}
        for col in obj.columns:
            target = columns.get(col.name.lower())
            if target is not None:
                changed |= _apply(target, col.model_dump(mode="json"), COLUMN_FIELDS)
        if changed:
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            count += 1
    return count


def _apply(target: dict, source: dict, fields: tuple[str, ...]) -> bool:
    """Superpone los campos curados del fixture salvo que alguien ya los haya curado aquí (`human`)."""
    if target.get("description_source") == "human" and target.get("reviewed"):
        return False
    if source.get("description_source", "generated") == "generated" and not source.get("domain"):
        return False
    changed = False
    for f in fields:
        value = source.get(f)
        if value in (None, [], "") or (f == "description_source" and value == "generated"):
            continue
        if target.get(f) != value:
            target[f] = value
            changed = True
    return changed
