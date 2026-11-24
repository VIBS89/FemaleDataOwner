"""AskFlow (F6–F10): responde con el dato pedido, ejecutando la consulta con los permisos del propio usuario.

    descubrimiento (dónde vive el dato) → esquema de la base → planner (LLM) → validador (F7) → ejecutor (F8)
                                                                 ▲                                  │
                                                                 └──── corrección (máx. 3 intentos) ┘
                                                                                                    ▼
                                                                         frase con las cifras reales (F10)

Garantías:
- El LLM ve solo estructura (tablas, columnas, tipos, descripciones) y los valores de columnas categóricas que no son
  personales (estados, tipos, categorías). Nunca ve el resultado: escribe la frase con marcadores que se rellenan aquí,
  así que no puede inventar cifras (F10-CA1).
- La consulta pasa el validador antes de llegar a SQL Server y corre con el login del usuario (F8): SQL Server decide
  qué puede leer.
"""

from __future__ import annotations

import datetime as dt
import decimal
import re
import time
from dataclasses import dataclass, field

from discovery_data_agent.ask.ports import (QueryExecutor, QueryRejected, QueryResult, QuestionInterpretation,
                                  QuestionInterpreter, SqlPlan, SqlPlanner)
from discovery_data_agent.ask.validator import ValidationError, validate
from discovery_data_agent.catalog.ids import table_key
from discovery_data_agent.catalog.store import Catalog
from discovery_data_agent.models.catalog import CatalogObject, Column
from discovery_data_agent.models.discovery import DataAnswer, Discovery
from discovery_data_agent.models.identity import UserContext

MAX_ATTEMPTS = 3
MAX_TABLES = 15
MAX_SAMPLED_COLUMNS = 25
MAX_CATEGORY_VALUES = 30
# Columnas que pueden identificar a una persona o un producto concreto: nunca se leen sus valores para el LLM.
PERSONAL = re.compile(
    r"nombre|apellido|email|correo|telefono|celular|dui|nit|pasaporte|documento|direccion|domicilio|cuenta|tarjeta|"
    r"numero|iban|clabe|token|password|clave|usuario|login|ip|referencia|comentario|observacion|nota|descripcion",
    re.I,
)
MAX_DATE_COLUMNS = 4
PROBE_TTL_S = 1800  # 30 min
MAX_OVERVIEW_TABLES = 300  # el intérprete ve el catálogo visible resumido (solo nombres y descripciones)
MAX_OVERVIEW_COLUMNS = 25
DATE_TYPE = re.compile(r"^(date|datetime|datetime2|smalldatetime|datetimeoffset)\b", re.I)
TEXT_TYPE = re.compile(r"^(n?(var)?char)\((\d+|max)\)$", re.I)
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class AskOutcome:
    ok: bool
    text: str = ""
    data: DataAnswer | None = None
    attempts: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # para la auditoría (nunca valores)


def _is_category(column: Column) -> bool:
    m = TEXT_TYPE.match(column.type.replace(" ", ""))
    if not m or column.pii or PERSONAL.search(column.name):
        return False
    size = m.group(3)
    return size != "max" and int(size) <= 60


