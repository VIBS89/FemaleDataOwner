"""Implementaciones deterministas de los puertos de LLM.

Se usan cuando no hay Bedrock configurado (desarrollo, tests, evaluación de la línea base de recuperación) y como
respaldo cuando la salida del modelo no pasa las guardas (ids desconocidos, objetos inventados en la narrativa).
"""

from __future__ import annotations

import re

from converdata.catalog.ids import short_name
from converdata.discovery.ports import RerankItem, RerankScore
from converdata.memory.text import STOPWORDS, strip_accents
from converdata.models.discovery import Discovery
from converdata.models.intent import Clarification, IntentResult

_WRITE = re.compile(
    r"\b(borra|borrar|elimina|eliminar|actualiza|actualizar|inserta|insertar|modifica|modificar|"
    r"drop|delete|update|truncate|insert)\b"
)
_GREETING = re.compile(r"^\s*(hola|buenos dias|buenas tardes|buenas noches|buenas|gracias|adios)\W*$")
_EXPLORATION = re.compile(r"\bque (datos|informacion|tablas) (tenemos|hay|existen)\b")
_DISCOVERY = re.compile(
    r"\b(donde|que significa|que campo|que columna|que tabla|identificador|identifica|encontrar|"
    r"ubicar|localizar|cual es el campo|en que (tabla|base)|que reglas)\b"
)
_DATA_QUERY = re.compile(r"\b(cuant[oa]s?|total de|suma de|promedio|top \d+|cuanto vendimos|monto total)\b")
_CONTEXT = re.compile(r"\b(?:procesos? de|flujo de|area de|proceso|en el (?:proceso|flujo) de)\s+([a-z0-9 ]+?)(?:[.?,;]|$)")
_FILLER = {"dame", "muestrame", "ver", "todo", "toda", "todos", "informacion", "favor", "puedes", "podrias"}


def _norm(text: str) -> str:
    return strip_accents(text).lower()


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


def _kind_hint(q: str, intent: str):
    # Exploración, cifras (en fase 1a se responde qué tabla consultar) y preguntas de ETL piden tablas.
    if intent in ("exploration", "data_query") or re.search(r"\btablas?\b", q) or _ETL.search(q):
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
        envs = ", ".join(sorted({loc.environment for loc in top.locations}))
        parts = [f"El candidato principal es {name} ({where}, ambiente: {envs}) con {round(top.confidence * 100)} % de confianza."]
        if top.why:
            parts.append(top.why)
        others = [_table_dot_column(c.asset_key) for c in discovery.candidates[1:]] + [
            _table_dot_column(a.asset_key) for a in discovery.alternatives
        ]
        if others:
            parts.append(f"También revisa: {', '.join(dict.fromkeys(others))}.")
        if discovery.knowledge_gap:
            parts.append("La confianza es baja; puedes preguntar al responsable del dominio.")
        return " ".join(parts[:4])
