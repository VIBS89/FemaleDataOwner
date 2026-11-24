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
from converdata.metadata.ports import MetadataSource, RawObject
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
    kept_from_failed: int = 0  # objetos conservados de servidores que no respondieron en este refresco
    skipped_unsafe: int = 0  # objetos con nombres no admitidos (`.`, `/`, `\\`, `:` o caracteres de control)

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
        if self.kept_from_failed:
            lines.append(f"Objetos conservados de servidores que no respondieron: {self.kept_from_failed}")
        if self.skipped_unsafe:
            lines.append(f"Objetos omitidos por tener nombres no admitidos: {self.skipped_unsafe}")
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


# La BD de trabajo de ConverData no forma parte del patrimonio de datos: no se cataloga a sí misma.
OWN_DATABASES = frozenset({"converdata"})


def build_catalog_graph(
    inventory: Inventory,
    out_dir: Path,
    source_factory: Callable[[ServerConfig], MetadataSource],
    enricher=None,
    exclude_databases: frozenset[str] = OWN_DATABASES,
):
    out_dir = Path(out_dir)
    excluded = {name.lower() for name in exclude_databases}

    def extract(state: BuildState):
        report = state["report"]
        existing = cb.load_existing(out_dir)
        raws: dict[str, RawObject] = {}
        objects: list[CatalogObject] = []
        pending: list[str] = []
        for server in inventory.servers:
            try:
                source = source_factory(server)
                dbs = [db for db in source.list_databases() if db.lower() not in excluded]
                if server.all_databases:
                    server.databases = dbs  # el inventario escrito refleja lo descubierto
                for db in dbs:
                    for raw in source.extract_database(db):
                        if cb.unsafe_name(raw) is not None:  # no entra al catálogo; se cuenta en el informe
                            report.skipped_unsafe += 1
                            continue
                        obj = cb.to_catalog_object(raw, server)
                        known = existing.get(obj.id)
                        merged, needs = cb.merge_existing(obj, known)
                        raws[merged.id] = raw
                        objects.append(merged)
                        if needs and merged.kind in ("table", "view"):
                            pending.append(merged.id)
                        if known is not None and known.schema_hash == obj.schema_hash:
                            report.reused += 1  # misma estructura: se conserva lo anterior (aunque falte describirlo)
                    report.databases.append(f"{server.id}/{db}")
                report.servers_ok.append(server.id)
            except Exception as exc:  # F1-CA5: se sigue con los demás servidores
                log.warning("servidor %s no disponible: %s", server.id, type(exc).__name__)
                report.servers_failed[server.id] = f"{type(exc).__name__}: {str(exc)[:120]}"
                # Un servidor caído no vacía su parte del catálogo: se conserva lo último conocido de ese servidor.
                partial = {o.id for o in objects if o.server == server.id}
                objects = [o for o in objects if o.id not in partial]
                pending = [i for i in pending if i not in partial]
                for known in existing.values():
                    if known.server == server.id:
                        raws.pop(known.id, None)
                        objects.append(known)
                        report.kept_from_failed += 1
        report.objects = len(objects)
        report.columns = sum(len(o.columns) for o in objects)
        return {"raws": raws, "objects": objects, "pending_enrich": pending}

    def enrich(state: BuildState):
        report = state["report"]
        if enricher is None or not state["pending_enrich"]:
            return {}
        by_id = {o.id: o for o in state["objects"]}
        pending = [by_id[i] for i in state["pending_enrich"]]

        def describe(batch) -> list:
            """Pide descripciones para un lote y las aplica. Devuelve los objetos que el modelo no describió."""
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
                return list(batch)
            by_table = {o_.table.split(".")[-1].lower(): o_ for o_ in result.tables}
            missing = []
            for obj in batch:
                proposal = by_table.get(obj.name.lower())
                if proposal is None:
                    missing.append(obj)
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
            return missing

        for start in range(0, len(pending), ENRICH_BATCH):
            # Un modelo puede devolver menos tablas de las pedidas (salida cortada por longitud): las que falten se
            # piden de nuevo una por una, una sola vez. Si siguen sin descripción, quedan para el próximo refresco.
            for obj in describe(pending[start:start + ENRICH_BATCH]):
                describe([obj])
        return {"objects": state["objects"]}

    def relate(state: BuildState):
        entities = cb.detect_entities(state["objects"])
        lineage = cb.view_lineage(state["objects"], state["raws"])
        if state["report"].servers_failed:  # las vistas de un servidor caído no se releyeron: se conserva su linaje
            from converdata.catalog.store import load_knowledge

            kept = {o.asset_key for o in state["objects"] if o.id not in state["raws"]}
            lineage += [e for e in load_knowledge(out_dir / "knowledge").lineage
                        if e.via.kind == "view" and e.to in kept]
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


def build_catalog(
    inventory: Inventory, out_dir: Path, source_factory: Callable[[ServerConfig], MetadataSource], enricher=None,
    exclude_databases: frozenset[str] = OWN_DATABASES,
) -> BuildReport:
    """`source_factory` lo inyecta la raíz de composición: `SqlServerMetadata` en producción, fuentes falsas en tests.

    `exclude_databases`: BDs que no se catalogan aunque el inventario diga `"*"` (por defecto, la BD `ConverData`)."""
    t0 = time.perf_counter()
    report = BuildReport()
    graph = build_catalog_graph(inventory, out_dir, source_factory, enricher, exclude_databases)
    graph.invoke({"report": report})
    report.seconds = time.perf_counter() - t0
    return report
