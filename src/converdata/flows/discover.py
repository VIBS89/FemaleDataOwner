"""DiscoverFlow (F22) como grafo de LangGraph con pasos fijos y ciclos acotados.

    START → intent ─┬─► retrieve → grade ─┬─► rerank → expand → review ─┬─► respond → finalize → END
                    │       ▲             │              ▲              │
                    │       └── reintento ┘ (C, máx. 1)  └── corrección ┘ (B, máx. 1)
                    └─► finalize   (aclaración o fuera de alcance)

Patrones de agentes (activables en `Settings.patterns`, medidos con `converdata eval discovery`):
- **D, expansión de la consulta** (`retrieve`): pregunta original + variante con términos técnicos; cobertura por conceptos.
- **C, RAG correctivo** (`grade`): si la recuperación cubre poco la pregunta, se reformula una vez (LLM `fast` o léxico).
- **E, cascada** (`rerank`): si el ranking determinista es claro, no se llama al reranker LLM.
- **B, evaluador-optimizador** (`review`): chequeos deterministas y juez LLM (`judge`); una corrección como máximo, y si
  queda un fallo sin resolver la confianza baja al nivel de brecha.

El orden y los ciclos los define el grafo, nunca el modelo (PRD §8.1). Sin checkpointer persistente (F17).
"""

from __future__ import annotations

import datetime as dt
import logging
import operator
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Iterator, TypedDict

from langgraph.graph import END, START, StateGraph

from converdata.ask.engine import AskEngine, AskOutcome
from converdata.ask.ports import QueryExecutor, QuestionInterpretation
from converdata.audit.recorder import AuditSink, InMemoryAuditSink, StepRecord, TraceRecord
from converdata.catalog.store import Catalog, KnowledgeBase
from converdata.config import OwnersDirectory, Settings
from converdata.discovery import assistant, engine, figures
from converdata.discovery.deterministic import (
    RuleBasedIntentClassifier,
    ScoreReranker,
    TemplateNarrator,
    contextualize,
    is_join_question,
    is_write_request,
)
from converdata.discovery.expansion import ANALYSIS_TERMS, QueryPlan, concepts_of, lexicon_variant, plan_query
from converdata.discovery.ports import Guide, IntentClassifier, Narrator, QueryExpander, Reranker, Reviewer
from converdata.models.intent import Clarification
from converdata.memory.base import VectorStore
from converdata.memory.text import strip_literals
from converdata.models.discovery import AnswerEnvelope, Check, Discovery, Validation
from converdata.models.identity import UserContext
from converdata.models.intent import IntentResult

MAX_RETRIEVAL_ATTEMPTS = 2  # C: búsqueda original + una reformulación
MAX_REVIEW_ATTEMPTS = 2  # B: revisión + una corrección
ASK_HINTS = 10  # fase 1b: activos mejor puntuados que orientan la base cuando no hay candidato recomendado

STEP_LABELS = {
    "intent": "Interpretando la pregunta",
    "retrieve": "Buscando en catálogo, diccionarios, documentos y ETL",
    "grade": "Calificando lo encontrado",
    "rerank": "Priorizando candidatos",
    "expand": "Agregando ubicaciones, reglas, relaciones y responsables",
    "review": "Revisando el resultado",
    "ask": "Calculando el dato con tus permisos",
    "compute": "Calculando la cifra con tus permisos",
    "respond": "Redactando la respuesta",
    "finalize": "Registrando la auditoría",
}

NO_FIGURES_NOTE = "Todavía no calculo cifras: te indico qué información usar y cómo se cruza para obtenerla."
FIGURE_FAILED_NOTE = ("No pude calcular la cifra (puede que tu usuario no tenga permiso de lectura sobre esa información "
                      "o que la consulta tardara demasiado). Te indico qué información usar.")

log = logging.getLogger(__name__)


