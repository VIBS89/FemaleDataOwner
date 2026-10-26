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
import operator
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Iterator, TypedDict

from langgraph.graph import END, START, StateGraph

from converdata.audit.recorder import AuditSink, InMemoryAuditSink, StepRecord, TraceRecord
from converdata.catalog.store import Catalog, KnowledgeBase
from converdata.config import OwnersDirectory, Settings
from converdata.discovery import engine
from converdata.discovery.deterministic import RuleBasedIntentClassifier, ScoreReranker, TemplateNarrator
from converdata.discovery.expansion import QueryPlan, lexicon_variant, plan_query
from converdata.discovery.ports import IntentClassifier, Narrator, QueryExpander, Reranker, Reviewer
from converdata.memory.base import VectorStore
from converdata.models.discovery import AnswerEnvelope, Check, Discovery, Validation
from converdata.models.identity import UserContext
from converdata.models.intent import IntentResult

MAX_RETRIEVAL_ATTEMPTS = 2  # C: búsqueda original + una reformulación
MAX_REVIEW_ATTEMPTS = 2  # B: revisión + una corrección

STEP_LABELS = {
    "intent": "Interpretando la pregunta",
    "retrieve": "Buscando en catálogo, diccionarios, documentos y ETL",
    "grade": "Calificando lo encontrado",
    "rerank": "Priorizando candidatos",
    "expand": "Agregando ubicaciones, reglas, relaciones y responsables",
    "review": "Revisando el resultado",
    "respond": "Redactando la respuesta",
    "finalize": "Registrando la auditoría",
}


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
    graph: object | None = None  # EstateGraph (F19); lo construye `DiscoverService` si falta
    audit: AuditSink = field(default_factory=InMemoryAuditSink)
    model_names: Mapping[str, str] = field(default_factory=dict)  # rol → proveedor:modelo (`audit_step.model`)


