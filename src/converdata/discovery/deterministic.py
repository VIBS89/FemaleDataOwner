"""Implementaciones deterministas de los puertos de LLM.

Se usan cuando no hay Bedrock configurado (desarrollo, tests, evaluación de la línea base de recuperación) y como
respaldo cuando la salida del modelo no pasa las guardas (ids desconocidos, objetos inventados en la narrativa).
"""

from __future__ import annotations

import re

from converdata.catalog.ids import short_name
from converdata.discovery.expansion import content_words
from converdata.discovery.ports import RerankItem, RerankScore
from converdata.memory.text import STOPWORDS, strip_accents
from converdata.models.discovery import Discovery
from converdata.models.intent import Clarification, IntentResult

_WRITE = re.compile(
    r"\b(borra|borrar|elimina|eliminar|actualiza|actualizar|inserta|insertar|modifica|modificar|"
    r"drop|delete|update|truncate|insert)\b"
    # Una orden al inicio ("cambia el saldo…", "ponle estado cancelado"): en medio de una pregunta el mismo verbo solo
    # describe el dato ("¿dónde veo cuándo cambia el estado?").
    r"|^\W*(?:por favor,? )?(?:cambia(?:me|le)?|pon(?:le|me)?|ajusta|anula|reversa|crea|agrega|quita|corrige|aprueba|"
    r"desbloquea|bloquea|sube|baja)\b"
)
_GREETING = re.compile(r"^\s*(hola|buenos dias|buenas tardes|buenas noches|buenas|gracias|adios)\W*$")
_EXPLORATION = re.compile(r"\bque (datos|informacion|tablas) (tenemos|hay|existen)\b"
                          r"|\bque (puedo|podemos|se puede) (consultar|ver|preguntar|saber|encontrar) (sobre|de|acerca)\b")
_DISCOVERY = re.compile(
    r"\b(donde|que significa|que campo|que columna|que tabla|identificador|identifica|encontrar|"
    r"ubicar|localizar|cual es el campo|en que (tabla|base)|que reglas)\b"
)
_DATA_QUERY = re.compile(
    r"\b(cuant[oa]s?|total de|suma de|promedio|top \d+|cuanto vendimos|(?:monto|saldo|valor) total|cantidad de|"
    r"ranking|l[oa]s \d+ (?:mas|mayores|mejores|principales)|"
    r"por (?:mes|ano|dia|semana|trimestre|agencia|sucursal|ejecutivo)|"
    r"(?:ultim[oa]s?|este|esta|pasad[oa]) (?:\d+ )?(?:mes|meses|ano|anos|trimestre|semana|semanas|dias))\b")
# En una pregunta de cifras, nombrar una medida ("el saldo total", "el monto promedio") pide el dato que la guarda.
_MEASURE = re.compile(r"\b(montos?|saldos?|importes?|valor(?:es)?|dinero|plata|deuda|consumos?|ingresos?)\b")
_CONTEXT = re.compile(r"\b(?:procesos? de|flujo de|area de|proceso|en el (?:proceso|flujo) de)\s+([a-z0-9 ]+?)(?:[.?,;]|$)")
_FILLER = {"dame", "muestrame", "ver", "todo", "toda", "todos", "informacion", "favor", "puedes", "podrias"}


def _norm(text: str) -> str:
    return strip_accents(text).lower()


# Una pregunta que sigue a la anterior: empieza con un conector ("y…", "ahora…", "pero…") o señala algo ya dicho
# ("de esos", "esa fecha", "lo mismo", "cómo los cruzo").
_CONNECTOR = re.compile(r"^\W*(?:y|pero|ahora|tambien|entonces|ademas|o sea)\b")
_ANAPHORA = re.compile(
    r"\b(?:es[oa]s?|ese|aquell[oa]s?|dich[oa]s?|lo mismo|l[oa]s mism[oa]s|de ell[oa]s)\b"
    r"|\bcomo l[oa]s? (?:cruz\w+|un[oe]|relacion\w+|junt\w+|conect\w+)\b")