@dataclass
class DiscoverDeps:
    catalog: Catalog
    knowledge: KnowledgeBase
    store: VectorStore
    owners: OwnersDirectory
    settings: Settings = field(default_factory=Settings)
    intent_classifier: IntentClassifier = field(default_factory=RuleBasedIntentClassifier)
    reranker: Reranker | None = None  # None → ScoreReranker (determinista)
    narrator: Narrator = field(default_factory=TemplateNarrator)
    expander: QueryExpander | None = None  # C/D con LLM (rol `fast`); None → solo léxico
    reviewer: Reviewer | None = None  # B con juez LLM (rol `judge`); None → solo chequeos deterministas
    guide: Guide | None = None  # sin resultados: el LLM (rol `fast`) reconoce el tema o propone una aclaración de negocio
    graph: object | None = None  # EstateGraph (F19); lo construye `DiscoverService` si falta
    # Fase 1b (`features.ask_llm_sql`): SQL de un LLM cuando la plantilla de cifras no puede responder.
    ask: AskEngine | None = None
    audit: AuditSink = field(default_factory=InMemoryAuditSink)
    model_names: Mapping[str, str] = field(default_factory=dict)  # rol → proveedor:modelo (`audit_step.model`)


class DiscoverState(TypedDict, total=False):
    trace_id: str
    question: str
    search_question: str  # la pregunta sin saludo y, si es un seguimiento, con la anterior delante
    figures: bool  # pide una cifra: los términos de cálculo y de periodo no nombran un dato
    assistant_topic: str  # pregunta sobre el propio asistente (`discovery.assistant`)
    clarification: Clarification
    executor: Any  # `figures.FigureExecutor` de la sesión; sin él no se calculan cifras
    figure: Any  # `models.figures.Figure` calculada
    sql_executor: QueryExecutor  # fase 1b: SQL validado con la sesión del usuario (`runtime.ask_executor`)
    interpretation: QuestionInterpretation  # fase 1b: lo que entendió el LLM de la pregunta
    ask: AskOutcome  # fase 1b: el dato calculado con SQL de un LLM
    history: list[str]
    client: str
    user: UserContext
    started: float
    intent: IntentResult
    route: str
    assumptions: Annotated[list[str], operator.add]
    plan: QueryPlan
    retrieval_attempt: int
    retrieval_route: str
    retrieval: engine.Retrieval
    shortlist: list[engine.Draft]
    ranked: list[engine.Draft]
    discovery: Discovery
    review_attempt: int
    review_route: str
    validation: Validation
    answer_text: str
    envelope: AnswerEnvelope
    db_ms: int
    steps: Annotated[list[StepRecord], operator.add]


def _timed(name: str, model_role: str | None, deps: DiscoverDeps, fn, attempt_key: str | None = None):
    """Envuelve un nodo para registrar su `audit_step`. El nodo devuelve (update, error[, detalle])."""

    def node(state: DiscoverState) -> dict[str, Any]:
        started_at = dt.datetime.now(dt.timezone.utc)
        t0 = time.perf_counter()
        result = fn(state)
        update, error = result[0], result[1]
        detail = result[2] if len(result) > 2 else None
        used_model = update.pop("_model_used", None)
        step = StepRecord(
            trace_id=state["trace_id"],
            step=name,
            attempt=state.get(attempt_key, 0) + 1 if attempt_key else 1,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            model=(deps.model_names.get(model_role) if model_role else None) if used_model is not False else None,
            ok=error is None,
            error=error,
            detail=detail,
        )
        return {**update, "steps": [step]}

    return node


