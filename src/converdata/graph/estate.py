"""Grafo del patrimonio de datos (F19) en memoria.

Nodos: tablas y vistas (`asset_key`). Aristas no dirigidas con tipo y detalle:
- `fk`: llave foránea declarada (`on` = columnas);
- `same_entity`: la misma entidad de negocio en otra BD (F19), con su tabla canónica;
- `etl` / `view`: linaje de un salto (F23).

On-premise el mismo modelo vive en tablas de grafo de SQL Server (`NODE`/`EDGE`, `MATCH`, `SHORTEST_PATH`, OP-02);
esta clase es la implementación en memoria que usan el flujo y los tests. Toda consulta recibe `visible_ids`: un camino
nunca atraviesa una tabla que el usuario no puede ver (F14).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from converdata.catalog.ids import is_column_key, short_name, table_key
from converdata.catalog.store import Catalog, KnowledgeBase
from converdata.memory.text import normalized_name

# Al buscar caminos de unión se prefieren las relaciones más fiables (F19): FK > misma entidad > linaje.
EDGE_COST = {"fk": 1.0, "same_entity": 1.5, "etl": 2.5, "view": 2.5}


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    kind: str
    detail: str | None = None

    def other(self, node: str) -> str:
        return self.b if node == self.a else self.a


class EstateGraph:
    def __init__(self, catalog: Catalog, kb: KnowledgeBase):
        self.catalog = catalog
        self._adj: dict[str, list[Edge]] = defaultdict(list)
        self._entity_of: dict[str, tuple[str, str | None]] = {}  # tabla → (entidad, canónica)
        for fk in catalog.fk_edges():
            self._add(Edge(fk.from_table, fk.to_table, "fk", fk.on))
        for e in kb.lineage:
            self._add(Edge(e.from_, e.to, "view" if e.via.kind == "view" else "etl", f"{e.via.kind}:{e.via.name}"))
        for ent in kb.entities:
            for t in ent.tables:
                self._entity_of[t] = (ent.name, ent.canonical)
            canonical = ent.canonical or ent.tables[0]
            for t in ent.tables:
                if t != canonical:
                    self._add(Edge(canonical, t, "same_entity", ent.name))

    def _add(self, edge: Edge) -> None:
        self._adj[edge.a].append(edge)
        self._adj[edge.b].append(edge)

    def _visible(self, table: str, vis) -> bool:
        return self.catalog.is_visible(table, vis)

    # --- entidades ------------------------------------------------------------------------
    def entity_of(self, table: str) -> tuple[str, str | None] | None:
        return self._entity_of.get(table_key(table))

    def entity_signature(self, asset_key: str) -> tuple | None:
        """Firma para agrupar copias: (entidad, columna normalizada). Dos columnas con la misma firma son el mismo dato."""
        ent = self.entity_of(asset_key)
        if ent is None:
            return None
        table = normalized_name(table_key(asset_key).split(".")[-1])
        return (ent[0], table, normalized_name(short_name(asset_key)) if is_column_key(asset_key) else "")

    def copies(self, asset_key: str, vis) -> list[str]:
        """Copias visibles del mismo dato en las otras tablas de la entidad (incluida la propia), canónica primero."""
        ent = self.entity_of(asset_key)
        if ent is None:
            return [asset_key]
        name, canonical = ent
        same_name = normalized_name(table_key(asset_key).split(".")[-1])
        tables = [
            t for t, (n, _) in self._entity_of.items()
            if n == name and normalized_name(t.split(".")[-1]) == same_name and self._visible(t, vis)
        ]
        tables.sort(key=lambda t: (t != canonical, t))
        if not is_column_key(asset_key):
            return tables
        col = normalized_name(short_name(asset_key))
        out = []
        for t in tables:
            obj = self.catalog.visible_copies(t, vis)
            match = next((c.name for c in (obj[0].columns if obj else []) if normalized_name(c.name) == col), None)
            if match:
                out.append(f"{t}.{match}")
        return out or [asset_key]

    def nearby_tables(self, table: str, vis, max_hops: int = 2) -> dict[str, int]:
        """Tablas visibles alcanzables por FK (y misma entidad) en `max_hops` saltos, con su distancia."""
        start = table_key(table)
        dist = {start: 0}
        frontier = [start]
        for hop in range(1, max_hops + 1):
            nxt = []
            for node in frontier:
                for edge in self._adj.get(node, []):
                    if edge.kind not in ("fk", "same_entity"):
                        continue
                    other = edge.other(node)
                    if other not in dist and self._visible(other, vis):
                        dist[other] = hop
                        nxt.append(other)
            frontier = nxt
        dist.pop(start)
        return dist

    # --- caminos ---------------------------------------------------------------------------
    def neighbors(self, table: str, vis) -> list[Edge]:
        return [e for e in self._adj.get(table_key(table), []) if self._visible(e.other(table_key(table)), vis)]

    def join_path(self, source: str, target: str, vis, max_hops: int = 3) -> list[Edge] | None:
        """Camino de menor costo entre dos tablas (Dijkstra sobre pocas aristas), solo por tablas visibles."""
        src, dst = table_key(source), table_key(target)
        if src == dst:
            return []
        if not (self._visible(src, vis) and self._visible(dst, vis)):
            return None
        best: dict[str, float] = {src: 0.0}
        queue: deque[tuple[float, str, list[Edge]]] = deque([(0.0, src, [])])
        found: list[Edge] | None = None
        found_cost = float("inf")
        while queue:
            queue = deque(sorted(queue, key=lambda x: x[0]))
            cost, node, path = queue.popleft()
            if cost >= found_cost or len(path) > max_hops:
                continue
            if node == dst:
                found, found_cost = path, cost
                continue
            for edge in self._adj.get(node, []):
                nxt = edge.other(node)
                if not self._visible(nxt, vis) or len(path) + 1 > max_hops:
                    continue
                new_cost = cost + EDGE_COST.get(edge.kind, 3.0)
                if new_cost < best.get(nxt, float("inf")):
                    best[nxt] = new_cost
                    queue.append((new_cost, nxt, [*path, edge]))
        return found
