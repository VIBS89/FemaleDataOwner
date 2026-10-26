"""Implementaciones con LLM de los puertos del DiscoverFlow: llamadas directas con salida estructurada (no agentes).

Reciben un `RoutedChat` del gateway (NIM o Bedrock según `config/models.yaml`) o cualquier chat model de LangChain.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from converdata.discovery.ports import RerankItem, RerankResult, RerankScore
from converdata.models.discovery import Discovery
from converdata.models.intent import IntentResult

INTENT_SYSTEM = """Eres el clasificador de intención de ConverData, un agente de descubrimiento de datos de un banco.
Clasifica la pregunta del usuario:
- discovery: busca dónde está o qué significa un dato (intención por defecto ante la duda).
- exploration: "¿qué datos tenemos de X?".
- data_query / procedure: pide cifras o filas.
- out_of_scope: saludos, temas ajenos o peticiones de escritura (borrar, actualizar, insertar).
- ambiguous: no se entiende qué dato busca; propone hasta 4 opciones en clarification.
Extrae business_context (proceso o área, p. ej. "onboarding digital"), asset_kind_hint y environment_hint
("produccion" por defecto). Responde en español. Nunca inventes nombres de tablas."""

RERANK_SYSTEM = """Ordena candidatos de un catálogo de datos según su relevancia para la pregunta.
Devuelve, para cada id de la lista, relevance entre 0 y 1 y una justificación de una línea en español.
Usa solo los ids recibidos; no añadas ninguno. Valora más las descripciones revisadas por humanos y las reglas de negocio."""

RESPOND_SYSTEM = """Redacta de 1 a 4 frases en español que recomienden el candidato principal y expliquen por qué.
Menciona únicamente objetos que aparecen en el JSON recibido. No inventes tablas, columnas ni reglas."""


class LlmIntentClassifier:
    def __init__(self, llm):
        self._llm = llm.with_structured_output(IntentResult)

    def classify(self, question: str, history: list[str]) -> IntentResult:
        context = "\n".join(f"- {h}" for h in history[-5:])
        content = f"Historial reciente:\n{context or '(vacío)'}\n\nPregunta: {question}"
        return self._llm.invoke([SystemMessage(INTENT_SYSTEM), HumanMessage(content)])


class LlmReranker:
    def __init__(self, llm):
        self._llm = llm.with_structured_output(RerankResult)

    def rerank(self, question: str, items: list[RerankItem]) -> list[RerankScore]:
        payload = json.dumps([i.model_dump() for i in items], ensure_ascii=False)
        result = self._llm.invoke([SystemMessage(RERANK_SYSTEM), HumanMessage(f"Pregunta: {question}\nCandidatos: {payload}")])
        return result.items


class LlmNarrator:
    def __init__(self, llm):
        self._llm = llm

    def narrate(self, question: str, discovery: Discovery) -> str:
        compact = {
            "candidates": [
                {"asset_key": c.asset_key, "confidence": c.confidence, "why": c.why, "description": c.description}
                for c in discovery.candidates
            ],
            "alternatives": [a.model_dump() for a in discovery.alternatives],
            "knowledge_gap": discovery.knowledge_gap,
        }
        msg = self._llm.invoke(
            [SystemMessage(RESPOND_SYSTEM), HumanMessage(f"Pregunta: {question}\n{json.dumps(compact, ensure_ascii=False)}")]
        )
        return msg.content if isinstance(msg.content, str) else "".join(
            part.get("text", "") for part in msg.content if isinstance(part, dict)
        )


# --- Catalog Builder: enriquecimiento de descripciones (F1, rol `planner`) ---------------------------
from pydantic import BaseModel, Field  # noqa: E402


class ColumnEnrichment(BaseModel):
    name: str
    description: str = Field(description="Una frase en español; qué representa la columna")
    synonyms: list[str] = Field(default_factory=list, max_length=5, description="Términos de negocio en español")


class TableEnrichment(BaseModel):
    table: str
    description: str = Field(description="Una o dos frases en español")
    synonyms: list[str] = Field(default_factory=list, max_length=5)
    domain: str | None = None
    columns: list[ColumnEnrichment] = Field(default_factory=list)


class EnrichmentBatch(BaseModel):
    tables: list[TableEnrichment]


ENRICH_SYSTEM = """Eres un analista de datos de un banco. Para cada tabla de SQL Server recibida (solo estructura:
nombres, tipos, llaves; nunca valores), escribe en español una descripción funcional breve de la tabla y de cada columna,
y hasta 5 sinónimos de negocio. No inventes tablas ni columnas: usa exactamente los nombres recibidos."""


class LlmEnricher:
    def __init__(self, llm):
        self._llm = llm.with_structured_output(EnrichmentBatch)

    def enrich(self, tables: list[dict]) -> EnrichmentBatch:
        payload = json.dumps(tables, ensure_ascii=False)
        return self._llm.invoke([SystemMessage(ENRICH_SYSTEM), HumanMessage(payload)])
