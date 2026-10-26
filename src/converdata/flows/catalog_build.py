"""CatalogBuildFlow: el agente que descubre los esquemas con su acceso y construye el catálogo (F1, F18, F19).

    START → extract → enrich → relate → write → END

- Inventario: `config/databases.yaml`; `databases: ["*"]` = todas las BDs que el login de metadatos ve.
- `extract`: `converdata-discovery` (consultas fijas sobre sys.*); un servidor caído no detiene a los demás (F1-CA5).
- `enrich`: descripciones y sinónimos con el rol `planner` por lotes (marcados `generated`); sin LLM, solo reglas.
  Los objetos sin cambios de estructura no se vuelven a enriquecer (F1-CA2).
- `relate`: entidades entre BDs (F19) y linaje de vistas (F23).
- `write`: formato lógico de F1 en un directorio que el DiscoverFlow carga directamente.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from converdata.builder import catalog_builder as cb
from converdata.config import Inventory, ServerConfig
from converdata.metadata.sqlserver import MetadataSource, RawObject, SqlServerMetadata
from converdata.models.catalog import CatalogObject

log = logging.getLogger(__name__)
ENRICH_BATCH = 6


@dataclass
class BuildReport:
    servers_ok: list[str] = field(default_factory=list)
    servers_failed: dict[str, str] = field(default_factory=dict)
    databases: list[str] = field(default_factory=list)
    objects: int = 0
    columns: int = 0
    reused: int = 0
    enriched: int = 0
    enrich_errors: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    lineage_edges: int = 0
    files_written: int = 0
    seconds: float = 0.0

    def render(self) -> str:
        lines = [
            f"Servidores: {', '.join(self.servers_ok) or '—'}"
            + (f" · fallidos: {self.servers_failed}" if self.servers_failed else ""),
            f"BDs: {', '.join(self.databases)}",
            f"Objetos: {self.objects} · columnas: {self.columns} · reutilizados sin cambios: {self.reused}"
            f" · enriquecidos con LLM: {self.enriched}",
            f"Entidades entre BDs: {', '.join(self.entities) or '—'} · aristas de linaje: {self.lineage_edges}",
            f"Archivos escritos: {self.files_written} · {self.seconds:.1f} s",
        ]
        if self.enrich_errors:
            lines.append(f"Avisos de enriquecimiento: {len(self.enrich_errors)} (primero: {self.enrich_errors[0]})")
        return "\n".join(lines)


class BuildState(TypedDict, total=False):
    raws: dict[str, RawObject]
    objects: list[CatalogObject]
    pending_enrich: list[str]
    entities: list
    lineage: list
    report: BuildReport


def build_catalog_graph(
    inventory: Inventory,
    out_dir: Path,
    source_factory: Callable[[ServerConfig], MetadataSource] = SqlServerMetadata,
    enricher=None,
):
    out_dir = Path(out_dir)

    def extract(state: BuildState):
        report = state["report"]
        existing = cb.load_existing(out_dir)
        raws: dict[str, RawObject] = {}
        objects: list[CatalogObject] = []
        pending: list[str] = []
        for server in inventory.servers:
            try:
                source = source_factory(server)
                dbs = source.list_databases()
                if server.all_databases:
                    server.databases = dbs  # el inventario escrito refleja lo descubierto
                for db in dbs:
                    for raw in source.extract_database(db):
                        obj = cb.to_catalog_object(raw, server)
                        merged, needs = cb.merge_existing(obj, existing.get(obj.id))
                        raws[merged.id] = raw
                        objects.append(merged)
                        if needs and merged.kind in ("table", "view"):
                            pending.append(merged.id)
                        elif not needs:
                            report.reused += 1
                    report.databases.append(f"{server.id}/{db}")
                report.servers_ok.append(server.id)
            except Exception as exc:  # F1-CA5: se sigue con los demás servidores
                log.warning("servidor %s no disponible: %s", server.id, type(exc).__name__)
                report.servers_failed[server.id] = f"{type(exc).__name__}: {str(exc)[:120]}"
        report.objects = len(objects)
        report.columns = sum(len(o.columns) for o in objects)
        return {"raws": raws, "objects": objects, "pending_enrich": pending}

    def enrich(state: BuildState):
        report = state["report"]
        if enricher is None or not state["pending_enrich"]:
            return {}
        by_id = {o.id: o for o in state["objects"]}
        pending = [by_id[i] for i in state["pending_enrich"]]
        for start in range(0, len(pending), ENRICH_BATCH):
            batch = pending[start:start + ENRICH_BATCH]
            payload = [
                {
                    "table": f"{o.database}.{o.schema_}.{o.name}",
                    "kind": o.kind,
                    "primary_key": o.primary_key,
                    "foreign_keys": [f"{', '.join(fk.columns)} → {fk.ref}" for fk in o.foreign_keys],
                    "columns": [{"name": c.name, "type": c.type} for c in o.columns],
                }
                for o in batch
            ]
            try:
                result = enricher.enrich(payload)
            except Exception as exc:
                report.enrich_errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
                continue
            by_table = {o_.table.split(".")[-1].lower(): o_ for o_ in result.tables}
            for obj in batch:
                proposal = by_table.get(obj.name.lower())
                if proposal is None:
                    continue
                if obj.description_source == "generated" and not obj.description:
                    obj.description = proposal.description.strip()[:500]
                    obj.synonyms = list(dict.fromkeys([*obj.synonyms, *proposal.synonyms]))[:8]
                cols = {c.name.lower(): c for c in proposal.columns}
                for col in obj.columns:  # solo columnas que existen; nunca pisa descripciones de otra fuente
                    p = cols.get(col.name.lower())
                    if p and col.description_source == "generated" and not col.description:
                        col.description = p.description.strip()[:300]
                        col.synonyms = list(dict.fromkeys([*col.synonyms, *p.synonyms]))[:8]
                report.enriched += 1
        return {"objects": state["objects"]}

    def relate(state: BuildState):
        entities = cb.detect_entities(state["objects"])
        lineage = cb.view_lineage(state["objects"], state["raws"])
        state["report"].entities = [f"{e.name} ({len(e.tables)} BDs)" for e in entities]
        state["report"].lineage_edges = len(lineage)
        return {"entities": entities, "lineage": lineage}

    def write(state: BuildState):
        written = cb.write_output(out_dir, inventory, state["objects"], state["entities"], state["lineage"])
        state["report"].files_written = len(written)
        return {}

    g = StateGraph(BuildState)
    g.add_node("extract", extract)
    g.add_node("enrich", enrich)
    g.add_node("relate", relate)
    g.add_node("write", write)
    g.add_edge(START, "extract")
    g.add_edge("extract", "enrich")
    g.add_edge("enrich", "relate")
    g.add_edge("relate", "write")
    g.add_edge("write", END)
    return g.compile()


def build_catalog(inventory: Inventory, out_dir: Path, source_factory=SqlServerMetadata, enricher=None) -> BuildReport:
    t0 = time.perf_counter()
    report = BuildReport()
    graph = build_catalog_graph(inventory, out_dir, source_factory, enricher)
    graph.invoke({"report": report})
    report.seconds = time.perf_counter() - t0
    return report
