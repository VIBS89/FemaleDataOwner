"""Adaptador de archivos del puerto `CatalogStore`: el formato lógico YAML de F1 y F23 (`catalog/`, `knowledge/`, `config/`)."""

from __future__ import annotations

from pathlib import Path

import yaml

from converdata.builder import catalog_builder as cb
from converdata.catalog.store import Catalog, KnowledgeBase
from converdata.config import Inventory
from converdata.models.catalog import CatalogObject
from converdata.models.knowledge import BusinessEntity, BusinessRule, GoldenDiscovery, KnowledgeItem, LineageEdge


def _yaml_docs(root: Path):
    for path in sorted(root.rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            yield path, yaml.safe_load(fh)


class FileCatalogStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def load_catalog(self, inventory: Inventory) -> Catalog:
        objects = []
        for path, data in _yaml_docs(self.root / "catalog"):
            if path.name.startswith("_"):  # _database.yaml: resumen por BD
                continue
            try:
                objects.append(CatalogObject.model_validate(data))
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
        return Catalog(objects, inventory)

    def load_knowledge(self) -> KnowledgeBase:
        kb = KnowledgeBase()
        loaders = {
            "rules": (kb.rules, BusinessRule),
            "lineage": (kb.lineage, LineageEdge),
            "golden": (kb.golden, GoldenDiscovery),
            "items": (kb.items, KnowledgeItem),
            "estate": (kb.entities, BusinessEntity),
        }
        for sub, (target, model) in loaders.items():
            if (self.root / "knowledge" / sub).exists():
                for _, data in _yaml_docs(self.root / "knowledge" / sub):
                    target.extend(model.model_validate(d) for d in (data or []))
        return kb

    def load_existing(self) -> dict[str, CatalogObject]:
        return cb.load_existing(self.root)

    def save_catalog(self, inventory: Inventory, objects: list[CatalogObject], entities: list[BusinessEntity],
                     lineage: list[LineageEdge]) -> int:
        return len(cb.write_output(self.root, inventory, objects, entities, lineage))
