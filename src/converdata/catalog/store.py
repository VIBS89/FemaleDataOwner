"""Catálogo y base de conocimiento en memoria del proceso.

On-premise la fuente es el esquema `catalog`/`knowledge` de la BD `ConverData` (OP-02); en desarrollo y tests,
el formato lógico YAML de F1/F23. Ambos producen los mismos objetos Pydantic, reunidos en un `CatalogSnapshot`.
El puerto `CatalogRepository` lo implementa `converdata.storage.catalog_repository` (SQL Server).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from converdata.catalog.ids import is_column_key, short_name, table_key
from converdata.config import Inventory, OwnersDirectory, ServerConfig, load_inventory, load_owners
from converdata.memory.text import strip_accents
from converdata.models.catalog import CatalogObject, Column
from converdata.models.knowledge import BusinessEntity, BusinessRule, GoldenDiscovery, KnowledgeItem, LineageEdge


@dataclass(frozen=True)
class FkEdge:
    from_table: str
    to_table: str
    on: str  # columnas de la FK (lado origen)


class Catalog:
    def __init__(self, objects: list[CatalogObject], inventory: Inventory):
        self.inventory = inventory
        self._by_id: dict[str, CatalogObject] = {}
        self._copies: dict[str, list[CatalogObject]] = defaultdict(list)
        for obj in objects:
            if obj.deprecated:
                continue
            if obj.id in self._by_id:
                raise ValueError(f"Objeto duplicado en el catálogo: {obj.id}")
            self._by_id[obj.id] = obj
            self._copies[obj.asset_key].append(obj)
        # El ambiente de referencia va primero (F1: las búsquedas priorizan `is_reference`).
        for copies in self._copies.values():
            copies.sort(key=lambda o: (not inventory.is_reference(o.environment, o.server), o.environment, o.server))

    # --- consulta -------------------------------------------------------------------------
    @property
    def objects(self) -> list[CatalogObject]:
        return list(self._by_id.values())

    def table_keys(self) -> list[str]:
        return list(self._copies)

    def get(self, physical_id: str) -> CatalogObject | None:
        return self._by_id.get(physical_id)

    def copies(self, asset_key: str) -> list[CatalogObject]:
        return list(self._copies.get(table_key(asset_key), []))

    def exists(self, asset_key: str) -> bool:
        copies = self.copies(asset_key)
        if not copies:
            return False
        if not is_column_key(asset_key):
            return True
        return any(self._find_column(o, short_name(asset_key)) for o in copies)

    def visible_copies(self, asset_key: str, visible_ids: frozenset[str] | set[str]) -> list[CatalogObject]:
        copies = [o for o in self.copies(asset_key) if o.id in visible_ids]
        if is_column_key(asset_key):
            copies = [o for o in copies if self._find_column(o, short_name(asset_key))]
        return copies

    def is_visible(self, asset_key: str, visible_ids: frozenset[str] | set[str]) -> bool:
        return bool(self.visible_copies(asset_key, visible_ids))

    def column(self, asset_key: str, visible_ids: frozenset[str] | set[str]) -> tuple[CatalogObject, Column] | None:
        """Columna de la copia visible de referencia."""
        for obj in self.visible_copies(asset_key, visible_ids):
            col = self._find_column(obj, short_name(asset_key))
            if col:
                return obj, col
        return None

    def fk_edges(self) -> list[FkEdge]:
        edges: dict[tuple[str, str, str], FkEdge] = {}
        for obj in self._by_id.values():
            for fk in obj.foreign_keys:
                edge = FkEdge(obj.asset_key, fk.ref, ", ".join(fk.columns))
                edges[(edge.from_table, edge.to_table, edge.on)] = edge
        return list(edges.values())

    def names_with_digits(self, visible_ids=None) -> frozenset[str]:
        """Nombres de BDs, esquemas, objetos y columnas que llevan algún dígito (`Ultimos4`, `T24`), en minúsculas y
        sin tildes: en una pregunta son vocabulario, no literales. Con `visible_ids`, solo los de objetos visibles."""
        if not hasattr(self, "_digit_names"):
            found: dict[str, set[str]] = defaultdict(set)
            for obj in self._by_id.values():
                for name in (obj.database, obj.schema_, obj.name, *(c.name for c in obj.columns)):
                    if any(ch.isdigit() for ch in name):
                        found[strip_accents(name).lower()].add(obj.id)
            self._digit_names = dict(found)
        return frozenset(name for name, ids in self._digit_names.items()
                         if visible_ids is None or not ids.isdisjoint(visible_ids))

    def all_names(self) -> set[str]:
        """Nombres de objetos y columnas de todo el catálogo (para la guarda de la narrativa)."""
        names: set[str] = set()
        for obj in self._by_id.values():
            names.add(obj.name)
            names.update(c.name for c in obj.columns)
        return names

    @staticmethod
    def _find_column(obj: CatalogObject, name: str) -> Column | None:
        return next((c for c in obj.columns if c.name.lower() == name.lower()), None)


@dataclass
class KnowledgeBase:
    rules: list[BusinessRule] = field(default_factory=list)
    lineage: list[LineageEdge] = field(default_factory=list)
    golden: list[GoldenDiscovery] = field(default_factory=list)
    items: list[KnowledgeItem] = field(default_factory=list)
    entities: list[BusinessEntity] = field(default_factory=list)

    def all_items(self) -> list[KnowledgeItem]:
        """Todo lo que se indexa en las colecciones de conocimiento de F2."""
        return [*self.items, *(r.as_item() for r in self.rules), *(e.as_item() for e in self.lineage)]

    def codes(self) -> frozenset[str]:
        """Códigos del conocimiento del banco: palabras con letras y dígitos de los fragmentos y las reglas (`NCB-022`,
        `BR-ONB-004`), en minúsculas y sin tildes. Los números sueltos no cuentan: un fragmento mal redactado no
        puede convertir un documento o una cuenta en vocabulario."""
        if not hasattr(self, "_codes"):
            words = [w for item in self.items for w in item.text.split()]
            words += [w for rule in self.rules for w in (rule.id, *rule.text.split())]
            edge = "¿?¡!.,;:()[]{}\"'«»“”‘’<>"
            cores = (strip_accents(w.strip(edge)).lower() for w in words)
            self._codes = frozenset(c for c in cores if any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c))
        return self._codes

    def rules_for(self, asset_key: str) -> list[BusinessRule]:
        return [r for r in self.rules if asset_key in r.applies_to or table_key(asset_key) in r.applies_to]


# --- carga desde YAML (formato lógico de F1 y F23) ---------------------------------------------
def _yaml_docs(root: Path):
    for path in sorted(root.rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            yield path, yaml.safe_load(fh)


def load_objects(root: str | Path) -> list[CatalogObject]:
    objects = []
    for path, data in _yaml_docs(Path(root)):
        if path.name.startswith("_"):  # _database.yaml: resumen por BD
            continue
        try:
            objects.append(CatalogObject.model_validate(data))
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return objects


def load_catalog(root: str | Path, inventory: Inventory) -> Catalog:
    return Catalog(load_objects(root), inventory)


def load_knowledge(root: str | Path) -> KnowledgeBase:
    root = Path(root)
    kb = KnowledgeBase()
    loaders = {
        "rules": (kb.rules, BusinessRule),
        "lineage": (kb.lineage, LineageEdge),
        "golden": (kb.golden, GoldenDiscovery),
        "items": (kb.items, KnowledgeItem),
        "estate": (kb.entities, BusinessEntity),
    }
    for sub, (target, model) in loaders.items():
        if (root / sub).exists():
            for _, data in _yaml_docs(root / sub):
                target.extend(model.model_validate(d) for d in (data or []))
    return kb


# --- foto completa: lo que se publica en la BD `ConverData` y lo que carga el DiscoverFlow ---------------
@dataclass
class CatalogSnapshot:
    """Todo lo que el DiscoverFlow necesita de un catálogo: inventario, objetos, conocimiento y responsables."""

    inventory: Inventory
    objects: list[CatalogObject]
    knowledge: KnowledgeBase
    owners: OwnersDirectory

    def catalog(self) -> Catalog:
        return Catalog(self.objects, self.inventory)


def load_snapshot(root: str | Path) -> CatalogSnapshot:
    """Lee un directorio con `config/`, `catalog/` y `knowledge/` (formato de desarrollo y de trabajo del Builder)."""
    root = Path(root)
    return CatalogSnapshot(
        inventory=load_inventory(root / "config" / "databases.yaml"),
        objects=load_objects(root / "catalog"),
        knowledge=load_knowledge(root / "knowledge"),
        owners=load_owners(root / "config" / "owners.yaml"),
    )


class StaleCatalog(RuntimeError):
    """Otro proceso publicó una versión más nueva: hay que volver a cargar antes de escribir."""


@dataclass(frozen=True)
class PublishResult:
    version: int | None  # versión vigente tras publicar (None solo si nunca hubo catálogo y no había nada que escribir)
    changed: bool
    counts: dict[str, int] = field(default_factory=dict)  # tabla.acción → filas (insertadas, actualizadas, borradas)


class CatalogRepository(Protocol):
    """Almacén durable del catálogo (OP-02). Publicar es dejar el almacén igual a la foto, conservando el historial.
    Las escrituras puntuales de la curación son el puerto `converdata.curation.KnowledgeWriter`."""

    def version(self) -> int | None: ...

    def load(self, scope: str = "all") -> tuple[CatalogSnapshot, int] | None: ...

    def publish(self, snapshot: CatalogSnapshot, *, published_by: str, reason: str, scope: str = "all",
                expected_version: int | None = None) -> PublishResult: ...

    def description_history(self, asset_key: str) -> list[dict]:
        """Cambios de la descripción de un activo, del más antiguo al más reciente: `physical_id`, `description`,
        `description_source`, `modified_by`, `valid_from` y `valid_to` (None en la versión vigente)."""


class InventoryStore(Protocol):
    """Inventario de servidores con sus hosts: a dónde se conecta ConverData con la credencial de cada usuario."""

    def inventory(self) -> list[ServerConfig]: ...

    def save_inventory(self, servers: list[ServerConfig], *, by: str) -> None: ...
