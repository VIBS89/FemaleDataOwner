"""Catálogo y base de conocimiento en memoria del proceso.

On-premise la fuente es el esquema `catalog`/`knowledge` de la BD `ConverData` (OP-02); en desarrollo y tests,
el formato lógico YAML de F1/F23. Ambos producen los mismos objetos Pydantic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from converdata.catalog.ids import is_column_key, short_name, table_key
from converdata.config import Inventory
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

    def physical_ids(self, asset_key: str) -> set[str]:
        """Ids físicos que dan acceso a un activo (para una columna, los de su tabla)."""
        return {o.id for o in self.copies(asset_key)}

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

    def rules_for(self, asset_key: str) -> list[BusinessRule]:
        return [r for r in self.rules if asset_key in r.applies_to or table_key(asset_key) in r.applies_to]


# --- carga desde YAML (formato lógico de F1 y F23) ---------------------------------------------
def _yaml_docs(root: Path):
    for path in sorted(root.rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            yield path, yaml.safe_load(fh)


def load_catalog(root: str | Path, inventory: Inventory) -> Catalog:
    objects = []
    for path, data in _yaml_docs(Path(root)):
        if path.name.startswith("_"):  # _database.yaml: resumen por BD
            continue
        try:
            objects.append(CatalogObject.model_validate(data))
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return Catalog(objects, inventory)


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