def _q(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


class AskEngine:
    def __init__(self, planner: SqlPlanner, catalog: Catalog, max_rows: int = 1000,
                 interpreter: QuestionInterpreter | None = None):
        self.planner, self.catalog, self.max_rows = planner, catalog, max_rows
        self.interpreter = interpreter
        # Valores de categorías y rangos de fechas: cambian poco y cada sondeo es una consulta al servidor.
        self._probes: dict[tuple[str, str, str], tuple[float, QueryResult]] = {}

    def _probe(self, executor: QueryExecutor, obj: CatalogObject, sql: str, max_rows: int) -> QueryResult:
        """Sondeo para el planner (se audita, no cuenta para el tope diario), con caché de `PROBE_TTL_S`."""
        key = (obj.server, obj.database, sql)
        hit = self._probes.get(key)
        if hit and time.monotonic() - hit[0] < PROBE_TTL_S:
            return hit[1]
        result = executor.run(obj.server, obj.database, sql, max_rows, probe=True)
        self._probes[key] = (time.monotonic(), result)
        return result

    # --- interpretación con LLM (sin listas de palabras clave) ------------------------------
    def overview(self, user: UserContext) -> str:
        """Tablas y vistas visibles para el usuario, con su descripción y columnas: solo metadatos."""
        lines: list[str] = []
        for key in sorted(self.catalog.table_keys()):
            copies = self.catalog.visible_copies(key, user.visible_ids)
            if not copies or copies[0].kind not in ("table", "view"):
                continue
            obj = copies[0]
            cols = ", ".join(c.name for c in obj.columns[:MAX_OVERVIEW_COLUMNS])
            desc = f" — {obj.description}" if obj.description else ""
            lines.append(f"{key}{desc} [{cols}]")
            if len(lines) >= MAX_OVERVIEW_TABLES:
                break
        return "\n".join(lines)

    def interpret(self, question: str, history: list[str], user: UserContext) -> QuestionInterpretation | None:
        if self.interpreter is None:
            return None
        return self.interpreter.interpret(question, history, self.overview(user), f"{dt.date.today():%d/%m/%Y}")

    # --- contexto -------------------------------------------------------------------------
    def tables_for(self, discovery: Discovery, user: UserContext, hints: list[str] | None = None,
                   chosen: list[str] | None = None) -> list[CatalogObject]:
        """Las tablas de la base del candidato principal: primero las del descubrimiento, luego el resto visible.

        `hints` son los activos mejor puntuados de la búsqueda: cuando la pregunta trae palabras que no son del
        catálogo ("en los últimos 3 meses") ningún activo llega al umbral de recomendación, pero para calcular el dato
        basta con saber en qué base está; el planner recibe después todas sus tablas."""
        preferred = [table_key(c.asset_key) for c in discovery.candidates]
        preferred += [k for r in discovery.related for k in (r.from_, r.to)]
        preferred += [table_key(h) for h in hints or []]
        if chosen:  # las tablas que eligió el intérprete van primero y fijan la base
            preferred = [table_key(k) for k in chosen] + preferred
        visible = [k for k in preferred if self.catalog.is_visible(k, user.visible_ids)]
        if not visible:
            return []
        database = visible[0].split(".")[0]
        objects: list[CatalogObject] = []
        seen: set[str] = set()
        for key in preferred + sorted(self.catalog.table_keys()):
            key = table_key(key)
            if key in seen or not key.lower().startswith(database.lower() + "."):
                continue
            seen.add(key)
            copies = self.catalog.visible_copies(key, user.visible_ids)
            if copies and copies[0].kind in ("table", "view"):
                objects.append(copies[0])
            if len(objects) >= MAX_TABLES:
                break
        return objects

    def category_values(self, objects: list[CatalogObject], executor: QueryExecutor) -> dict[tuple[str, str], list[str]]:
        values: dict[tuple[str, str], list[str]] = {}
        sampled = 0
        for obj in objects:
            for col in obj.columns:
                if sampled >= MAX_SAMPLED_COLUMNS or not _is_category(col):
                    continue
                sampled += 1
                sql = (f"SELECT TOP ({MAX_CATEGORY_VALUES + 1}) {_q(col.name)} AS valor, COUNT(*) AS n "
                       f"FROM {_q(obj.database)}.{_q(obj.schema_)}.{_q(obj.name)} "
                       f"WHERE {_q(col.name)} IS NOT NULL GROUP BY {_q(col.name)} ORDER BY COUNT(*) DESC")
                try:
                    result = self._probe(executor, obj, sql, MAX_CATEGORY_VALUES + 1)
                except QueryRejected:
                    continue
                if 0 < len(result.rows) <= MAX_CATEGORY_VALUES:
                    values[(obj.asset_key, col.name)] = [str(r[0]) for r in result.rows]
        return values

    def date_ranges(self, objects: list[CatalogObject], executor: QueryExecutor) -> dict[tuple[str, str], str]:
        """Fecha mínima y máxima de cada columna de fecha: el planner sabe hasta cuándo llegan los datos y puede
        avisar si "los últimos 3 meses" caen fuera de ese rango."""
        ranges: dict[tuple[str, str], str] = {}
        for obj in objects:
            dates = [c for c in obj.columns if DATE_TYPE.match(c.type) and not c.pii][:MAX_DATE_COLUMNS]
            if not dates:
                continue
            select = ", ".join(f"MIN({_q(c.name)}), MAX({_q(c.name)})" for c in dates)
            sql = f"SELECT {select} FROM {_q(obj.database)}.{_q(obj.schema_)}.{_q(obj.name)}"
            try:
                row = self._probe(executor, obj, sql, 1).rows[0]
            except (QueryRejected, IndexError):
                continue
            if len(row) != 2 * len(dates):
                continue
            for i, col in enumerate(dates):
                low, high = row[2 * i], row[2 * i + 1]
                if low is not None:
                    ranges[(obj.asset_key, col.name)] = f"{format_value(low)} a {format_value(high)}"
        return ranges

    def schema_text(self, objects: list[CatalogObject], values: dict[tuple[str, str], list[str]],
                    ranges: dict[tuple[str, str], str] | None = None) -> str:
        ranges = ranges or {}
        lines: list[str] = []
        for obj in objects:
            head = f"[{obj.database}].[{obj.schema_}].[{obj.name}]"
            if obj.description:
                head += f" — {obj.description}"
            if obj.row_count is not None:
                head += f" (~{obj.row_count} filas)"
            lines.append(head)
            fks = {c: fk.ref for fk in obj.foreign_keys for c in fk.columns}
            for col in obj.columns:
                line = f"  - {col.name} {col.type}"
                if col.name in obj.primary_key:
                    line += " PK"
                if col.name in fks:
                    line += f" → {fks[col.name]}"
                if col.description:
                    line += f": {col.description}"
                if (obj.asset_key, col.name) in values:
                    line += " | valores: " + ", ".join(values[(obj.asset_key, col.name)])
                if (obj.asset_key, col.name) in ranges:
                    line += " | datos de " + ranges[(obj.asset_key, col.name)]
                lines.append(line)
        return "\n".join(lines)

    def _key(self, name: str) -> str | None:
        """Nombre que devolvió el LLM → asset_key del catálogo (sin distinguir mayúsculas ni corchetes)."""
        clean = name.replace("[", "").replace("]", "").strip().lower()
        return next((k for k in self.catalog.table_keys() if k.lower() == clean), None)

    # --- ejecución ------------------------------------------------------------------------
    def run(self, question: str, discovery: Discovery, user: UserContext, executor: QueryExecutor,
            hints: list[str] | None = None, interpretation: QuestionInterpretation | None = None) -> AskOutcome:
        chosen = [self._key(t) for t in interpretation.tables] if interpretation else []
        objects = self.tables_for(discovery, user, hints, [k for k in chosen if k])
        refined = interpretation.refined_question.strip() if interpretation else ""
        if refined and refined != question.strip():
            question = f"{question}\n(Interpretación: {refined})"
        if not objects:
            return AskOutcome(False, notes=["No encontré una tabla a la que tengas acceso para calcular el dato."])
        server = objects[0].server
        schema = self.schema_text(objects, self.category_values(objects, executor), self.date_ranges(objects, executor))
        schema = f"Fecha de hoy: {dt.date.today():%d/%m/%Y}\n\n{schema}"
        feedback: list[str] = []
        outcome = AskOutcome(False)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            outcome.attempts = attempt
            plan: SqlPlan = self.planner.plan(question, schema, feedback)
            try:
                checked = validate(plan.sql, plan.database or objects[0].database, self.catalog, user.visible_ids,
                                   self.max_rows)
            except ValidationError as exc:
                feedback = [f"[{exc.stage}] {exc}", f"SQL: {plan.sql}"]
                outcome.errors.append(f"validacion:{exc.stage}")
                continue
            try:
                result = executor.run(server, checked.database, checked.sql, self.max_rows)
            except QueryRejected as exc:
                outcome.errors.append("ejecucion")
                if not exc.retry:
                    outcome.notes.append(str(exc))
                    return outcome
                feedback = [f"SQL Server rechazó la consulta: {exc}", f"SQL: {checked.sql}"]
                continue
            text = fill_answer(plan.answer_template, result, question, plan.list_intro)
            outcome.ok, outcome.text = True, text
            outcome.data = DataAnswer(
                columns=result.columns, rows=[[_json_value(v) for v in r] for r in result.rows],
                row_count=len(result.rows), truncated=result.truncated, sql=checked.sql, database=checked.database,
                server=executor.server_label(server), tables=checked.tables,
                explanation=plan.explanation.strip(), filters=[f for f in plan.filters if f.strip()],
            )
            if result.truncated:
                outcome.notes.append(f"Muestro las primeras {self.max_rows} filas; hay más resultados.")
            return outcome
        outcome.notes.append("No pude calcular el dato con seguridad; te indico dónde está la información.")
        return outcome


# --- redacción (F10) ----------------------------------------------------------------------
def format_value(value) -> str:
    """Formato de El Salvador (es-SV), el mismo que usa la web: coma de miles y punto decimal."""
    if value is None:
        return "sin dato"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, (int,)) or (isinstance(value, decimal.Decimal) and value == value.to_integral_value()):
        return f"{int(value):,}"
    if isinstance(value, (float, decimal.Decimal)):
        return f"{float(value):,.2f}"
    if isinstance(value, dt.datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, dt.date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _json_value(value):
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return "(binario)"
    return value


def _fill(template: str, result: QueryResult, question: str, allow_columns: bool) -> str | None:
    """Rellena los marcadores con el resultado, o None si la frase no es segura: un número escrito por el modelo
    (que no venga de la pregunta) o un marcador que no corresponde al resultado."""
    if not template.strip():
        return None
    columns = {c.lower(): i for i, c in enumerate(result.columns)}
    literal_numbers = set(re.findall(r"\d+", PLACEHOLDER.sub("", template))) - set(re.findall(r"\d+", question))
    names = [n.lower() for n in PLACEHOLDER.findall(template)]
    if literal_numbers or not all(n == "filas" or (allow_columns and n in columns) for n in names):
        return None
    row = result.rows[0]
    return PLACEHOLDER.sub(
        lambda m: format_value(len(result.rows)) if m.group(1).lower() == "filas"
        else format_value(row[columns[m.group(1).lower()]]), template).strip()


def fill_answer(template: str, result: QueryResult, question: str, list_intro: str = "") -> str:
    """La frase de respuesta: con una fila, `template` con sus cifras; con varias, `list_intro` (o `template` si solo
    usa {filas}). Si ninguna es segura, una redacción genérica que no inventa nada."""
    if not result.rows:
        return "No encontré registros que cumplan esa condición."
    single = len(result.rows) == 1
    if single:
        text = _fill(template, result, question, allow_columns=True)
    else:
        text = _fill(list_intro, result, question, False) or _fill(template, result, question, False)
    if text:
        return text
    if single and len(result.columns) <= 3:
        parts = [f"{_label(c)}: {format_value(v)}" for c, v in zip(result.columns, result.rows[0])]
        return "El resultado es " + "; ".join(parts) + "."
    return f"Encontré {format_value(len(result.rows))} resultados; te los muestro en la tabla."


def _label(column: str) -> str:
    return column.replace("_", " ").strip().capitalize()