def build_discover_graph(deps: DiscoverDeps):
    fallback_intent = RuleBasedIntentClassifier()
    fallback_narrator = TemplateNarrator()

    def ds():
        return deps.settings.discovery

    def patterns():
        return deps.settings.patterns

    def llm_sql_available(state) -> bool:
        return bool(deps.settings.features.ask_llm_sql and deps.ask is not None and state.get("sql_executor"))

    def wants_figure(state) -> bool:
        return bool(state.get("figures") and deps.settings.features.ask_flow and state.get("executor")
                    and state["discovery"].candidates)

    def wants_llm_sql(state) -> bool:
        return bool(state.get("figures") and llm_sql_available(state)
                    and (state["discovery"].candidates or state.get("ranked")))

    def intent_node(state):
        error = None
        history = state.get("history", [])
        # Una pregunta sobre el propio asistente ("¿cómo te enteras de tablas nuevas?") no se busca en el catálogo.
        topic = assistant.topic_of(state["question"])
        if topic:
            result = IntentResult(intent="assistant", rewritten_question=state["question"].strip(), confidence=1.0)
            return {"intent": result, "route": "assistant", "assistant_topic": topic, "assumptions": [],
                    "search_question": state["question"], "_model_used": False}, None
        # El saludo no es parte de lo que se busca, y un seguimiento se entiende con la pregunta anterior.
        current = assistant.strip_greeting(state["question"])
        search = contextualize(current, history)
        detail = f"seguimiento:{len(history)}" if search != current else None
        if is_write_request(current):
            # Una orden de modificar datos se rechaza por lo que dice la pregunta actual: el historial lo envía el
            # cliente y no puede ni disimularla ni provocar el rechazo de una pregunta legítima.
            result = IntentResult(intent="out_of_scope", rewritten_question=current, confidence=0.95)
        else:
            try:
                result = deps.intent_classifier.classify(search, history)
            except Exception as exc:  # throttling, timeout o salida no parseable → reglas
                error = f"fallback:{type(exc).__name__}"
                result = fallback_intent.classify(search, history)
            if result.intent == "out_of_scope" and search != current:
                result = fallback_intent.classify(current, [])
                search = current
        assumptions: list[str] = []
        figures = result.intent in ("data_query", "procedure")
        interpretation = None
        if llm_sql_available(state) and result.intent != "out_of_scope":
            # Fase 1b: el LLM reconoce un pedido de datos sin listas de palabras clave ("dame los 10…") y reescribe la
            # pregunta. Solo suma: el rechazo de escrituras y el resto de la intención siguen siendo de las reglas.
            try:
                interpretation = deps.ask.interpret(search, history, state["user"])
            except Exception as exc:
                error = ((error + ";") if error else "") + f"interprete:fallback:{type(exc).__name__}"
            if interpretation is not None and interpretation.kind == "dato":
                figures = True
                result = result.model_copy(update={"intent": "data_query", "confidence": max(result.confidence, 0.8)})
        if result.intent == "out_of_scope":
            route = "out_of_scope"
        elif result.intent == "ambiguous" or result.confidence < 0.6:
            route = "clarify"
        elif figures:
            # F3: una pregunta de cifras primero se descubre (qué información la responde). Con `features.ask_flow` y un
            # ejecutor de la sesión, el nodo `compute` calcula después el agregado; sin ellos se indica dónde está.
            route = "discover"
            if not (deps.settings.features.ask_flow and state.get("executor")) and not llm_sql_available(state):
                assumptions.append(NO_FIGURES_NOTE)
            result = result.model_copy(update={"intent": "discovery"})
        else:
            route = "discover"
        if route == "discover" and result.asset_kind_hint is None:
            # Lo que la pregunta no dice lo aclara el catálogo: un plural que nombra una tabla visible pide esa tabla.
            hint = engine.entity_kind_hint(search, result, deps.catalog, state["user"].visible_ids)
            if hint:
                result = result.model_copy(update={"asset_kind_hint": hint})
        out = {"intent": result, "route": route, "assumptions": assumptions, "search_question": search,
               "figures": figures}
        if interpretation is not None:
            out["interpretation"] = interpretation
        return out, error, detail

    # --- D: recuperación con plan de consultas ---------------------------------------------
    def retrieve_node(state):
        intent = state["intent"]
        search = state.get("search_question") or state["question"]
        plan = state.get("plan") or plan_query(
            intent.rewritten_question or search, intent.business_context,
            patterns().query_expansion, ds().variant_weight,
            known=deps.catalog.names_with_digits(state["user"].visible_ids),
            ignore=(ANALYSIS_TERMS - engine.kept_analysis_terms(search, deps.catalog, state["user"].visible_ids))
            if state.get("figures") else frozenset(),
        )
        retrieval = engine.retrieve(
            search, intent, state["user"], deps.store, deps.catalog, deps.knowledge, ds(), plan,
            graph=deps.graph if patterns().graph else None,
        )
        detail = f"consultas={len(plan.queries)}"
        return {
            "plan": plan,
            "retrieval": retrieval,
            "shortlist": engine.shortlist(retrieval, intent, ds()),
            "retrieval_attempt": state.get("retrieval_attempt", 0) + 1,
        }, None, detail

    # --- C: calificación de la recuperación y una reformulación ----------------------------
    def grade_node(state):
        quality = engine.grade_retrieval(state["retrieval"])
        attempt = state.get("retrieval_attempt", 1)
        if not patterns().grade or quality >= ds().grade_min_coverage or attempt >= MAX_RETRIEVAL_ATTEMPTS:
            return {"retrieval_route": "continue", "_model_used": False}, None, f"calidad={quality:.2f}"
        plan: QueryPlan = state["plan"]
        variants, error, used_llm = [], None, False
        # En una pregunta de cifras el modelo no hace falta: la reformulación no cambia qué se calcula y solo añade espera.
        if deps.expander is not None and not state.get("figures"):
            try:
                weak = [sorted(c)[0] for c in plan.concepts]
                known = deps.catalog.names_with_digits(state["user"].visible_ids)
                variants = deps.expander.expand(strip_literals(state["intent"].rewritten_question, known), weak)
                used_llm = True
            except Exception as exc:
                error = f"fallback:{type(exc).__name__}"
        if not variants:
            lex = lexicon_variant(state.get("search_question") or state["question"])
            variants = [lex] if lex else []
        variants = [v.strip() for v in variants if isinstance(v, str) and v.strip()
                    and not engine.unsafe_generated_text(v)][:3]
        new = plan.add_variants(variants, ds().variant_weight)
        if not new:
            return {"retrieval_route": "continue", "_model_used": used_llm}, error, f"calidad={quality:.2f};sin_reformulacion"
        out: dict = {"plan": plan, "retrieval_route": "retry", "_model_used": used_llm}
        search = state.get("search_question") or state["question"]
        if used_llm and not plan.secondary_parts and not state.get("figures") and not is_join_question(search):
            # Una pregunta compuesta o de cruce ("el saldo de la cuenta y el nombre de la agencia") ya dice qué datos
            # quiere y cómo se reparten: ahí la reformulación solo suma búsquedas. La pregunta habla de un reporte o de un indicador ("cartera en mora mayor a 90 días que pide la
            # Superintendencia") y casi nada de eso nombra un dato. La primera reformulación del modelo dice qué dato
            # se necesita ("días de mora y saldo del préstamo"): con ella se mide si un activo responde. El modelo
            # solo redacta la búsqueda; qué activos existen y cuáles ve el usuario lo sigue decidiendo el catálogo.
            known = deps.catalog.names_with_digits(state["user"].visible_ids)
            restated = concepts_of(new[0], patterns().query_expansion, known)
            if restated:
                plan.concepts, plan.primary_concepts = restated, None
                out["assumptions"] = [f"Entendí que necesitas: «{new[0][:120]}». Si no es eso, dímelo con otras palabras."]
        return out, error, f"calidad={quality:.2f}→reintento({len(new)} variantes)"

    # --- E: cascada en el reranking ---------------------------------------------------------
    def rerank_node(state):
        drafts = state["shortlist"]
        fallback = engine.deterministic_relevance(drafts, state["intent"])
        items = engine.rerank_items(drafts, deps.knowledge)
        error, detail = None, None
        engine.apply_rerank(drafts, [], fallback)
        deterministic_rank = engine.rank(drafts, ds())
        use_llm = deps.reranker is not None and drafts
        if use_llm and patterns().cascade and engine.decisive(deterministic_rank, ds()):
            use_llm, detail = False, "cascada:sin_llm"
        if use_llm:
            try:
                scores = deps.reranker.rerank(state["intent"].rewritten_question, items)
                rejected = engine.apply_rerank(drafts, scores, fallback)
                if rejected:
                    error = f"ids_descartados:{len(rejected)}"
            except Exception as exc:
                error = f"fallback:{type(exc).__name__}"
                engine.apply_rerank(drafts, [], fallback)
        # Los candidatos sin justificación del modelo reciben la determinista.
        for d, s in zip(drafts, ScoreReranker(fallback).rerank(state["question"], items)):
            d.why = d.why or s.why
        return {"ranked": engine.rank(drafts, ds()), "_model_used": bool(use_llm)}, error, detail

    def expand_node(state):
        local = ds()
        if state["intent"].intent == "exploration":
            local = local.model_copy(update={"max_candidates": local.expand_top, "secondary_candidate_min": 0.0})
        discovery = engine.build_discovery(
            state["ranked"], state["retrieval"], state["intent"], state["user"],
            deps.catalog, deps.knowledge, deps.owners, local,
            graph=deps.graph if patterns().graph else None,
        )
        detail = f"caminos={len(discovery.join_paths)}" if discovery.join_paths else None
        out: dict = {"discovery": discovery}
        # Con la fase 1b el planner ve todas las tablas de la base: que el buscador no ubique una parte de la pregunta
        # (p. ej. una fecha) no significa que falte el dato.
        if discovery.unresolved_parts and not (state.get("figures") and llm_sql_available(state)):
            out["assumptions"] = [f"No encontré datos disponibles para «{p}»." for p in discovery.unresolved_parts]
        return out, None, detail

    # --- B: evaluador-optimizador -----------------------------------------------------------
    def review_node(state):
        attempt = state.get("review_attempt", 0) + 1
        validation = state.get("validation") or Validation()
        validation.attempts = attempt
        discovery, ranked, intent = state["discovery"], state["ranked"], state["intent"]
        if not patterns().review or not discovery.candidates:
            return {"review_route": "accept", "review_attempt": attempt, "validation": validation, "_model_used": False}, None
        checks = engine.review_checks(discovery, ranked, intent, ds())
        fails = [c for c in checks if c.status == "fail"]
        top_key = discovery.candidates[0].asset_key
        error, detail, used_llm = None, None, False
        winner, reason = None, ""

        if attempt < MAX_REVIEW_ATTEMPTS:
            low, high = ds().review_judge_band
            in_band = low <= discovery.candidates[0].confidence <= high
            if deps.reviewer is not None and (fails or in_band):
                try:
                    items = engine.rerank_items(ranked[: ds().rerank_max], deps.knowledge)
                    verdict = deps.reviewer.review(intent.rewritten_question, items, top_key, [c.detail for c in checks])
                    used_llm = True
                    validation.judge = verdict.model_dump()
                    valid_ids = {d.asset_key for d in ranked}
                    if not verdict.answers_question:
                        if verdict.better_candidate in valid_ids and verdict.better_candidate != top_key:
                            winner = next(d for d in ranked if d.asset_key == verdict.better_candidate)
                            reason = (verdict.issues[0] if verdict.issues else "El revisor lo considera más adecuado.")
                        else:
                            fails.append(Check(name="judge_rejected", status="fail",
                                               detail="; ".join(verdict.issues) or "no responde la pregunta"))
                    elif verdict.better_candidate and verdict.better_candidate not in valid_ids:
                        error = "juez:id_descartado"
                except Exception as exc:
                    error = f"fallback:{type(exc).__name__}"
            if winner is None and fails:
                winner = engine.fix_candidate(ranked, top_key, intent, ds())
                reason = f"Cumple lo pedido ({fails[0].detail})." if winner else ""

        if winner is not None:
            loser = next(d for d in ranked if d.asset_key == top_key)
            new_ranked = engine.promote(ranked, winner, loser, reason, ds())
            for c in fails:
                c.status = "fixed"
            validation.checks = checks + [c for c in fails if c not in checks]
            detail = f"corregido:{loser.asset_key}→{winner.asset_key}"
            return (
                {"ranked": new_ranked, "review_route": "fix", "review_attempt": attempt, "validation": validation,
                 "_model_used": used_llm},
                error, detail,
            )

        # Sin corrección posible: se aceptan los avisos y, si queda un fallo, la confianza baja al nivel de brecha.
        previous = [c for c in validation.checks if c.status == "fixed"]
        validation.checks = previous + checks + [c for c in fails if c not in checks]
        if fails:
            engine.cap_unresolved(discovery, ds())
            detail = "fallo_sin_resolver:" + ",".join(c.name for c in fails)
        else:
            detail = "aprobado" + (f" ({len(checks)} avisos)" if checks else "")
        return (
            {"discovery": discovery, "review_route": "accept", "review_attempt": attempt, "validation": validation,
             "_model_used": used_llm},
            error, detail,
        )

    # --- cifras agregadas (primer corte del AskFlow) -------------------------------------------
    def compute_node(state):
        search = state.get("search_question") or state["question"]
        plan = figures.plan_figure(search, state["discovery"], deps.catalog, state["user"].visible_ids,
                                   state["intent"].environment_hint)
        if isinstance(plan, str):  # el motivo por el que no se calcula, ya redactado para el usuario
            return {"assumptions": [f"{plan} Te indico qué información usar."], "_model_used": False}, None, "sin_plan"
        t0 = time.perf_counter()
        try:
            figure = figures.run_plan(plan, state["executor"], ds().figures_min_rows)
        except Exception as exc:  # sin permiso sobre la tabla, tiempo agotado o servidor caído: se responde sin cifra
            return ({"assumptions": [FIGURE_FAILED_NOTE], "_model_used": False},
                    f"cifra:{type(exc).__name__}", plan.operation)
        ms = int((time.perf_counter() - t0) * 1000)
        return ({"figure": figure, "db_ms": ms, "_model_used": False}, None,
                f"{plan.operation};grupos={len(figure.groups)};ms={ms}")

    # --- fase 1b: SQL de un LLM cuando la plantilla no basta ----------------------------------
    def ask_node(state):
        # Aunque ningún activo llegue al umbral de recomendación, los mejor puntuados dicen en qué base buscar.
        hints = [d.asset_key for d in state.get("ranked", [])[:ASK_HINTS]]
        search = state.get("search_question") or state["question"]
        try:
            outcome = deps.ask.run(search, state["discovery"], state["user"], state["sql_executor"], hints,
                                   state.get("interpretation"))
        except Exception as exc:  # el LLM o la conexión fallaron: se responde como descubrimiento
            outcome = AskOutcome(False, notes=[FIGURE_FAILED_NOTE], errors=[f"fallo:{type(exc).__name__}"])
        detail = f"intentos={outcome.attempts}" + (f";filas={outcome.data.row_count}" if outcome.data else "")
        error = None if outcome.ok else (",".join(outcome.errors) or None)
        # Si la plantilla va a intentarlo después, sus avisos sustituyen a los de este intento.
        notes = [] if not outcome.ok and wants_figure(state) else list(outcome.notes)
        return {"ask": outcome, "assumptions": notes}, error, detail

    def respond_node(state):
        if state.get("figure") is not None:  # el número nunca lo redacta un modelo
            return {"answer_text": figures.answer_text(state["figure"]), "_model_used": False}, None
        asked = state.get("ask")
        if asked is not None and asked.ok:  # fase 1b: la frase se rellenó con el resultado, sin pasar por un modelo
            return {"answer_text": asked.text, "_model_used": False}, None
        discovery = state["discovery"]
        search = state.get("search_question") or state["question"]
        error = None
        text = None
        out: dict = {}
        used_llm = False
        if discovery.candidates:
            used_llm = not isinstance(deps.narrator, TemplateNarrator)
            try:
                # Al narrador le basta la pregunta actual: la anterior solo hizo falta para buscar.
                asked = state["question"] if search != state["question"] else state["intent"].rewritten_question
                text = deps.narrator.narrate(asked, discovery)
            except Exception as exc:
                error = f"fallback:{type(exc).__name__}"
            if text is not None and not engine.narrative_mentions_ok(text, discovery, deps.catalog):
                error, text = "narrativa_rechazada:objeto_fuera_de_respuesta", None
            elif text is not None and engine.unsafe_generated_text(text):
                error, text = "narrativa_rechazada:contenido_no_permitido", None
            options = engine.area_options(search, discovery, ds())
            if options:  # el mismo dato existe en varias áreas: se responde y además se ofrece precisar
                out["clarification"] = Clarification(question="¿De cuál de estas áreas lo necesitas?", options=options)
        elif deps.guide is not None:
            # La búsqueda no encontró nada: el modelo dice si era una pregunta sobre el asistente o propone cómo
            # precisarla en lenguaje de negocio. Solo elige entre temas fijos y redacta opciones; no nombra objetos.
            used_llm = True
            try:
                known = deps.catalog.names_with_digits(state["user"].visible_ids)
                # Al modelo no le llegan los literales (un documento, una cuenta) que alguien haya escrito (F17).
                advice = deps.guide.advise(strip_literals(state["question"], known),
                                           [strip_literals(h, known) for h in state.get("history", [])])
                if advice.kind == "assistant" and advice.topic in assistant.TOPICS:
                    out["assistant_topic"] = advice.topic
                    out["intent"] = state["intent"].model_copy(update={"intent": "assistant"})
                elif advice.kind == "clarify" and advice.question and advice.options:
                    safe = [o.strip() for o in advice.options if o and o.strip()
                            and not engine.unsafe_generated_text(o) and not engine.looks_technical(o)]
                    if safe and not engine.unsafe_generated_text(advice.question) \
                            and not engine.looks_technical(advice.question):
                        out["clarification"] = Clarification(question=advice.question.strip()[:240],
                                                             options=[o[:160] for o in safe[:4]])
            except Exception as exc:
                error = f"fallback:{type(exc).__name__}"
        if text is None:
            text = fallback_narrator.narrate(search, discovery)
        return {"answer_text": text, "_model_used": used_llm, **out}, error

    def finalize_node(state):
        intent = state.get("intent")
        route = state.get("route")
        env = AnswerEnvelope(trace_id=state["trace_id"], flow="discover",
                             assumptions=list(dict.fromkeys(state.get("assumptions", []))))
        if route == "clarify":
            env.status = "needs_clarification"
            env.clarification = intent.clarification
            env.answer_text = intent.clarification.question if intent.clarification else "¿Puedes precisar qué dato buscas?"
        elif route == "out_of_scope":
            env.status = "rejected"
            env.answer_text = (
                "Eso no puedo hacerlo: solo ayudo a encontrar dónde está la información del banco y qué significa. "
                "No modifico datos ni respondo temas fuera de ese alcance."
            )
        elif route == "assistant" or state.get("assistant_topic"):
            env.answer_text = assistant.answer(state["assistant_topic"], deps.catalog, state["user"].visible_ids,
                                               ask_flow=deps.settings.features.ask_flow)
            env.assumptions = []
        elif state.get("clarification") and not state["discovery"].candidates:
            # No se encontró nada: se dice, y además se ofrece precisar la pregunta. El dato puede no existir en el
            # banco, así que la aclaración acompaña a la respuesta en vez de sustituirla.
            env.discovery = state["discovery"]
            env.clarification = state["clarification"]
            env.answer_text = f"{state['answer_text']} {env.clarification.question}"
            env.confidence = 0.0
        else:
            disc = state["discovery"]
            env.discovery = disc
            env.validation = state.get("validation")
            env.clarification = state.get("clarification")
            env.answer_text = state["answer_text"]
            if state.get("figure") is not None:
                env.flow = "ask"
                env.figure = state["figure"]
            env.confidence = disc.candidates[0].confidence if disc.candidates else 0.0
            env.databases = engine.databases_of(disc)
            env.tables_used = engine.tables_of(disc)
            asked = state.get("ask")
            if asked is not None and asked.ok:
                env.flow, env.data = "ask", asked.data
                env.databases, env.tables_used = [asked.data.database], list(asked.data.tables)
                env.confidence = None  # la del descubrimiento no aplica a un dato calculado
        env.timings_ms = {"total": int((time.perf_counter() - state["started"]) * 1000), "db": state.get("db_ms", 0)}
        record = TraceRecord(
            trace_id=state["trace_id"], user_id=state["user"].user_id, client=state.get("client", "api"),
            question=state["question"], intent=intent.intent if intent else None,
            # La auditoría guarda la consulta y el número de filas, nunca los valores (F11, F17).
            envelope=env.model_copy(update={"data": env.data.redacted()}) if env.data else env,
            steps=list(state.get("steps", [])),
        )
        try:
            deps.audit.write(record)
        except Exception as exc:  # F11: fail-closed
            # Solo el tipo del error (D5): el monitoreo lo convierte en la alerta "Fallo de escritura de auditoría" (OP-05).
            log.error("audit.write_failed", extra={"error_type": type(exc).__name__, "trace_id": state["trace_id"]})
            if not deps.settings.audit.fail_open:
                env = AnswerEnvelope(
                    trace_id=state["trace_id"], status="error",
                    answer_text="No se pudo registrar la auditoría; la respuesta no se entrega.",
                )
        return {"envelope": env}

    g = StateGraph(DiscoverState)
    g.add_node("intent", _timed("intent", "planner", deps, intent_node))
    g.add_node("retrieve", _timed("retrieve", None, deps, retrieve_node, "retrieval_attempt"))
    g.add_node("grade", _timed("grade", "fast", deps, grade_node, None))
    g.add_node("rerank", _timed("rerank", "planner", deps, rerank_node))
    g.add_node("expand", _timed("expand", None, deps, expand_node))
    g.add_node("review", _timed("review", "judge", deps, review_node, "review_attempt"))
    g.add_node("compute", _timed("compute", None, deps, compute_node))
    g.add_node("ask", _timed("ask", "coder", deps, ask_node))
    g.add_node("respond", _timed("respond", "fast", deps, respond_node))
    g.add_node("finalize", finalize_node)  # escribe la auditoría con los pasos anteriores; no se audita a sí mismo
    g.add_edge(START, "intent")
    g.add_conditional_edges(
        "intent", lambda s: s["route"],
        {"discover": "retrieve", "clarify": "finalize", "out_of_scope": "finalize", "assistant": "finalize"}
    )
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", lambda s: s["retrieval_route"], {"retry": "retrieve", "continue": "rerank"})
    g.add_edge("rerank", "expand")
    g.add_edge("expand", "review")
    def after_review(state):
        # Con la fase 1b activa responde primero el SQL de un LLM (entiende filtros, periodos y varias uniones); las
        # cifras de plantilla (decisión 17) quedan de respaldo. Sin la fase 1b, el orden de main no cambia.
        if state["review_route"] == "fix":
            return "fix"
        if wants_llm_sql(state):
            return "ask"
        return "compute" if wants_figure(state) else "accept"

    def after_ask(state):
        asked = state.get("ask")
        return "compute" if (asked is None or not asked.ok) and wants_figure(state) else "respond"

    g.add_conditional_edges("review", after_review,
                            {"fix": "expand", "accept": "respond", "compute": "compute", "ask": "ask"})
    g.add_conditional_edges("ask", after_ask, {"compute": "compute", "respond": "respond"})
    g.add_edge("compute", "respond")
    g.add_edge("respond", "finalize")
    g.add_edge("finalize", END)
    return g.compile()  # sin checkpointer (F17)