MAX_CONTEXT_TURNS = 3
_MEANING = re.compile(r"\bque (?:significa|quiere decir)\b")


_FOLLOW_UP_LEAD = re.compile(r"^\W*(?:y|pero|ahora|tambien|entonces|ademas|o sea)\b[\s,]*")


def is_write_request(question: str) -> bool:
    """¿Pide modificar datos? Se mira la pregunta sola, sin el conector con que empieza un seguimiento ("y…")."""
    return bool(_WRITE.search(_FOLLOW_UP_LEAD.sub("", _norm(question))))


def is_join_question(question: str) -> bool:
    """¿Pregunta cómo relacionar o cruzar información? Ahí lo pedido son las tablas y el camino entre ellas."""
    return bool(_JOIN.search(_norm(question)))


def is_figures_question(question: str) -> bool:
    """¿Pide una cifra (cuántos, total, promedio, por mes…)? En la fase 1a se responde con qué información se obtiene."""
    q = _norm(question)
    return bool(_DATA_QUERY.search(q)) and not _DISCOVERY.search(q)


def is_follow_up(question: str) -> bool:
    """Señala algo ya dicho ("de esos", "lo mismo", "cómo los cruzo"), o empieza con un conector y casi no trae
    contenido propio ("¿y en leasing?"). "Y dónde está el DUI del cliente" empieza con "y" pero nombra su propio
    dato: es una pregunta nueva."""
    q = _norm(question)
    if _ANAPHORA.search(q):
        return True
    if not _CONNECTOR.search(q):
        return False
    # "¿Y qué significa el estado de la gestión?" pregunta por algo de lo que se venía hablando.
    return len(content_words(q)) <= 1 or bool(_MEANING.search(q))


def contextualize(question: str, history: list[str]) -> str:
    """Una pregunta de seguimiento ("¿y cómo los cruzo con los clientes?") se entiende junto con la anterior. Se
    antepone la última pregunta que no era a su vez un seguimiento (hasta `MAX_CONTEXT_TURNS` hacia atrás); una pregunta
    nueva se deja como está."""
    if not history or not is_follow_up(question):
        return question
    previous: list[str] = []
    for past in reversed(history[-MAX_CONTEXT_TURNS:]):
        if not past or not past.strip():
            continue
        previous.insert(0, past.strip(" ¿?.!¡"))
        if not is_follow_up(past):
            break
    return " ".join([*previous, question.strip()]) if previous else question


class RuleBasedIntentClassifier:
    """Clasificador de intención por reglas (F3). Ante la duda gana `discovery`."""

    def classify(self, question: str, history: list[str]) -> IntentResult:
        q = _norm(question)
        words = re.findall(r"[a-z0-9]+", q)
        entities = [w for w in words if len(w) > 3 and w not in STOPWORDS and w not in _FILLER]
        base = dict(rewritten_question=question.strip(), entities=entities)

        if _GREETING.match(q):
            return IntentResult(intent="out_of_scope", confidence=0.95, **base)
        if _WRITE.search(q):
            return IntentResult(intent="out_of_scope", confidence=0.95, **base)
        if not entities:
            return IntentResult(
                intent="ambiguous",
                confidence=0.3,
                clarification=Clarification(
                    question="¿Qué dato necesitas encontrar?",
                    options=["Un campo o columna", "Una tabla", "Una regla de negocio", "Un indicador"],
                ),
                **base,
            )

        if _EXPLORATION.search(q):
            intent = "exploration"
        elif _DATA_QUERY.search(q) and not _DISCOVERY.search(q):
            intent = "data_query"
        else:
            intent = "discovery"

        context = _CONTEXT.search(q)
        return IntentResult(
            intent=intent,
            analysis_mode="explore" if intent == "exploration" else "lookup",
            business_context=context.group(1).strip() if context else None,
            asset_kind_hint=_kind_hint(q, intent),
            environment_hint=_environment_hint(q),
            confidence=0.85,
            **base,
        )


