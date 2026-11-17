"""`SqlServerCatalogRepository`: el catálogo y el conocimiento en la BD `ConverData` (OP-02, HU-06, HU-09).

Publicar deja las tablas iguales a la foto (`CatalogSnapshot`) **escribiendo solo lo que cambió**: una segunda
publicación idéntica no toca ninguna fila ni sube la versión, y el historial temporal de `catalog.object`,
`catalog.column`, `knowledge.item` y `knowledge.business_rule` guarda cada versión anterior con `modified_by`.

Reglas:
- Todo ocurre en una transacción bajo un bloqueo de aplicación, así dos procesos (API y Builder) no se pisan.
- `scope="build"` (refrescos del Builder): solo toca lo que el Builder deriva de los metadatos (servidores, objetos,
  columnas, FKs, entidades y linaje). No toca reglas, fragmentos, confirmaciones ni responsables, y una descripción
  `human` o `data_dictionary` que ya está en la BD no se reemplaza (F1, F24 CA3), aunque el Builder haya partido de
  una copia anterior, humana o no.
- `scope="all"` (la API tras una edición de curación, o una importación): la BD queda igual a la foto.
- `expected_version`: quien edita declara sobre qué versión trabajó; si la BD ya va por otra, `StaleCatalog`.
- `load(scope="build")`: el Builder no lee lo curado (las confirmaciones salen de preguntas de usuarios).
- La curación de ConverData-API no publica fotos: escribe filas concretas (`write_descriptions`, `upsert_rule`,
  `delete_rule`, `upsert_golden`), cada una en su transacción y subiendo la versión (puerto `KnowledgeWriter`).
- `inventory()` / `save_inventory()`: el inventario de servidores con sus hosts, que solo escribe la API.
- Nunca hay valores de datos: el modelo `CatalogObject` los rechaza antes de llegar aquí (F1, F17).
"""

from __future__ import annotations

import contextlib
import json
from typing import Callable, Iterable

from converdata.catalog.store import CatalogSnapshot, KnowledgeBase, PublishResult, StaleCatalog
from converdata.curation import DescriptionEdit
from converdata.config import DomainOwners, Inventory, OwnerRef, OwnersDirectory, ServerConfig
from converdata.models.catalog import CatalogObject, Column, ForeignKey
from converdata.models.knowledge import BusinessEntity, BusinessRule, GoldenDiscovery, KnowledgeItem, LineageEdge

PROTECTED_SOURCES = {"human", "data_dictionary"}
LOCK = ("DECLARE @rc int; EXEC @rc = sp_getapplock @Resource = 'converdata_catalog', @LockMode = '{mode}', "
        "@LockOwner = 'Transaction', @LockTimeout = 30000; SELECT @rc")
OBJECT_HUMAN = (8, 9, 10, 12)  # description, description_source, reviewed, synonyms_json en OBJECTS
COLUMN_HUMAN = (5, 6, 7, 8)  # lo mismo en COLUMNS
SERVER_FIELDS = {"id", "alias", "environment", "platform", "is_reference"}


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _order(obj: CatalogObject) -> tuple:
    """El mismo orden en que se leen los archivos del catálogo, para que cargar de la BD o de YAML dé lo mismo."""
    return tuple(p.lower() for p in (obj.environment, obj.server, obj.database, f"{obj.schema_}.{obj.name}.yaml"))


