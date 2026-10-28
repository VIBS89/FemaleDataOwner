"""Puerto `CatalogStore`: de dónde sale y a dónde se escribe el catálogo (OP-09 §Puertos que faltan).

Adaptadores: `catalog.files.FileCatalogStore` (YAML de F1/F23, desarrollo y tests) y, con HU-06, el de la BD `ConverData`.
El historial de cambios (RF-34) se añade al puerto con el adaptador de SQL Server, que es el único que lo puede dar.
"""

from __future__ import annotations

from typing import Protocol

from converdata.catalog.store import Catalog, KnowledgeBase
from converdata.config import Inventory
from converdata.models.catalog import CatalogObject
from converdata.models.knowledge import BusinessEntity, LineageEdge


class CatalogStore(Protocol):
    def load_catalog(self, inventory: Inventory) -> Catalog: ...

    def load_knowledge(self) -> KnowledgeBase: ...

    def load_existing(self) -> dict[str, CatalogObject]:
        """Objetos ya guardados por `id`, para fusionar un refresco sin pisar ediciones humanas (F24-CA3)."""
        ...

    def save_catalog(self, inventory: Inventory, objects: list[CatalogObject], entities: list[BusinessEntity],
                     lineage: list[LineageEdge]) -> int:
        """Persiste el catálogo completo; los objetos que ya no vienen salen del catálogo. Devuelve cuántos objetos cambiaron."""
        ...