_ETL = re.compile(r"\b(etl|ssis|linaje|llena|alimenta|carga|cargan|que proceso|que job)\b")
# "¿Cómo relaciono A con B?": se piden las tablas y el camino para unirlas, no una columna suelta. El verbo va tras
# "cómo" (o es inequívoco): "cada uno de los clientes" no es un cruce.
_JOIN = re.compile(r"\bcomo (?:se |puedo |podemos |l[oa]s? |le )*(?:relacion\w+|cruz\w+|un[oe]|unir|unen|unimos|junt\w+|"
                   r"conect\w+)\b"
                   r"|\b(?:relacion(?:o|ar|an|amos)|cruz(?:o|ar|an|amos)|unir|join)\b.*\bcon\b")
_ASKS_FIELD = re.compile(r"\b(?:que|cual|cuales) (?:campos?|columnas?|llaves?)\b")


def _kind_hint(q: str, intent: str):
    # "¿Qué es la fecha de corte en las tablas de saldos?" pregunta por el significado de un dato, aunque diga "tablas".
    if intent == "discovery" and re.search(r"\bque (?:es|significa|quiere decir) (?:el|la)\b", q):
        return "column"
    # Una cifra sobre una medida ("saldo total de la cartera") pide la columna que la guarda.
    if intent == "data_query" and _MEASURE.search(q) and not re.search(r"\btablas?\b", q):
        return "column"
    # Exploración, conteos (en fase 1a se responde qué tabla consultar) y preguntas de ETL piden tablas.
    if intent in ("exploration", "data_query") or re.search(r"\btablas?\b", q) or _ETL.search(q):
        return "table"
    if _ASKS_FIELD.search(q):  # "¿con qué campo cruzo…?" pide la columna, aunque hable de cruzar
        return "column"
    if _JOIN.search(q):
        return "table"
    if re.search(r"\b(indicador|metrica|kpi)", q):
        return "indicator"
    if re.search(r"\breglas?\b", q):
        return "rule"
    if re.search(r"\b(campo|columna|identificador|codigo|fecha|id)\b", q):
        return "column"
    # "¿Dónde está el saldo…?" (singular) pide un dato concreto; "¿dónde están los arrendamientos?" puede ser una tabla.
    if re.search(r"\bdonde (esta|se guarda|se encuentra|queda) (el|la)\b", q):
        return "column"
    return None


def _environment_hint(q: str) -> str:
    if re.search(r"\b(qa|pruebas|calidad)\b", q):
        return "qa"
    if re.search(r"\b(desarrollo|dev)\b", q):
        return "desarrollo"
    return "produccion"


class ScoreReranker:
    """Reranker determinista: conserva el orden de recuperación (lo calcula el motor) y explica con la evidencia."""

    def __init__(self, relevance: dict[str, float] | None = None):
        self.relevance = relevance or {}

    def rerank(self, question: str, items: list[RerankItem]) -> list[RerankScore]:
        scores = []
        for item in items:
            if any(e.startswith("golden_discovery") for e in item.evidence):
                why = "Confirmado previamente para una pregunta similar."
            elif item.rules:
                why = f"Tiene reglas de negocio vinculadas ({', '.join(item.rules[:2])})."
            elif item.description_source != "generated":
                why = "Su nombre y su descripción documentada coinciden con lo que buscas."
            else:
                why = "Su nombre coincide con lo que buscas (descripción sugerida por IA, sin revisar)."
            scores.append(RerankScore(id=item.id, relevance=self.relevance.get(item.id, 0.0), why=why))
        return scores


def _table_dot_column(asset_key: str) -> str:
    return ".".join(asset_key.split(".")[-2:]) if asset_key.count(".") >= 3 else short_name(asset_key)


_ASKS_PROCESS = re.compile(r"\b(etl|ssis|linaje|proceso|procesos|job|jobs|paquete)\b")