class _Table:
    """Sincroniza una tabla con las filas deseadas. `key` = nº de columnas iniciales que forman la clave."""

    def __init__(self, name: str, columns: list[str], key: int = 1, stamp: bool = False):
        self.name, self.columns, self.key, self.stamp = name, columns, key, stamp

    def current(self, cur) -> dict[tuple, tuple]:
        cur.execute(f"SELECT {', '.join(self.columns)} FROM {self.name}")
        return {tuple(row[:self.key]): tuple(row) for row in cur.fetchall()}

    def sync(self, cur, desired: Iterable[tuple], who: str, counts: dict[str, int], *, delete_missing: bool = True,
             existing: dict[tuple, tuple] | None = None) -> None:
        existing = self.current(cur) if existing is None else existing
        wanted = {tuple(row[:self.key]): tuple(row) for row in desired}
        short = self.name.split(".")[-1].strip("[]")
        where = " AND ".join(f"{c} = ?" for c in self.columns[:self.key])
        stale = [k for k in existing if k not in wanted] if delete_missing else []
        for key in stale:
            cur.execute(f"DELETE FROM {self.name} WHERE {where}", *key)
        new = [row for key, row in wanted.items() if key not in existing]
        if new:
            cols = self.columns + (["modified_by"] if self.stamp else [])
            sql = f"INSERT INTO {self.name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            cur.executemany(sql, [row + ((who,) if self.stamp else ()) for row in new])
        changed = [row for key, row in wanted.items() if key in existing and _differs(existing[key], row)]
        for row in changed:
            sets = [f"{c} = ?" for c in self.columns[self.key:]] + (["modified_by = ?"] if self.stamp else [])
            params = row[self.key:] + ((who,) if self.stamp else ()) + row[:self.key]
            cur.execute(f"UPDATE {self.name} SET {', '.join(sets)} WHERE {where}", *params)
        for action, rows in (("inserted", new), ("updated", changed), ("deleted", stale)):
            if rows:
                counts[f"{short}.{action}"] = counts.get(f"{short}.{action}", 0) + len(rows)


def _differs(old: tuple, new: tuple) -> bool:
    return any(_norm(a) != _norm(b) for a, b in zip(old, new))


