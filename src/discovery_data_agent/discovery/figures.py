"""Cifras agregadas (primer corte del AskFlow, F3–F8): conteos, sumas y promedios sobre una tabla, con desglose.

Apagado por defecto (`features.ask_flow`). Cuando está activo, una pregunta de cifras ("¿cuántos clientes tienen
préstamos?") se responde con el número además de con la información que lo sustenta. Reglas del diseño:

- **Solo totales.** La consulta es siempre un agregado (`COUNT`, `COUNT DISTINCT`, `SUM`, `AVG`), opcionalmente agrupado
  por una columna de categoría. Nunca se seleccionan filas ni columnas marcadas como dato personal.
- **Sin texto libre en el SQL.** La consulta se arma con una plantilla fija y con nombres tomados del catálogo que el
  usuario puede ver, entre corchetes. Nada de lo que escribe el usuario ni de lo que produce un modelo llega al SQL.
- **Con los permisos del usuario.** La ejecuta quien llama (`FigureExecutor`) con la credencial de la sesión, en solo
  lectura: SQL Server decide si puede leer la tabla.
- **El número no pasa por el LLM.** El texto de la respuesta se arma aquí.
- **Se dice exactamente qué se calculó.** Lo que la pregunta pide y esta versión no aplica (un periodo, un cruce entre
  tablas) se declara en `notes`; no se entrega un número que aparente responderlo.

Este módulo decide *qué* calcular y *cómo decirlo*; no abre conexiones.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from decimal import Decimal

from discovery_data_agent.catalog.ids import short_name, table_key
from discovery_data_agent.catalog.store import Catalog
from discovery_data_agent.discovery import engine
from discovery_data_agent.discovery.deterministic import ENV_LABELS
from discovery_data_agent.memory.text import strip_accents, tokenize
from discovery_data_agent.models.catalog import CatalogObject, Column
from discovery_data_agent.models.discovery import Discovery
from discovery_data_agent.models.figures import Figure, FigureGroup, FigurePlan, FigureQuery

# (id del servidor del inventario, base de datos, SQL) → filas. Lo implementa la integración con la sesión del usuario.
FigureExecutor = Callable[[str, str, str], Sequence[Sequence]]

MAX_GROUPS = 25
# Un total o un grupo calculado sobre menos registros que este umbral no se muestra: con uno o dos registros, la "suma"
# es el saldo de un cliente concreto. Regla de supresión de celdas pequeñas, habitual en estadística.
MIN_ROWS = 10
_IDENT = r"\[(?:[^\]]|\]\])+\]"
_AGG = rf"(?:COUNT_BIG\(\*\)|COUNT_BIG\(DISTINCT {_IDENT}\)|(?:SUM|AVG)\(CAST\({_IDENT} AS decimal\(38, 4\)\)\))"
_SOURCE = rf"{_IDENT}\.{_IDENT}\.{_IDENT}"
# Desglose por un dato de una tabla relacionada: una sola unión, por la llave foránea que declara el catálogo.
_AGG_F = (rf"(?:COUNT_BIG\(\*\)|COUNT_BIG\(DISTINCT f\.{_IDENT}\)"
          rf"|(?:SUM|AVG)\(CAST\(f\.{_IDENT} AS decimal\(38, 4\)\)\))")
_JOINED = rf"{_SOURCE} AS f JOIN {_SOURCE} AS d ON f\.{_IDENT} = d\.{_IDENT}"
# Las únicas formas de consulta que existen. El ejecutor rechaza cualquier otra cosa, venga de donde venga.
ALLOWED_SQL = re.compile(
    rf"^(?:SELECT {_AGG} AS valor, COUNT_BIG\(\*\) AS n FROM {_SOURCE}"
    rf"|SELECT COUNT_BIG\(DISTINCT {_IDENT}\) AS valor FROM {_SOURCE}"
    rf"|SELECT TOP \(25\) {_IDENT} AS grupo, {_AGG} AS valor, COUNT_BIG\(\*\) AS n FROM {_SOURCE} "
    rf"GROUP BY {_IDENT} ORDER BY valor DESC"
    rf"|SELECT COUNT_BIG\(DISTINCT d\.{_IDENT}\) AS valor FROM {_JOINED}"
    rf"|SELECT TOP \(25\) d\.{_IDENT} AS grupo, {_AGG_F} AS valor, COUNT_BIG\(\*\) AS n FROM {_JOINED} "
    rf"GROUP BY d\.{_IDENT} ORDER BY valor DESC) OPTION \(MAXDOP 1\)$")
# Solo se desglosa por una categoría: texto o bit, o un entero que es un código (termina en ID o Codigo). Nunca por una
# medida ("días de mora") ni por algo que nombra a una persona, esté o no marcado como dato personal.
_CATEGORY_TYPE = re.compile(r"^(?:char|varchar|nchar|nvarchar|bit)\b", re.I)
_CODE_TYPE = re.compile(r"^(?:int|smallint|tinyint|bigint)\b", re.I)
_CODE_NAME = re.compile(r"(?:id|codigo|code)$", re.I)
_PERSON_NAME = re.compile(r"cliente|nombre|apellido|razonsocial|documento|dui|nit|gestor|ejecutivo|usuario|titular|"
                          r"email|correo|telefono|direccion", re.I)
APPROXIMATE_NOTE = "Es una cifra informativa calculada ahora: puede variar un poco con operaciones en curso."


def check_sql(sql: str) -> str:
    """El SQL tal cual si es una de las consultas permitidas; `ValueError` si no."""
    if not ALLOWED_SQL.fullmatch(sql):  # fullmatch: `$` aceptaría un salto de línea al final
        raise ValueError("Consulta fuera de la plantilla de cifras agregadas")
    return sql


def is_category(col: Column) -> bool:
    if col.pii or _PERSON_NAME.search(col.name):
        return False
    kind = col.type or ""
    return bool(_CATEGORY_TYPE.match(kind) or (_CODE_TYPE.match(kind) and _CODE_NAME.search(col.name)))
_NUMERIC = re.compile(r"^(?:decimal|numeric|money|smallmoney|int|bigint|smallint|tinyint|float|real)\b", re.I)
_AVG = re.compile(r"\b(promedio|media|en promedio)\b")
_COUNTED = re.compile(r"\b(?:cuant[oa]s|cantidad de|numero de|total de)\s+([a-z]+)")
_GROUP = re.compile(r"\bpor\s+((?:[a-z]+\s+){0,3}[a-z]+)")
_PERIOD = re.compile(
    r"\b(?:ultim[oa]s?|este|esta|pasad[oa]|cierre|hoy|ayer|ano|anos|mes|meses|trimestre|semana|mensual|anual)\b")
_PERIOD_GROUP = {"mes", "ano", "dia", "semana", "trimestre", "semestre", "fecha"}
# Un adjetivo de situación pide un valor de la columna de estado: como el catálogo no guarda valores, se desglosa.
_STATE_WORD = re.compile(r"\b(activ[oa]s?|vigentes?|cancelad[oa]s?|bloquead[oa]s?|vencid[oa]s?|rechazad[oa]s?|"
                         r"aprobad[oa]s?|cerrad[oa]s?|abiert[oa]s?|en mora|moros[oa]s?)\b")
# "…y también tarjeta", "…pero no préstamo": la condición depende de otra tabla; un desglose no la resuelve.
_COMBINES = re.compile(r"\b(y tambien|y ademas|ademas|tambien tienen?|pero no|que no tienen?|sin tener)\b")
_STATE_COLUMN = re.compile(r"^(estado|status|estatus|situacion)$", re.I)


def _q(name: str) -> str:
    """Identificador entre corchetes. El nombre viene del catálogo; el corchete de cierre se duplica."""
    return "[" + name.replace("]", "]]") + "]"


def _norm(text: str) -> str:
    return strip_accents(text).lower()


def _stems(text: str) -> set[str]:
    return set(tokenize(text))


def _column(obj: CatalogObject, name: str) -> Column | None:
    return next((c for c in obj.columns if c.name.lower() == name.lower()), None)


def _match_column(obj: CatalogObject, words: str) -> Column | None:
    """La columna de la tabla que mejor nombra `words` ("tipo de garantia" → `TipoGarantia`, "agencia" → `AgenciaID`)."""
    wanted = _stems(words)
    if not wanted:
        return None
    head = _stems(words.split()[0])  # lo que se pide: "estado de la solicitud" es un estado, no una solicitud
    best, best_score = None, 0.0
    for col in obj.columns:
        tokens = {t for t in _stems(col.name) if t != "id"}
        if not tokens or not (wanted & tokens) or (head and not (head & tokens)):
            continue
        score = len(wanted & tokens) / len(wanted | tokens)
        if score > best_score:
            best, best_score = col, score
    return best


NO_PERIOD = "No calculé la cifra: la pregunta pide un periodo y todavía no aplico filtros de fecha."
NO_CROSS = ("No calculé la cifra: la pregunta combina información de varias tablas o sistemas y todavía solo calculo "
            "sobre una.")
NO_MEASURE = "No calculé la cifra: lo que se pide sumar o promediar no es un dato numérico que pueda agregar."
NO_SUBJECT = "No calculé la cifra: no identifiqué con seguridad qué hay que contar."
NO_AMBIGUOUS = ("No calculé la cifra: hay más de un dato que podría ser el que buscas. Dime cuál de los que te muestro "
                "es y lo calculo.")
AMBIGUOUS_MARGIN = 0.05


def plan_figure(question: str, discovery: Discovery, catalog: Catalog, vis,
                environment: str | None = None) -> FigurePlan | str:
    """El agregado que responde la pregunta sobre la tabla del candidato principal, o el motivo (un texto para el
    usuario) por el que esta versión no lo calcula. Ante la duda no se calcula: un número que aparenta responder y no
    responde es peor que no dar número."""
    if not discovery.candidates or discovery.unresolved_parts:
        return NO_SUBJECT
    top = discovery.candidates[0]
    tkey = table_key(top.asset_key)
    copies = engine.ordered_copies(tkey, catalog, vis, environment)
    if not copies or copies[0].kind not in ("table", "view"):
        return NO_SUBJECT
    obj = copies[0]
    q = _norm(question)
    notes: list[str] = []
    if _PERIOD.search(q):
        return NO_PERIOD
    # Si otro dato de otra tabla responde casi igual de bien, sumar el primero sería adivinar.
    # Una tabla a la que esta apunta (su catálogo de productos, sus clientes) no compite: describe a la principal.
    referenced = {fk.ref for fk in obj.foreign_keys}
    rival = next((c for c in discovery.candidates[1:]
                  if table_key(c.asset_key) not in referenced | {tkey} and c.kind != "view"), None)
    if rival is not None and top.confidence - rival.confidence < AMBIGUOUS_MARGIN:
        return NO_AMBIGUOUS
    # Un camino que pasa por otro sistema o por más de una tabla dice que la pregunta combinaba varias cosas.
    crosses = any(len(p.steps) > 1 or "same_entity" in " ".join(p.steps) for p in discovery.join_paths)
    if crosses and (_COMBINES.search(q) or not _GROUP.search(q)):
        return NO_CROSS

    measure = _column(obj, top.column) if top.kind == "column" and top.column else None
    if measure is not None and (measure.pii or not _NUMERIC.match(measure.type or "")):
        measure = None
    counted = _COUNTED.search(q)
    if measure is not None and not (counted and not engine.query_role(question) == "amount"):
        op = "AVG" if _AVG.search(q) else "SUM"
        target = measure.name
        what = f"{'Promedio' if op == 'AVG' else 'Suma'} de {engine.humanize(measure.name).lower()} en"
    elif measure is None and (not counted or _AVG.search(q)):
        return NO_MEASURE  # se pidió una medida que no se puede sumar (texto, fecha o dato personal)
    else:
        counting = _count(obj, counted.group(1), catalog, vis)
        if counting is None:
            return NO_SUBJECT
        op, target, what = counting
    expr = _aggregate(op, target)

    group = None
    joined = None  # (columna de la llave foránea, tabla relacionada, su llave)
    for match in _GROUP.finditer(q):
        words = match.group(1)
        if _stems(words) & _PERIOD_GROUP:
            notes.append(f"No agrupé por «{words.split()[0]}»: todavía no agrupo por periodos.")
            continue
        related = _related_category(obj, words, catalog, vis) if _names_related(obj, words) else None
        if related is not None:
            group, joined = related[0], related[1:]
            notes.append(_join_note(joined))
            break
        col = _match_column(obj, words)
        if col is not None and is_category(col):
            group = col
            break
        if col is not None:
            notes.append(f"No desglosé por «{words.split()[0]}»: no es una categoría (es una medida o identifica a "
                         "una persona).")
            continue
        related = _related_category(obj, words, catalog, vis)
        if related is not None:
            group, joined = related[0], related[1:]
            notes.append(_join_note(joined))
            break
        notes.append(f"No desglosé por «{words.split()[0]}»: ese dato no está en esta tabla ni en una a la que apunte "
                     "directamente.")
    if group is None and _STATE_WORD.search(q):
        state = next((c for c in obj.columns if _STATE_COLUMN.match(c.name) and is_category(c)), None)
        if state is not None:
            group = state
            notes.append(f"No filtré por «{_STATE_WORD.search(q).group(0)}»: te muestro el desglose por "
                         f"{engine.humanize(state.name).lower()} para que tomes el que corresponde.")

    if crosses and group is None:
        return NO_CROSS  # lo que hacía falta cruzar no era un desglose que esta versión resuelva
    source = f"{_q(obj.database)}.{_q(obj.schema_)}.{_q(obj.name)}"
    tail = "OPTION (MAXDOP 1)"  # un solo procesador: una cifra informativa no compite con la operación
    queries = [FigureQuery(purpose="total", sql=f"SELECT {expr} AS valor, COUNT_BIG(*) AS n FROM {source} {tail}")]
    if group is not None and joined is not None:
        fk_column, dim, dim_key = joined
        dim_source = f"{_q(dim.database)}.{_q(dim.schema_)}.{_q(dim.name)}"
        join = f"{source} AS f JOIN {dim_source} AS d ON f.{_q(fk_column)} = d.{_q(dim_key)}"
        expr_f = _aggregate(op, target, "f.")  # se arma de nuevo con el alias; nunca editando el texto del SQL
        queries.append(FigureQuery(
            purpose="cardinality", sql=f"SELECT COUNT_BIG(DISTINCT d.{_q(group.name)}) AS valor FROM {join} {tail}"))
        queries.append(FigureQuery(
            purpose="groups",
            sql=(f"SELECT TOP ({MAX_GROUPS}) d.{_q(group.name)} AS grupo, {expr_f} AS valor, COUNT_BIG(*) AS n "
                 f"FROM {join} GROUP BY d.{_q(group.name)} ORDER BY valor DESC {tail}"),
        ))
    elif group is not None:
        # Antes de desglosar se cuenta cuántos valores distintos tiene la columna: solo se desglosa por una categoría
        # (pocos valores). Una columna casi única (un documento, un nombre, un número de cuenta) mostraría datos de
        # clientes uno por uno, esté o no marcada como dato personal en el catálogo.
        queries.append(FigureQuery(
            purpose="cardinality", sql=f"SELECT COUNT_BIG(DISTINCT {_q(group.name)}) AS valor FROM {source} {tail}"))
        queries.append(FigureQuery(
            purpose="groups",
            sql=(f"SELECT TOP ({MAX_GROUPS}) {_q(group.name)} AS grupo, {expr} AS valor, COUNT_BIG(*) AS n "
                 f"FROM {source} GROUP BY {_q(group.name)} ORDER BY valor DESC {tail}"),
        ))
    return FigurePlan(
        asset_key=tkey, server=obj.server, database=obj.database, operation=op,
        environment=obj.environment, server_alias=catalog.inventory.alias(obj.server),
        description=f"{what} {engine.humanize(obj.name).lower()}",
        group_by=group.name if group is not None else None,
        queries=queries, notes=notes,
    )


JOIN_NOTE = "El desglose usa"


def _join_note(joined) -> str:
    return (f"{JOIN_NOTE} {engine.humanize(joined[1].name).lower()}, unida por {engine.humanize(joined[0]).lower()}; "
            "no cuenta los registros sin ese dato.")


def _names_related(obj: CatalogObject, words: str) -> bool:
    """¿La frase, después de lo que pide, nombra una tabla a la que `obj` apunta? ("estado de la solicitud")."""
    rest = _stems(" ".join(words.split()[1:]))
    return bool(rest) and any(rest & _stems(short_name(fk.ref)) for fk in obj.foreign_keys)


def _related_category(obj: CatalogObject, words: str, catalog: Catalog, vis):
    """Una categoría que vive en una tabla a la que `obj` apunta por una llave foránea de una sola columna ("saldo de
    préstamos por segmento" → `Clientes.Segmento` por `ClienteID`). Solo tablas que el usuario ve, de la misma base de
    datos, servidor y ambiente. Devuelve (columna de categoría, columna de la llave, tabla relacionada, su llave)."""
    for fk in obj.foreign_keys:
        if len(fk.columns) != 1 or len(fk.ref_columns) != 1:
            continue
        fk_col = _column(obj, fk.columns[0])
        if fk_col is None or fk_col.pii:
            continue
        for dim in catalog.visible_copies(fk.ref, vis):
            if (dim.server, dim.environment, dim.database) != (obj.server, obj.environment, obj.database):
                continue
            col = _match_column(dim, words)
            key = _column(dim, fk.ref_columns[0])
            if col is not None and key is not None and is_category(col):
                return col, fk_col.name, dim, key.name
    return None


def _aggregate(op: str, column: str | None, alias: str = "") -> str:
    """La expresión del agregado sobre `column` (None para contar filas), con el alias de tabla si hay unión."""
    if op == "COUNT":
        return "COUNT_BIG(*)"
    if op == "COUNT_DISTINCT":
        return f"COUNT_BIG(DISTINCT {alias}{_q(column)})"
    return f"{op}(CAST({alias}{_q(column)} AS decimal(38, 4)))"


def _count(obj: CatalogObject, counted: str, catalog: Catalog, vis) -> tuple[str, str | None, str] | None:
    """`COUNT(*)` si se cuenta lo que la tabla guarda; `COUNT(DISTINCT llave)` si se cuenta otra entidad a la que la
    tabla apunta ("cuántos clientes tienen préstamos" sobre `Prestamos` → clientes distintos por `ClienteID`). None si
    lo que se cuenta no es ni la tabla ni algo a lo que apunta."""
    wanted = {s for w in [counted, *_synonyms(counted)] for s in _stems(w)}
    if wanted & _stems(obj.name):
        return "COUNT", None, "Total de"
    for fk in obj.foreign_keys:
        if len(fk.columns) == 1 and catalog.is_visible(fk.ref, vis) and wanted & _stems(short_name(fk.ref)):
            col = _column(obj, fk.columns[0])
            if col is not None and not col.pii:
                return ("COUNT_DISTINCT", col.name,
                        f"{engine.humanize(short_name(fk.ref))} con al menos un registro en")
    return None


def _synonyms(word: str) -> list[str]:
    """"Créditos" cuenta filas de `Prestamos`: el mismo vocabulario que usa la búsqueda."""
    from discovery_data_agent.discovery.expansion import _translations

    return _translations(word)


def run_plan(plan: FigurePlan, executor: FigureExecutor, min_rows: int = MIN_ROWS) -> Figure:
    """Ejecuta el plan con el ejecutor de la sesión y arma la cifra. Las excepciones del ejecutor se propagan.
    `min_rows`: registros mínimos para mostrar un total o un grupo (`discovery.figures_min_rows`)."""
    min_rows = max(min_rows, 5)
    value: float | int | None = None
    total_rows: int | None = None
    groups: list[FigureGroup] = []
    notes = list(plan.notes)
    group_by = plan.group_by
    ran: list[str] = []
    for query in plan.queries:
        if query.purpose == "groups" and group_by is None:
            continue  # la columna no era una categoría: no se desglosa
        rows = executor(plan.server, plan.database, check_sql(query.sql))
        ran.append(query.sql)
        if query.purpose == "total":
            total_rows = int(rows[0][1]) if rows and rows[0][1] is not None else 0
            if total_rows < min_rows:
                # Con tan pocos registros el "total" sería el dato de uno o de unos pocos clientes: no se muestra.
                return Figure(
                    asset_key=plan.asset_key, description=plan.description, operation=plan.operation, value=None,
                    environment=plan.environment, server_alias=plan.server_alias, rows=None, sql=ran,
                    notes=[f"No muestro la cifra: se calcularía sobre menos de {min_rows} registros y podría revelar "
                           "el dato de un cliente."],
                )
            value = _number(rows[0][0])
        elif query.purpose == "cardinality":
            distinct = _number(rows[0][0]) if rows else None
            if distinct is None or distinct > MAX_GROUPS:
                notes = [n for n in notes if not n.startswith(("No filtré", JOIN_NOTE))]
                notes.append(f"No desglosé por {engine.humanize(group_by or '').lower()}: tiene demasiados valores "
                             "distintos para mostrarlos como categorías.")
                group_by = None
        else:
            groups, hidden = _safe_groups(rows[:MAX_GROUPS], min_rows)
            if hidden:
                notes.append(f"Oculté {hidden} grupo{'s' if hidden != 1 else ''} con menos de {min_rows} registros "
                             "para no revelar el dato de un cliente.")
    notes.append(APPROXIMATE_NOTE)
    return Figure(
        asset_key=plan.asset_key, description=plan.description, operation=plan.operation, value=value,
        environment=plan.environment, server_alias=plan.server_alias, rows=total_rows,
        group_by=group_by, groups=groups, notes=notes, sql=ran,
    )


def _safe_groups(rows, min_rows: int = MIN_ROWS) -> tuple[list[FigureGroup], int]:
    """Los grupos que se pueden mostrar y cuántos se ocultaron. Se oculta todo grupo con menos de `MIN_ROWS` registros
    y, si solo se ocultó uno, también el más pequeño de los visibles: de lo contrario el oculto se deduciría restando
    los visibles al total."""
    visible = [r for r in rows if r[2] is not None and int(r[2]) >= min_rows]
    hidden = len(rows) - len(visible)
    if hidden == 1 and visible:
        visible.remove(min(visible, key=lambda r: int(r[2])))
        hidden += 1
    return [FigureGroup(label=_label(r[0]), value=_number(r[1]) or 0) for r in visible], hidden


def _number(raw) -> float | int | None:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return int(raw) if raw == raw.to_integral_value() else float(raw)
    return raw if isinstance(raw, (int, float)) else float(raw)


def _label(raw) -> str:
    return "(sin valor)" if raw is None else str(raw)[:80]


def fmt(value: float | int | None) -> str:
    if value is None:
        return "sin datos"
    return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"


def answer_text(figure: Figure) -> str:
    """Texto de la respuesta. Determinista: la cifra nunca la redacta un modelo."""
    if figure.value is None:
        return " ".join(figure.notes) or "No hay datos para calcular la cifra."
    where = f" (ambiente: {ENV_LABELS.get(figure.environment, figure.environment)})" if figure.environment else ""
    parts = [f"{figure.description}{where}: {fmt(figure.value)}."]
    if figure.groups:
        shown = "; ".join(f"{g.label}: {fmt(g.value)}" for g in figure.groups[:8])
        more = f" (y {len(figure.groups) - 8} más)" if len(figure.groups) > 8 else ""
        parts.append(f"Por {engine.humanize(figure.group_by or '').lower()}: {shown}{more}.")
    parts.extend(figure.notes)
    return " ".join(parts)