class DiscoverState(TypedDict, total=False):
    trace_id: str
    question: str
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

    def intent_node(state):
        error = None
        try:
            result = deps.intent_classifier.classify(state["question"], state.get("history", []))
        except Exception as exc:  # throttling, timeout o salida no parseable → reglas
            error = f"fallback:{type(exc).__name__}"
            result = fallback_intent.classify(state["question"], state.get("history", []))
        assumptions: list[str] = []
        if result.intent == "out_of_scope":
            route = "out_of_scope"
        elif result.intent == "ambiguous" or result.confidence < 0.6:
            route = "clarify"
        elif result.intent in ("data_query", "procedure") and not deps.settings.features.ask_flow:
            # F3: fase 1a sin AskFlow → se responde como descubrimiento indicando dónde están los datos.
            route = "discover"
            assumptions.append("La consulta de datos no está habilitada en esta fase; te indico dónde están los datos.")
            result = result.model_copy(update={"intent": "discovery"})
        else:
            route = "discover"
        return {"intent": result, "route": route, "assumptions": assumptions}, error

    # --- D: recuperación con plan de consultas ---------------------------------------------
    def retrieve_node(state):
        intent = state["intent"]
        plan = state.get("plan") or plan_query(
            intent.rewritten_question or state["question"], intent.business_context,
            patterns().query_expansion, ds().variant_weight,
        )
        retrieval = engine.retrieve(
            state["question"], intent, state["user"], deps.store, deps.catalog, deps.knowledge, ds(), plan,
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
        if deps.expander is not None:
            try:
                weak = [sorted(c)[0] for c in plan.concepts]
                variants = deps.expander.expand(state["intent"].rewritten_question, weak)
                used_llm = True
            except Exception as exc:
                error = f"fallback:{type(exc).__name__}"
        if not variants:
            lex = lexicon_variant(state["question"])
            variants = [lex] if lex else []
        new = plan.add_variants([v for v in variants if isinstance(v, str)][:3], ds().variant_weight)
        if not new:
            return {"retrieval_route": "continue", "_model_used": used_llm}, error, f"calidad={quality:.2f};sin_reformulacion"
        return (
            {"plan": plan, "retrieval_route": "retry", "_model_used": used_llm},
            error,
            f"calidad={quality:.2f}→reintento({len(new)} variantes)",
        )

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
        return {"discovery": discovery}, None, detail

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

    def respond_node(state):
        discovery = state["discovery"]
        error = None
        text = None
        if discovery.candidates:
            try:
                text = deps.narrator.narrate(state["intent"].rewritten_question, discovery)
            except Exception as exc:
                error = f"fallback:{type(exc).__name__}"
            if text is not None and not engine.narrative_mentions_ok(text, discovery, deps.catalog):
                error, text = "narrativa_rechazada:objeto_fuera_de_respuesta", None
        if text is None:
            text = fallback_narrator.narrate(state["question"], discovery)
        return {"answer_text": text}, error

    def finalize_node(state):
        intent = state.get("intent")
        route = state.get("route")
        env = AnswerEnvelope(trace_id=state["trace_id"], flow="discover", assumptions=state.get("assumptions", []))
        if route == "clarify":
            env.status = "needs_clarification"
            env.clarification = intent.clarification
            env.answer_text = intent.clarification.question if intent.clarification else "¿Puedes precisar qué dato buscas?"
        elif route == "out_of_scope":
            env.status = "rejected"
            env.answer_text = (
                "Solo puedo ayudarte a descubrir dónde están los datos y qué significan; "
                "no modifico información ni respondo temas fuera de ese alcance."
            )
        else:
            disc = state["discovery"]
            env.discovery = disc
            env.validation = state.get("validation")
            env.answer_text = state["answer_text"]
            env.confidence = disc.candidates[0].confidence if disc.candidates else 0.0
            env.databases = engine.databases_of(disc)
            env.tables_used = engine.tables_of(disc)
        env.timings_ms = {"total": int((time.perf_counter() - state["started"]) * 1000), "db": 0}
        record = TraceRecord(
            trace_id=state["trace_id"], user_id=state["user"].user_id, client=state.get("client", "api"),
            question=state["question"], envelope=env, intent=intent.intent if intent else None,
            steps=list(state.get("steps", [])),
        )
        try:
            deps.audit.write(record)
        except Exception:  # F11: fail-closed
            if not deps.settings.audit.fail_open:
                env = AnswerEnvelope(
                    trace_id=state["trace_id"], status="error",
                    answer_text="No se pudo registrar la auditoría; la respuesta no se entrega.",
                )
        return {"envelope": env}

    g = StateGraph(DiscoverState)
    g.add_node("intent", _timed("intent", "planner", deps, intent_node))
    g.add_node("retrieve", _timed("retrieve", "embed", deps, retrieve_node, "retrieval_attempt"))
    g.add_node("grade", _timed("grade", "fast", deps, grade_node, None))
    g.add_node("rerank", _timed("rerank", "planner", deps, rerank_node))
    g.add_node("expand", _timed("expand", None, deps, expand_node))
    g.add_node("review", _timed("review", "judge", deps, review_node, "review_attempt"))
    g.add_node("respond", _timed("respond", "fast", deps, respond_node))
    g.add_node("finalize", finalize_node)  # escribe la auditoría con los pasos anteriores; no se audita a sí mismo
    g.add_edge(START, "intent")
    g.add_conditional_edges(
        "intent", lambda s: s["route"], {"discover": "retrieve", "clarify": "finalize", "out_of_scope": "finalize"}
    )
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", lambda s: s["retrieval_route"], {"retry": "retrieve", "continue": "rerank"})
    g.add_edge("rerank", "expand")
    g.add_edge("expand", "review")
    g.add_conditional_edges("review", lambda s: s["review_route"], {"fix": "expand", "accept": "respond"})
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

    def _initial(self, question: str, user: UserContext, history: list[str] | None, client: str) -> DiscoverState:
        if user.visible_ids is None:
            raise ValueError("El DiscoverFlow requiere la visibilidad del usuario (F14)")
        return {
            "trace_id": str(uuid.uuid4()),
            "question": question,
            "history": history or [],
            "client": client,
            "user": user,
            "started": time.perf_counter(),
            "assumptions": [],
            "steps": [],
        }

    def run(self, question: str, user: UserContext, history: list[str] | None = None, client: str = "api") -> AnswerEnvelope:
        final = self.graph.invoke(self._initial(question, user, history, client))
        return final["envelope"]

    def stream(
        self, question: str, user: UserContext, history: list[str] | None = None, client: str = "api"
    ) -> Iterator[tuple[str, dict]]:
        """Eventos por nodo (`step`) y, al final, la respuesta (`answer`)."""
        for update in self.graph.stream(self._initial(question, user, history, client), stream_mode="updates"):
            for node, payload in update.items():
                if node == "finalize":
                    yield "answer", payload["envelope"].model_dump(by_alias=True)
                else:
                    yield "step", {"node": node, "label": STEP_LABELS.get(node, node)}