def _loading_sentence(question: str, table: str, discovery: Discovery) -> str | None:
    """Si la pregunta es de linaje ("¿qué proceso llena…?"), nombra los procesos ETL que cargan la tabla principal."""
    q = _norm(question)
    if not _ETL.search(q):
        return None
    loaders = [r for r in discovery.related if r.relation == "etl" and r.to == table and r.via]
    if loaders:
        shown = "; ".join(f"{r.via.replace(':', ' ', 1)} desde {r.from_}" for r in loaders)
        return f"Proceso de carga de {table}: {shown}."
    if _ASKS_PROCESS.search(q):
        return f"No tengo registrado ningún proceso que cargue {table}; puedes preguntar al responsable del dominio."
    return None


ENV_LABELS = {"produccion": "Producción", "qa": "QA", "desarrollo": "Desarrollo", "dr": "DR"}
ENV_ORDER = {"produccion": 0, "qa": 1, "desarrollo": 2, "dr": 3}


class TemplateNarrator:
    """Narrativa de 1 a 4 frases que solo menciona objetos de la respuesta (F22 paso 7)."""

    def narrate(self, question: str, discovery: Discovery) -> str:
        if not discovery.candidates:
            return (
                "No encontré datos disponibles para ti sobre lo que preguntas. "
                "Puedes preguntar al responsable del dominio."
            )
        top = discovery.candidates[0]
        name = top.column or top.table
        where = f"{top.database}.{top.schema_}.{top.table}"
        envs = sorted({loc.environment for loc in top.locations}, key=lambda e: (ENV_ORDER.get(e, 9), e))
        label = "ambientes" if len(envs) > 1 else "ambiente"
        shown = " y ".join(ENV_LABELS.get(e, e) for e in envs)
        lead = ("Para obtener esa cifra, la información está en" if _DATA_QUERY.search(_norm(question))
                else "Lo más cercano a lo que buscas es")
        parts = [f"{lead} {name} ({where}, {label}: {shown}), con {round(top.confidence * 100)} % de confianza."]
        loading = _loading_sentence(question, where, discovery)
        if loading:  # "¿qué proceso llena…?": el proceso es la respuesta, va antes que el resto
            parts.append(loading)
        if top.description and top.description_source != "generated":
            parts.append(top.description.rstrip(".") + ".")
        elif top.why:
            parts.append(top.why)
        if discovery.join_paths:
            parts.append("Se cruza así: " + "; ".join(join_sentence(p.steps) for p in discovery.join_paths[:2]) + ".")
        others = [_table_dot_column(c.asset_key) for c in discovery.candidates[1:]] + [
            _table_dot_column(a.asset_key) for a in discovery.alternatives
        ]
        if others:
            parts.append(f"También revisa: {', '.join(dict.fromkeys(others))}.")
        if discovery.unresolved_parts:
            missing = ", ".join(f"«{p}»" for p in discovery.unresolved_parts)
            parts.append(f"No encontré datos disponibles para {missing}; puedes preguntar al responsable del dominio.")
        elif discovery.knowledge_gap:
            parts.append("La confianza es baja; puedes preguntar al responsable del dominio.")
        return " ".join(parts[:5])


def join_sentence(steps: list[str]) -> str:
    """"BD.dbo.A → BD.dbo.B (fk: ClienteID)" → "A → B (por ClienteID)": el camino de unión en una línea legible."""
    out = []
    for step in steps:
        match = re.match(r"(\S+) → (\S+)(?: \((\w+)(?:: (.+))?\))?$", step)
        if not match:
            out.append(step)
            continue
        a, b, kind, detail = match.groups()
        how = {"fk": f"por {detail}" if detail else "", "same_entity": "el mismo dato en otro sistema",
               "view": "vista que lo resume"}.get(kind or "", detail or "")
        out.append(f"{short_name(a)} → {short_name(b)}" + (f" ({how})" if how else ""))
    return ", ".join(out)
