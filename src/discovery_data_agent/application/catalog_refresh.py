"""Caso de uso: refrescar el catálogo (F1, F18) y publicarlo en el almacén durable (OP-02).

Lo usan por igual `discovery-data-agent catalog build --db` (la tarea programada) y la construcción bajo demanda de
DiscoveryDataAgent-API, para que las dos hagan lo mismo:

1. el directorio de trabajo arranca con el catálogo vigente del almacén, así el flujo reutiliza lo que no cambió y
   conserva lo de un servidor que no responde;
2. corre el CatalogBuildFlow con el login de metadatos;
3. si respondió al menos un servidor, publica el resultado. Con `scope="build"` solo se escribe lo que deriva de los
   metadatos: lo curado por personas queda como está en el almacén.

Sin almacén (`repository=None`, desarrollo) el directorio de trabajo es el catálogo y no se publica nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from discovery_data_agent.builder.catalog_builder import write_snapshot
from discovery_data_agent.catalog.store import CatalogRepository, PublishResult, load_snapshot
from discovery_data_agent.config import Inventory
from discovery_data_agent.flows.catalog_build import OWN_DATABASES, BuildReport, build_catalog


@dataclass
class RefreshResult:
    report: BuildReport
    previous_version: int | None = None
    published: PublishResult | None = None  # None: no había almacén o ningún servidor respondió

    @property
    def version(self) -> int | None:
        return self.published.version if self.published else self.previous_version


def refresh_catalog(
    inventory: Inventory, work_dir: Path, *, source_factory, enricher=None, repository: CatalogRepository | None = None,
    published_by: str = "builder", scope: str = "build", own_databases: frozenset[str] | set[str] = frozenset(),
    after_build: Callable[[Path], None] | None = None,
) -> RefreshResult:
    """`own_databases`: nombres (en minúsculas) de la BD de trabajo, que no se cataloga a sí misma.
    `after_build(work_dir)`: paso extra antes de publicar (el modo demo superpone el conocimiento de los fixtures)."""
    work_dir = Path(work_dir)
    previous = None
    if repository is not None:
        loaded = repository.load(scope)
        if loaded is not None:
            write_snapshot(work_dir, loaded[0])
            previous = loaded[1]
    report = build_catalog(inventory, work_dir, source_factory=source_factory, enricher=enricher,
                           exclude_databases=OWN_DATABASES | {name.lower() for name in own_databases})
    result = RefreshResult(report=report, previous_version=previous)
    if not report.servers_ok:
        return result
    if after_build is not None:
        after_build(work_dir)
    if repository is not None:
        result.published = repository.publish(load_snapshot(work_dir), published_by=published_by, reason="build",
                                              scope=scope)
    return result