def _norm(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


OBJECTS = _Table("catalog.object", [
    "physical_id", "asset_key", "environment", "server_id", "kind", "database_name", "schema_name", "object_name",
    "description", "description_source", "reviewed", "domain", "synonyms_json", "row_count", "primary_key_json",
    "parameters_json", "drift_json", "schema_hash", "deprecated"], stamp=True)
COLUMNS = _Table("catalog.[column]", [
    "physical_id", "column_name", "ordinal", "data_type", "nullable", "description", "description_source", "reviewed",
    "synonyms_json", "low_cardinality", "pii"], key=2, stamp=True)
FOREIGN_KEYS = _Table("catalog.foreign_key", ["physical_id", "ordinal", "columns_json", "ref_asset", "ref_columns_json"], key=2)
SERVERS = _Table("catalog.server", ["server_id", "alias", "environment", "platform", "is_reference", "config_json"])
ITEMS = _Table("knowledge.item", [
    "item_id", "kind", "content", "source", "domain", "linked_assets_json", "allowed_groups_json", "reviewed",
    "redacted"], stamp=True)
RULES = _Table("knowledge.business_rule", [
    "rule_id", "content", "domain", "applies_to_json", "source", "owner", "reviewed"], stamp=True)
ENTITIES = _Table("knowledge.business_entity", [
    "entity_name", "synonyms_json", "definition", "tables_json", "canonical", "domain"])
GOLDEN = _Table("knowledge.golden_discovery", [
    "golden_id", "template", "asset_keys_json", "confirmed_by", "confirmations", "rejected"])
OWNERS = _Table("curation.owners", [
    "domain", "assets_json", "business_owner", "business_group", "technical_owner", "technical_group"])
INVENTORY = _Table("catalog.inventory_server", ["server_id", "position", "config_json"], stamp=True)
LINEAGE_COLUMNS = ["from_asset", "to_asset", "via_kind", "via_name", "via_job", "via_schedule", "edge_level"]


def _object_row(o: CatalogObject) -> tuple:
    return (o.id, o.asset_key, o.environment, o.server, o.kind, o.database, o.schema_, o.name, o.description,
            o.description_source, int(o.reviewed), o.domain, _j(o.synonyms), o.row_count, _j(o.primary_key),
            _j([p.model_dump() for p in o.parameters]), _j([d.model_dump() for d in o.drift]), o.schema_hash,
            int(o.deprecated))


def _column_row(o: CatalogObject, ordinal: int, c: Column) -> tuple:
    return (o.id, c.name, ordinal, c.type, int(c.nullable), c.description, c.description_source, int(c.reviewed),
            _j(c.synonyms), int(c.low_cardinality), int(c.pii))


def _protect(row: tuple, old: tuple | None, fields: tuple[int, int, int, int]) -> tuple:
    """Conserva descripción, fuente, revisado y sinónimos de la BD si allí son humanos.

    También cuando la foto trae otra versión humana: el Builder no escribe descripciones humanas, solo arrastra la que
    leyó al empezar, y entre tanto una persona pudo corregirla."""
    if old is None or old[fields[1]] not in PROTECTED_SOURCES:
        return row
    return tuple(old[i] if i in fields else value for i, value in enumerate(row))


def _lock(cur, mode: str) -> None:
    cur.execute(LOCK.format(mode=mode))
    if cur.fetchone()[0] < 0:
        raise TimeoutError("No se pudo tomar el bloqueo del catálogo: hay otra publicación en curso")


class SqlServerCatalogRepository:
    def __init__(self, connect: Callable[[], object]):
        self._connect = connect

    # --- versión -----------------------------------------------------------------------------------
    def version(self) -> int | None:
        conn = self._connect()
        try:
            row = conn.cursor().execute("SELECT MAX(version) FROM catalog.catalog_version").fetchone()
            return int(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()

    # --- publicar ----------------------------------------------------------------------------------
    def publish(self, snapshot: CatalogSnapshot, *, published_by: str, reason: str, scope: str = "all",
                expected_version: int | None = None) -> PublishResult:
        if scope not in ("all", "build"):
            raise ValueError(f"scope inválido: {scope!r}")
        conn = self._connect()
        counts: dict[str, int] = {}
        try:
            conn.autocommit = False
            cur = conn.cursor()
            _lock(cur, "Exclusive")
            cur.execute("SELECT MAX(version) FROM catalog.catalog_version")
            current = cur.fetchone()[0]
            if expected_version is not None and current is not None and int(current) != expected_version:
                raise StaleCatalog(f"El catálogo va por la versión {current} y se editó sobre la {expected_version}")
            who = published_by[:128]
            self._sync_catalog(cur, snapshot, who, scope == "build", counts)
            self._sync_derived(cur, snapshot.knowledge, who, counts)
            if scope == "all":
                self._sync_curated(cur, snapshot.knowledge, who, counts)
                OWNERS.sync(cur, (self._owner_row(d) for d in snapshot.owners.domains), who, counts)
            changed = bool(counts)
            if changed or current is None:
                cur.execute(
                    "INSERT INTO catalog.catalog_version (published_by, reason, objects, columns) "
                    "OUTPUT INSERTED.version VALUES (?, ?, ?, ?)",
                    who, reason[:60], len(snapshot.objects), sum(len(o.columns) for o in snapshot.objects))
                current = cur.fetchone()[0]
            conn.commit()
            return PublishResult(version=int(current) if current is not None else None, changed=changed, counts=counts)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _sync_catalog(cur, snapshot: CatalogSnapshot, who: str, protect_human: bool, counts: dict[str, int]) -> None:
        SERVERS.sync(cur, (
            (s.id, s.alias, s.environment, s.platform, int(s.is_reference),
             _j(s.model_dump(exclude=SERVER_FIELDS, exclude_defaults=True)))
            for s in snapshot.inventory.servers), who, counts)
        old_objects, old_columns = OBJECTS.current(cur), COLUMNS.current(cur)
        object_rows, column_rows, fk_rows = [], [], []
        for o in snapshot.objects:
            row = _object_row(o)
            object_rows.append(_protect(row, old_objects.get((o.id,)), OBJECT_HUMAN) if protect_human else row)
            for ordinal, c in enumerate(o.columns):
                crow = _column_row(o, ordinal, c)
                column_rows.append(_protect(crow, old_columns.get((o.id, c.name)), COLUMN_HUMAN) if protect_human else crow)
            fk_rows += [(o.id, n, _j(fk.columns), fk.ref, _j(fk.ref_columns)) for n, fk in enumerate(o.foreign_keys)]
        wanted_ids = {(r[0],) for r in object_rows}
        # Hijos antes que padres al borrar, padres antes que hijos al insertar (sin ON DELETE CASCADE: SQL Server 2016).
        FOREIGN_KEYS.sync(cur, [], who, counts, existing={
            k: v for k, v in FOREIGN_KEYS.current(cur).items() if (k[0],) not in wanted_ids})
        COLUMNS.sync(cur, [], who, counts, existing={k: v for k, v in old_columns.items() if (k[0],) not in wanted_ids})
        OBJECTS.sync(cur, object_rows, who, counts, existing=old_objects)
        COLUMNS.sync(cur, column_rows, who, counts,
                     existing={k: v for k, v in old_columns.items() if (k[0],) in wanted_ids})
        FOREIGN_KEYS.sync(cur, fk_rows, who, counts)

    @staticmethod
    def _sync_curated(cur, kb: KnowledgeBase, who: str, counts: dict[str, int]) -> None:
        """Lo que escriben las personas: fragmentos, reglas y confirmaciones."""
        ITEMS.sync(cur, (
            (i.id, i.kind, i.text, i.source, i.domain, _j([link.model_dump() for link in i.linked_assets]),
             _j(i.allowed_groups) if i.allowed_groups is not None else None, int(i.reviewed), int(i.redacted))
            for i in kb.items), who, counts)
        RULES.sync(cur, ((r.id, r.text, r.domain, _j(r.applies_to), r.source, r.owner, int(r.reviewed))
                         for r in kb.rules), who, counts)
        GOLDEN.sync(cur, ((g.id, g.template, _j(g.asset_keys), g.confirmed_by, g.confirmations, int(g.rejected))
                          for g in kb.golden), who, counts)

    @staticmethod
    def _sync_derived(cur, kb: KnowledgeBase, who: str, counts: dict[str, int]) -> None:
        """Lo que el Builder deduce de los metadatos: entidades entre BDs y linaje."""
        ENTITIES.sync(cur, ((e.name, _j(e.synonyms), e.definition, _j(e.tables), e.canonical, e.domain)
                            for e in kb.entities), who, counts)
        wanted = [(e.from_, e.to, e.via.kind, e.via.name, e.via.job, e.via.schedule, e.level) for e in kb.lineage]
        cur.execute(f"SELECT {', '.join(LINEAGE_COLUMNS)} FROM knowledge.lineage_edge ORDER BY edge_id")
        if [tuple(r) for r in cur.fetchall()] != wanted:  # el orden importa y no hay clave natural: se reemplaza entero
            cur.execute("DELETE FROM knowledge.lineage_edge")
            if wanted:
                cur.executemany(
                    f"INSERT INTO knowledge.lineage_edge ({', '.join(LINEAGE_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?)", wanted)
            counts["lineage_edge.replaced"] = len(wanted)

    @staticmethod
    def _owner_row(d: DomainOwners) -> tuple:
        business, technical = d.business_owner, d.technical_owner
        return (d.domain, _j(d.assets), business.name if business else None, business.group if business else None,
                technical.name if technical else None, technical.group if technical else None)

    # --- escrituras puntuales de la curación (puerto `KnowledgeWriter`) -----------------------------
    @contextlib.contextmanager
    def _writing(self):
        """Una transacción bajo el bloqueo del catálogo; se confirma al salir sin error."""
        conn = self._connect()
        try:
            conn.autocommit = False
            cur = conn.cursor()
            _lock(cur, "Exclusive")
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _bump(cur, who: str, reason: str) -> None:
        cur.execute("INSERT INTO catalog.catalog_version (published_by, reason) VALUES (?, ?)", who[:128], reason[:60])

    def write_descriptions(self, edits: list[DescriptionEdit], *, by: str, reason: str) -> int:
        """Escribe cada descripción en su fila; el historial temporal guarda la anterior con su autor (RF-34)."""
        who, changed = by[:128], 0
        with self._writing() as cur:
            for e in edits:
                sets, params = ["description = ?", "description_source = ?", "reviewed = ?", "modified_by = ?"], [
                    e.description, e.source, int(e.reviewed), who]
                if e.synonyms is not None:
                    sets.append("synonyms_json = ?")
                    params.append(_j(list(e.synonyms)))
                if e.column is None:
                    sql, key = f"UPDATE catalog.object SET {', '.join(sets)} WHERE physical_id = ?", [e.physical_id]
                else:
                    sql = f"UPDATE catalog.[column] SET {', '.join(sets)} WHERE physical_id = ? AND column_name = ?"
                    key = [e.physical_id, e.column]
                if e.keep_human:  # otro proceso pudo dejarla como humana después de leer el catálogo
                    sql += " AND description_source <> 'human'"
                cur.execute(sql, *params, *key)
                changed += max(cur.rowcount, 0)
            if changed:
                self._bump(cur, who, reason)
        return changed

    def upsert_rule(self, rule: BusinessRule, *, by: str) -> None:
        who = by[:128]
        row = (rule.text, rule.domain, _j(rule.applies_to), rule.source, rule.owner, int(rule.reviewed), who, rule.id)
        with self._writing() as cur:
            cur.execute("UPDATE knowledge.business_rule SET content = ?, domain = ?, applies_to_json = ?, source = ?, "
                        "owner = ?, reviewed = ?, modified_by = ? WHERE rule_id = ?", *row)
            if cur.rowcount == 0:
                cur.execute("INSERT INTO knowledge.business_rule (content, domain, applies_to_json, source, owner, "
                            "reviewed, modified_by, rule_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", *row)
            self._bump(cur, who, "curation")

    def delete_rule(self, rule_id: str, *, by: str) -> bool:
        with self._writing() as cur:
            cur.execute("DELETE FROM knowledge.business_rule WHERE rule_id = ?", rule_id)
            deleted = cur.rowcount > 0
            if deleted:
                self._bump(cur, by[:128], "curation")
        return deleted

    def upsert_golden(self, golden: GoldenDiscovery, *, by: str, question: str | None = None) -> None:
        """Una confirmación (un voto o la respuesta de un responsable). `question` es el texto original (D2): va al
        esquema `golden`, solo la primera vez, y nunca al índice."""
        row = (golden.template, _j(golden.asset_keys), golden.confirmed_by, golden.confirmations, int(golden.rejected),
               golden.id)
        with self._writing() as cur:
            cur.execute("UPDATE knowledge.golden_discovery SET template = ?, asset_keys_json = ?, confirmed_by = ?, "
                        "confirmations = ?, rejected = ? WHERE golden_id = ?", *row)
            if cur.rowcount == 0:
                cur.execute("INSERT INTO knowledge.golden_discovery (template, asset_keys_json, confirmed_by, "
                            "confirmations, rejected, golden_id) VALUES (?, ?, ?, ?, ?, ?)", *row)
            if question:
                cur.execute("INSERT INTO golden.golden_discovery_original (golden_id, question) SELECT ?, ? "
                            "WHERE NOT EXISTS (SELECT 1 FROM golden.golden_discovery_original WHERE golden_id = ?)",
                            golden.id, question[:2000], golden.id)
            self._bump(cur, by[:128], "feedback")

    # --- inventario de servidores (con hosts; `catalog.server` es la copia sin ellos) --------------
    def inventory(self) -> list[ServerConfig]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT config_json FROM catalog.inventory_server ORDER BY position, server_id")
            return [ServerConfig.model_validate(json.loads(row[0])) for row in cur.fetchall()]
        finally:
            conn.close()

    def save_inventory(self, servers: list[ServerConfig], *, by: str) -> None:
        rows = [(s.id, n, _j(s.model_dump(exclude_none=True))) for n, s in enumerate(servers)]
        with self._writing() as cur:
            INVENTORY.sync(cur, rows, by[:128], {})

    # --- cargar ------------------------------------------------------------------------------------
    def load(self, scope: str = "all") -> tuple[CatalogSnapshot, int] | None:
        """La foto vigente y su versión, leídas en una sola transacción; None si nunca se publicó un catálogo.

        Con `scope="build"` trae solo lo que el Builder necesita y puede leer: catálogo, entidades y linaje."""
        if scope not in ("all", "build"):
            raise ValueError(f"scope inválido: {scope!r}")
        conn = self._connect()
        try:
            conn.autocommit = False
            cur = conn.cursor()
            _lock(cur, "Shared")  # ninguna publicación a medias: se lee una versión completa
            cur.execute("SELECT MAX(version) FROM catalog.catalog_version")
            version = cur.fetchone()[0]
            if version is None:
                return None
            curated = scope == "all"
            snapshot = CatalogSnapshot(
                inventory=self._load_inventory(cur), objects=self._load_objects(cur),
                knowledge=self._load_knowledge(cur, curated),
                owners=self._load_owners(cur) if curated else OwnersDirectory())
            return snapshot, int(version)
        finally:
            conn.rollback()
            conn.close()

    @staticmethod
    def _load_inventory(cur) -> Inventory:
        cur.execute("SELECT server_id, alias, environment, platform, is_reference, config_json FROM catalog.server ORDER BY server_id")
        return Inventory(servers=[
            ServerConfig(id=sid, alias=alias, environment=env, platform=platform, is_reference=bool(ref), **json.loads(cfg))
            for sid, alias, env, platform, ref, cfg in cur.fetchall()])

    @staticmethod
    def _load_objects(cur) -> list[CatalogObject]:
        cur.execute(f"SELECT {', '.join(COLUMNS.columns)} FROM catalog.[column] ORDER BY physical_id, ordinal")
        columns: dict[str, list[Column]] = {}
        for pid, name, _ordinal, data_type, nullable, description, source, reviewed, synonyms, low, pii in cur.fetchall():
            columns.setdefault(pid, []).append(Column(
                name=name, type=data_type, nullable=bool(nullable), description=description, description_source=source,
                reviewed=bool(reviewed), synonyms=json.loads(synonyms), low_cardinality=bool(low), pii=bool(pii)))
        cur.execute(f"SELECT {', '.join(FOREIGN_KEYS.columns)} FROM catalog.foreign_key ORDER BY physical_id, ordinal")
        fks: dict[str, list[ForeignKey]] = {}
        for pid, _ordinal, cols, ref, ref_cols in cur.fetchall():
            fks.setdefault(pid, []).append(ForeignKey(columns=json.loads(cols), ref=ref, ref_columns=json.loads(ref_cols)))
        cur.execute(f"SELECT {', '.join(OBJECTS.columns)} FROM catalog.object")
        objects = [
            CatalogObject(
                id=pid, asset_key=asset_key, environment=env, server=server, kind=kind, database=database,
                schema=schema, name=name, description=description, description_source=source, reviewed=bool(reviewed),
                domain=domain, synonyms=json.loads(synonyms), row_count=row_count, primary_key=json.loads(pk),
                parameters=json.loads(parameters), drift=json.loads(drift), schema_hash=schema_hash,
                deprecated=bool(deprecated), columns=columns.get(pid, []), foreign_keys=fks.get(pid, []))
            for (pid, asset_key, env, server, kind, database, schema, name, description, source, reviewed, domain,
                 synonyms, row_count, pk, parameters, drift, schema_hash, deprecated) in cur.fetchall()
        ]
        return sorted(objects, key=_order)

    @staticmethod
    def _load_knowledge(cur, curated: bool = True) -> KnowledgeBase:
        kb = KnowledgeBase()
        cur.execute(f"SELECT {', '.join(LINEAGE_COLUMNS)} FROM knowledge.lineage_edge ORDER BY edge_id")
        kb.lineage = [
            LineageEdge.model_validate({"from": src, "to": dst, "level": level,
                                        "via": {"kind": kind, "name": name, "job": job, "schedule": schedule}})
            for src, dst, kind, name, job, schedule, level in cur.fetchall()]
        cur.execute(f"SELECT {', '.join(ENTITIES.columns)} FROM knowledge.business_entity ORDER BY entity_name")
        kb.entities = [
            BusinessEntity(name=name, synonyms=json.loads(synonyms), definition=definition, tables=json.loads(tables),
                           canonical=canonical, domain=domain)
            for name, synonyms, definition, tables, canonical, domain in cur.fetchall()]
        if not curated:
            return kb
        cur.execute(f"SELECT {', '.join(ITEMS.columns)} FROM knowledge.item ORDER BY item_id")
        kb.items = [
            KnowledgeItem(id=iid, kind=kind, text=content, source=source, domain=domain,
                          linked_assets=json.loads(links), allowed_groups=json.loads(groups) if groups else None,
                          reviewed=bool(reviewed), redacted=bool(redacted))
            for iid, kind, content, source, domain, links, groups, reviewed, redacted in cur.fetchall()]
        cur.execute(f"SELECT {', '.join(RULES.columns)} FROM knowledge.business_rule ORDER BY rule_id")
        kb.rules = [
            BusinessRule(id=rid, text=content, domain=domain, applies_to=json.loads(applies), source=source,
                         owner=owner, reviewed=bool(reviewed))
            for rid, content, domain, applies, source, owner, reviewed in cur.fetchall()]
        cur.execute(f"SELECT {', '.join(GOLDEN.columns)} FROM knowledge.golden_discovery ORDER BY golden_id")
        kb.golden = [
            GoldenDiscovery(id=gid, template=template, asset_keys=json.loads(keys), confirmed_by=by,
                            confirmations=confirmations, rejected=bool(rejected))
            for gid, template, keys, by, confirmations, rejected in cur.fetchall()]
        return kb

    @staticmethod
    def _load_owners(cur) -> OwnersDirectory:
        cur.execute(f"SELECT {', '.join(OWNERS.columns)} FROM curation.owners ORDER BY domain")
        return OwnersDirectory(domains=[
            DomainOwners(domain=domain, assets=json.loads(assets),
                         business_owner=OwnerRef(name=b_name, group=b_group or "") if b_name else None,
                         technical_owner=OwnerRef(name=t_name, group=t_group or "") if t_name else None)
            for domain, assets, b_name, b_group, t_name, t_group in cur.fetchall()])

    # --- historial ---------------------------------------------------------------------------------
    def description_history(self, asset_key: str) -> list[dict]:
        """Versiones de la descripción de una tabla o columna en orden cronológico, de todas sus copias físicas,
        incluidas las que ya no existen (RF-34). La última fila es el cambio más reciente.

        El historial temporal guarda una versión por cada cambio de la fila, también los que no tocan la descripción
        (un refresco que actualiza el número de filas). Esas versiones se funden con la anterior: cada entrada es un
        cambio real de la descripción, con quien lo hizo y desde cuándo, no con quien tocó la fila después."""
        parts = asset_key.split(".")
        table, column = ".".join(parts[:3]), ".".join(parts[3:]) or None
        conn = self._connect()
        try:
            cur = conn.cursor()
            if column is None:
                cur.execute(
                    "SELECT physical_id, description, description_source, modified_by, valid_from, valid_to "
                    "FROM catalog.object FOR SYSTEM_TIME ALL WHERE asset_key = ? ORDER BY valid_from, physical_id", table)
            else:
                cur.execute(
                    "SELECT c.physical_id, c.description, c.description_source, c.modified_by, c.valid_from, c.valid_to "
                    "FROM catalog.[column] FOR SYSTEM_TIME ALL c WHERE c.column_name = ? AND c.physical_id IN "
                    "(SELECT physical_id FROM catalog.object FOR SYSTEM_TIME ALL WHERE asset_key = ?) "
                    "ORDER BY c.valid_from, c.physical_id", column, table)
            versions: list[dict] = []
            latest: dict[str, dict] = {}  # copia física → su última versión distinta
            for pid, description, source, who, start, end in cur.fetchall():
                previous = latest.get(pid)
                if previous and (previous["description"], previous["description_source"]) == (description, source) \
                        and previous["valid_to"] == start:
                    previous["valid_to"] = end  # misma descripción, sin interrupción: sigue siendo la misma versión
                    continue
                latest[pid] = {"physical_id": pid, "description": description, "description_source": source,
                               "modified_by": who, "valid_from": start, "valid_to": end}
                versions.append(latest[pid])
            for version in versions:  # la fila vigente de una tabla temporal termina en el año 9999
                if version["valid_to"].year >= 9999:
                    version["valid_to"] = None
            return versions
        finally:
            conn.close()