class DiscoverService:
    """Punto de entrada que usan la API, el chat, el MCP y la CLI."""

    def __init__(self, deps: DiscoverDeps):
        if deps.graph is None:
            from converdata.graph.estate import EstateGraph

            deps.graph = EstateGraph(deps.catalog, deps.knowledge)
        self.deps = deps
        self.graph = build_discover_graph(deps)

    def rebuild(self) -> None:
        self.graph = build_discover_graph(self.deps)

    def _initial(self, question: str, user: UserContext, history: list[str] | None, client: str,
                 executor=None, sql_executor: QueryExecutor | None = None) -> DiscoverState:
        if user.visible_ids is None:
            raise ValueError("El DiscoverFlow requiere la visibilidad del usuario (F14)")
        return {
            "trace_id": str(uuid.uuid4()),
            "question": question,
            "history": history or [],
            "client": client,
            "executor": executor,
            "sql_executor": sql_executor,
            "user": user,
            "started": time.perf_counter(),
            "assumptions": [],
            "steps": [],
        }

    def run(self, question: str, user: UserContext, history: list[str] | None = None, client: str = "api",
            executor=None, sql_executor: QueryExecutor | None = None) -> AnswerEnvelope:
        """`executor`: cómo ejecutar un agregado con la sesión de quien pregunta (`figures.FigureExecutor`). Solo se
        usa con `features.ask_flow`; sin él, una pregunta de cifras se responde indicando dónde está la información.
        `sql_executor`: fase 1b (`features.ask_llm_sql`), ejecuta el SQL de un LLM ya validado con la sesión."""
        final = self.graph.invoke(self._initial(question, user, history, client, executor, sql_executor))
        return final["envelope"]

    def stream(
        self, question: str, user: UserContext, history: list[str] | None = None, client: str = "api", executor=None,
        sql_executor: QueryExecutor | None = None,
    ) -> Iterator[tuple[str, dict]]:
        """Eventos por nodo (`step`) y, al final, la respuesta (`answer`)."""
        for update in self.graph.stream(self._initial(question, user, history, client, executor, sql_executor),
                                        stream_mode="updates"):
            for node, payload in update.items():
                if node == "finalize":
                    yield "answer", payload["envelope"].model_dump(by_alias=True)
                else:
                    yield "step", {"node": node, "label": STEP_LABELS.get(node, node)}
