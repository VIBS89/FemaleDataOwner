"""Herramientas de descubrimiento de `converdata-mcp` (F12, F19, F22–F24) como funciones con el contexto del usuario.

La API, el chat y el servidor MCP llaman a este mismo código. La identidad (`UserContext`) la pone quien llama a partir
de la sesión autenticada; ninguna herramienta recibe `user_id`, `session_id` ni credenciales como argumento (F14,
OP-03). Todo lo devuelto pasa por `visible_ids`: un activo que el usuario no puede ver responde igual que uno que no
existe, para no revelar su existencia.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from converdata.catalog.ids import is_column_key, short_name, table_key
from converdata.discovery import engine
from converdata.flows.discover import DiscoverService
from converdata.memory.text import normalized_name, tokenize
from converdata.models.catalog import DescriptionSource
from converdata.models.discovery import AnswerEnvelope, JoinPath, Lineage, Location, Owners, Related, RuleRef
from converdata.models.identity import UserContext
from converdata.models.knowledge import LineageVia

MAX_SEARCH_K = 50


class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool = True
    description: str | None = None
    description_source: DescriptionSource = "generated"
    pii: bool = False


class AssetCard(BaseModel):
    """Ficha de un activo (`/assets/{asset_key}`, RF-10). Solo metadatos: nunca valores (F1)."""

    model_config = {"populate_by_name": True}

    asset_key: str
    kind: str  # column | table | view | procedure
    database: str
    schema_: str = Field(alias="schema")
    table: str
    column: str | None = None
    data_type: str | None = None
    description: str | None = None
    description_source: DescriptionSource = "generated"
    domain: str | None = None
    locations: list[Location] = Field(default_factory=list)
    drift_warning: str | None = None
    primary_key: list[str] = Field(default_factory=list)
    columns: list[ColumnInfo] = Field(default_factory=list)  # solo para tablas y vistas
    business_rules: list[RuleRef] = Field(default_factory=list)
    owners: Owners = Field(default_factory=Owners)
    lineage: Lineage = Field(default_factory=Lineage)
    copies: list[str] = Field(default_factory=list)  # el mismo dato en otras BDs (F19)


class AlternativeInfo(BaseModel):
    asset_key: str
    description: str | None = None


class LineageInfo(BaseModel):
    model_config = {"populate_by_name": True}

    from_: str = Field(alias="from")
    to: str
    via: LineageVia


class SearchHit(BaseModel):
    asset_key: str
    kind: str  # table | column
    score: float
    description: str | None = None


class EntityLocation(BaseModel):
    entity: str
    definition: str | None = None
    canonical: str | None = None
    tables: list[str] = Field(default_factory=list)


class DatabaseSummary(BaseModel):
    database: str
    environments: list[str]
    tables: int
    views: int
    procedures: int


class EstateOverview(BaseModel):
    databases: list[DatabaseSummary] = Field(default_factory=list)
    entities: list[EntityLocation] = Field(default_factory=list)


class DiscoveryTools:
    def __init__(self, service: DiscoverService):
        self.service = service

    @property
    def _deps(self):
        return self.service.deps

    # --- 5a ---------------------------------------------------------------------------------
    def discover(self, user: UserContext, question: str, history: list[str] | None = None,
                 client: str = "mcp") -> AnswerEnvelope:
        """DiscoverFlow completo (F22), auditado (F11)."""
        return self.service.run(question, user, history=history, client=client)

    def get_asset(self, user: UserContext, asset_key: str) -> AssetCard | None:
        d = self._deps
        vis = user.visible_ids
        copies = engine.ordered_copies(asset_key, d.catalog, vis)
        if not copies:
            return None
        ref = copies[0]
        column = d.catalog.column(asset_key, vis)[1] if is_column_key(asset_key) else None
        description = column.description if column else ref.description
        source = column.description_source if column else ref.description_source
        graph_copies = d.graph.copies(asset_key, vis) if d.graph is not None else [asset_key]
        return AssetCard(
            asset_key=asset_key,
            kind="column" if column else ref.kind,
            database=ref.database,
            schema=ref.schema_,
            table=ref.name,
            column=column.name if column else None,
            data_type=column.type if column else None,
            description=description,
            description_source=source,
            domain=ref.domain,
            locations=engine.locations_of(copies, d.catalog),
            drift_warning=engine.drift_of(copies),
            primary_key=[] if column else ref.primary_key,
            columns=[] if column else [
                ColumnInfo(name=c.name, type=c.type, nullable=c.nullable, description=c.description,
                           description_source=c.description_source, pii=c.pii)
                for c in ref.columns
            ],
            business_rules=engine.visible_rules(asset_key, d.catalog, d.knowledge, vis),
            owners=engine.owners_of(asset_key, d.owners),
            lineage=engine.visible_lineage(asset_key, d.catalog, d.knowledge, vis),
            copies=[c for c in graph_copies if c != asset_key],
        )

    # --- 5b ---------------------------------------------------------------------------------
    def get_related(self, user: UserContext, asset_key: str) -> list[Related]:
        d = self._deps
        if not d.catalog.is_visible(asset_key, user.visible_ids):
            return []
        return engine.related_for_tables({table_key(asset_key)}, d.catalog, d.knowledge, user.visible_ids)

    def find_alternatives(self, user: UserContext, asset_key: str) -> list[AlternativeInfo]:
        """Columnas visibles con la misma semántica: sinónimo compartido o mismo nombre normalizado (F22 paso 5)."""
        d = self._deps
        vis = user.visible_ids
        out = []
        for key in engine.find_alternatives(asset_key, d.catalog, vis):
            found = d.catalog.column(key, vis)
            out.append(AlternativeInfo(asset_key=key, description=found[1].description if found else None))
        return out

    def list_business_rules(self, user: UserContext, asset_key: str) -> list[RuleRef]:
        d = self._deps
        if not d.catalog.is_visible(asset_key, user.visible_ids):
            return []
        return engine.visible_rules(asset_key, d.catalog, d.knowledge, user.visible_ids)

    def get_lineage(self, user: UserContext, asset_key: str) -> list[LineageInfo]:
        """Aristas ETL a un salto (F23) con el paquete, job o SP que las produce; ambos extremos visibles."""
        d = self._deps
        vis = user.visible_ids
        if not d.catalog.is_visible(asset_key, vis):
            return []
        tkey = table_key(asset_key)
        return [
            LineageInfo(**{"from": e.from_, "to": e.to, "via": e.via})
            for e in d.knowledge.lineage
            if tkey in (e.from_, e.to) and d.catalog.is_visible(e.from_, vis) and d.catalog.is_visible(e.to, vis)
        ]

    # --- 5d: grafo del patrimonio (F19) y catálogo -------------------------------------------
    def search_catalog(self, user: UserContext, query: str, k: int = 10) -> list[SearchHit]:
        """Búsqueda híbrida directa sobre tablas y columnas visibles, sin el DiscoverFlow (no se audita la pregunta)."""
        d = self._deps
        vis = user.visible_ids
        k = max(1, min(k, MAX_SEARCH_K))
        hits = [SearchHit(asset_key=h.asset_key, kind="table", score=h.score)
                for h in d.store.search_tables(query, k=k, visible_ids=vis)]
        hits += [SearchHit(asset_key=h.asset_key, kind="column", score=h.score)
                 for h in d.store.search_columns(query, k=k, visible_ids=vis)]
        hits = [h for h in hits if d.catalog.is_visible(h.asset_key, vis)]
        for h in hits:
            if h.kind == "column":
                found = d.catalog.column(h.asset_key, vis)
                h.description = found[1].description if found else None
            else:
                copies = d.catalog.visible_copies(h.asset_key, vis)
                h.description = copies[0].description if copies else None
        hits.sort(key=lambda h: (-h.score, h.asset_key))
        return hits[:k]

    def where_is(self, user: UserContext, entity: str) -> list[EntityLocation]:
        """Dónde vive una entidad de negocio entre BDs (F19): tablas visibles, canónica primero."""
        d = self._deps
        vis = user.visible_ids
        wanted = set(tokenize(entity))
        out = []
        for ent in d.knowledge.entities:
            names = [ent.name, *ent.synonyms]
            if not any(wanted and wanted <= set(tokenize(n)) or normalized_name(n) == normalized_name(entity)
                       for n in names):
                continue
            tables = [t for t in ent.tables if d.catalog.is_visible(t, vis)]
            if not tables:
                continue  # sin tablas visibles la entidad no se menciona (F14)
            canonical = ent.canonical if ent.canonical in tables else tables[0]
            tables.sort(key=lambda t: (t != canonical, t))
            out.append(EntityLocation(entity=ent.name, definition=ent.definition, canonical=canonical, tables=tables))
        return out

    def find_join_path(self, user: UserContext, source: str, target: str, max_hops: int = 3) -> JoinPath | None:
        """Camino de unión más corto entre dos tablas visibles (FK > misma entidad > linaje), solo por tablas visibles."""
        d = self._deps
        if d.graph is None:
            return None
        edges = d.graph.join_path(table_key(source), table_key(target), user.visible_ids, max_hops=max(1, min(max_hops, 4)))
        if edges is None:
            return None
        return engine.join_path_model(short_name(table_key(target)), source, edges)

    def estate_overview(self, user: UserContext) -> EstateOverview:
        """Resumen de lo que el usuario puede ver: BDs con sus ambientes y conteos, y entidades de negocio."""
        d = self._deps
        vis = user.visible_ids
        summary: dict[str, dict] = {}
        for obj in d.catalog.objects:
            if obj.id not in vis:
                continue
            s = summary.setdefault(obj.database, {"environments": set(), "keys": {"table": set(), "view": set(), "procedure": set()}})
            s["environments"].add(obj.environment)
            s["keys"][obj.kind].add(obj.asset_key)
        dbs = [
            DatabaseSummary(database=db, environments=sorted(s["environments"]), tables=len(s["keys"]["table"]),
                            views=len(s["keys"]["view"]), procedures=len(s["keys"]["procedure"]))
            for db, s in sorted(summary.items())
        ]
        entities = []
        for ent in d.knowledge.entities:
            tables = sorted(t for t in ent.tables if d.catalog.is_visible(t, vis))
            if tables:
                canonical = ent.canonical if ent.canonical in tables else tables[0]
                entities.append(EntityLocation(entity=ent.name, definition=ent.definition, canonical=canonical, tables=tables))
        return EstateOverview(databases=dbs, entities=entities)
