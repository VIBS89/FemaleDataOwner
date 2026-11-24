"""Pasos deterministas del DiscoverFlow (F22): recuperación, agrupación, expansión, confianza y guardas.

Todo lo que se devuelve pasa por el filtro de visibilidad del usuario (F14): candidatos, ubicaciones, alternativas,
relaciones, linaje, reglas y evidencias.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from discovery_data_agent.catalog.ids import is_column_key, short_name, table_key
from discovery_data_agent.catalog.store import Catalog, KnowledgeBase
from discovery_data_agent.config import DiscoverySettings, OwnersDirectory
from discovery_data_agent.discovery.deterministic import is_figures_question
from discovery_data_agent.discovery.expansion import ANALYSIS_TERMS, QueryPlan, concepts_of, content_words, decompose, plan_query
from discovery_data_agent.discovery.ports import RerankItem, RerankScore
from discovery_data_agent.memory.base import VectorStore
from discovery_data_agent.memory.text import normalized_name, strip_accents, tokenize
from discovery_data_agent.models.discovery import (
    Alternative,
    Candidate,
    Check,
    Discovery,
    Evidence,
    JoinPath,
    Lineage,
    Location,
    Owners,
    Related,
    RuleRef,
)
from discovery_data_agent.models.identity import UserContext
from discovery_data_agent.models.intent import IntentResult

EVIDENCE_STRENGTH = {"human": 1.0, "data_dictionary": 0.9, "ms_description": 0.8, "document": 0.6, "generated": 0.3}
_KNOWLEDGE_SOURCE = {
    "data_dictionary": "data_dictionary",
    "document": "document",
    "glossary": "document",
    "annotation": "annotation",
    "etl": "etl",
    "business_rule": "business_rule",
}
# Pesos con que cada tipo de hit suma a la puntuación bruta de recuperación de un activo.
W_TABLE_CONTEXT = 0.5
W_KNOWLEDGE = 0.5
W_GOLDEN = 1.0
W_ENTITY = 0.5


@dataclass
class Draft:
    """Candidato en construcción, identificado por su `asset_key` lógico."""

    asset_key: str
    kind: str
    raw: float = 0.0
    sources: set[str] = field(default_factory=set)
    evidence: list[Evidence] = field(default_factory=list)
    golden_confirmation: float = 0.0
    unknown_qualifiers: bool = False  # parte de la pregunta que nadie conoce se descontó: nunca es una respuesta segura
    retrieval_norm: float = 0.0
    coverage: float = 0.0  # fracción de los términos de la pregunta que cubre el activo
    precision: float = 1.0  # fracción del nombre de su tabla que la pregunta nombra
    graph_coverage: float = 0.0  # cobertura contando tablas unidas por FK a 1–2 saltos (no ordena; ver _graph_coverage)
    context_text: list[str] = field(default_factory=list)  # textos de conocimiento vinculados (para la cobertura)
    relevance: float = 0.0
    why: str = ""
    confidence: float = 0.0
    strength: float = 0.0  # la confianza antes de aplicar los topes: desempata a los que el tope deja iguales
    description: str | None = None
    description_source: str = "generated"

    def add_evidence(self, ev: Evidence) -> None:
        if all((e.kind, e.source) != (ev.kind, ev.source) for e in self.evidence):
            self.evidence.append(ev)


@dataclass
class Retrieval:
    drafts: dict[str, Draft]
    entity_tables: dict[str, list[str]] = field(default_factory=dict)  # entidad → tablas visibles
    concepts: list[frozenset[str]] = field(default_factory=list)  # conceptos de la pregunta (caminos de unión)
    secondary_parts: list[list[frozenset[str]]] = field(default_factory=list)  # sub-preguntas a unir por el grafo
    secondary_texts: list[str] = field(default_factory=list)


# --- paso 1b: ¿la pregunta nombra una entidad? ------------------------------------------------------
_PLURAL_SUBJECT = re.compile(r"\bdonde (?:estan|se guardan|se encuentran|quedan) (?:los|las|todos los|todas las)\s+(.+)")


def entity_kind_hint(question: str, intent: IntentResult, catalog: Catalog, vis) -> str | None:
    """"¿Dónde están los arrendamientos financieros de vehículos?" pide la tabla de arrendamientos; "¿dónde están los
    días de mora?", una columna. La diferencia la da el catálogo: si lo primero que se nombra en plural es el nombre de
    una tabla o vista que el usuario ve, se pide esa entidad. Solo decide cuando la intención no trajo ya un tipo."""
    if intent.asset_kind_hint is not None or intent.intent != "discovery":
        return intent.asset_kind_hint
    match = _PLURAL_SUBJECT.search(strip_accents(question).lower())
    # Una pregunta compuesta ("las transacciones rechazadas y su motivo") pide además un dato concreto: no se fuerza.
    if not match or len(decompose(question)) > 1:
        return None
    known = catalog.names_with_digits(vis)
    subject = concepts_of(match.group(1), True, known)[:2]
    if not subject:
        return None
    visible = [obj for obj in catalog.objects if obj.id in vis]
    # "Los pagos mínimos", "las cuotas mensuales": si una columna se llama así, se pide ese atributo y no la entidad.
    # Se compara con las palabras tal como se escribieron: "los usuarios bloqueados" no pide la columna de estado.
    literal = [set(tokenize(w)) for w in content_words(match.group(1), known)[:2]]
    if len(literal) == 2 and all(literal) and any(
        literal[0] & tokens and literal[1] & tokens
        for obj in visible for tokens in (set(tokenize(c.name)) for c in obj.columns)
    ):
        return None
    if any(obj.kind in ("table", "view") and subject[0] & set(tokenize(obj.name)) for obj in visible):
        return "table"
    return None


# --- paso 2: recuperación híbrida filtrada por visibilidad --------------------------------------
def retrieve(
    question: str,
    intent: IntentResult,
    user: UserContext,
    store: VectorStore,
    catalog: Catalog,
    kb: KnowledgeBase,
    settings: DiscoverySettings,
    plan: QueryPlan | None = None,
    graph=None,
) -> Retrieval:
    """`plan` trae las consultas ponderadas (pregunta original + variantes, patrón D) y los conceptos de la pregunta.
    Sin plan, una sola consulta y conceptos = stems de la pregunta (comportamiento base)."""
    vis = user.visible_ids
    if plan is None:
        plan = plan_query(intent.rewritten_question or question, intent.business_context, False, 0.0,
                          known=catalog.names_with_digits(vis))
    concepts = plan.concepts
    drafts: dict[str, Draft] = {}

    def draft(key: str) -> Draft:
        if key not in drafts:
            obj = catalog.copies(key)[0]
            kind = "column" if is_column_key(key) else obj.kind
            drafts[key] = Draft(key, kind)
        return drafts[key]

    exploration = intent.intent == "exploration"
    table_scores: dict[str, float] = {}
    knowledge_hits: dict[str, tuple] = {}
    for query, weight in plan.queries:
        if not exploration:
            for hit in store.search_columns(query, k=settings.k_columns, visible_ids=vis):
                d = draft(hit.asset_key)
                d.raw += weight * hit.score
                d.sources.add("catalog")
        for hit in store.search_tables(query, k=settings.k_tables, visible_ids=vis):
            table_scores[hit.asset_key] = table_scores.get(hit.asset_key, 0.0) + weight * hit.score
            d = draft(hit.asset_key)
            d.raw += weight * hit.score
            d.sources.add("catalog")
        for hit in store.search_knowledge(
            query, k=settings.k_knowledge, visible_ids=vis, groups=user.groups,
            kinds=["glossary", "business_rule", "document", "annotation", "etl", "data_dictionary"],
        ):
            prev = knowledge_hits.get(hit.item.id)
            knowledge_hits[hit.item.id] = (hit.item, (prev[1] if prev else 0.0) + weight * hit.score)
    # El contexto de la tabla ("onboarding", "usuarios") refuerza a sus columnas ya recuperadas.
    for d in drafts.values():
        if d.kind == "column" and table_key(d.asset_key) in table_scores:
            d.raw += W_TABLE_CONTEXT * table_scores[table_key(d.asset_key)]

    for item, score in knowledge_hits.values():
        # Un fragmento suma en proporción a cuánto de la pregunta cubre (no solo por su posición en el ranking).
        item_cov = concept_coverage(concepts, set(tokenize(item.text)))
        for key in item.asset_keys:
            if exploration and is_column_key(key):
                key = table_key(key)
            if not catalog.is_visible(key, vis):
                continue
            d = draft(key)
            d.raw += W_KNOWLEDGE * score * item_cov
            if item.kind != "etl":
                d.context_text.append(item.text)
            d.sources.add(_KNOWLEDGE_SOURCE[item.kind])
            d.add_evidence(Evidence(kind=item.kind, source=item.source, reviewed=item.reviewed))

    for hit in store.search_golden_discovery(question, k=settings.k_golden, visible_ids=vis):
        g = hit.golden
        for key in g.asset_keys:
            d = draft(key)
            # Una pregunta confirmada solo pesa en proporción a su parecido con la actual.
            d.raw += W_GOLDEN * hit.score * hit.similarity
            if hit.similarity >= settings.golden_similarity_min:
                d.sources.add("golden")
                label = "confirmado por el responsable" if g.confirmed_by == "steward" else f"{g.confirmations} confirmaciones previas"
                d.add_evidence(Evidence(kind="golden_discovery", source=label, reviewed=g.confirmed_by == "steward"))
                d.context_text.append(g.template)
                if g.confirmed_by == "steward":
                    d.golden_confirmation = 1.0
                elif g.confirmations >= 2:
                    d.golden_confirmation = max(d.golden_confirmation, 0.7)

    # F19 `where_is`: entidades de negocio nombradas en la pregunta → sus tablas visibles en todas las BDs.
    entity_tables: dict[str, list[str]] = {}
    q_tokens = set(tokenize(question))
    top_raw = max((d.raw for d in drafts.values()), default=0.0) or 1.0
    for entity in kb.entities:
        names = [entity.name, *entity.synonyms]
        if not any(set(tokenize(n)) and set(tokenize(n)) <= q_tokens for n in names):
            continue
        visible_tables = [t for t in entity.tables if catalog.is_visible(t, vis)]
        if not visible_tables:
            continue
        entity_tables[entity.name] = visible_tables
        for t in visible_tables:
            d = draft(t)
            # La tabla canónica recibe el refuerzo completo; las copias en otras BDs, una parte.
            d.raw += W_ENTITY * top_raw * (0.2 if t == entity.canonical else 0.1)
            d.sources.add("estate")
            d.context_text.append(" ".join(names))

    best = max((d.raw for d in drafts.values()), default=0.0)
    # Pregunta compuesta: el orden lo decide la primera sub-pregunta; el resto lo resuelven los caminos de unión.
    asked = plan.primary_concepts or concepts
    # Cuando se pide una tabla, sus columnas también la describen (con menos peso que su nombre y su descripción).
    wants_table = intent.asset_kind_hint == "table"
    terms = {}
    for d in drafts.values():
        d.retrieval_norm = d.raw / best if best else 0.0
        _set_description(d, catalog, vis)
        terms[d.asset_key] = _asset_terms_split(d, catalog, vis, columns_as_weak=wants_table)
    weights = qualifier_weights(asked, [s | w for s, w in terms.values()]) if wants_table else None
    for d in drafts.values():
        strong, weak = terms[d.asset_key]
        d.coverage = round(weighted_coverage(asked, strong, weak, weights), 4)
        d.precision = name_precision(d.asset_key, asked)
    # Relativa al mejor: si ningún activo se llama como lo pedido, la precisión no distingue y no descuenta a nadie.
    best_precision = max((d.precision for d in drafts.values()), default=0.0)
    for d in drafts.values():
        d.precision = round(d.precision / best_precision, 4) if best_precision else 1.0
        d.unknown_qualifiers = bool(weights) and any(w < 1.0 for w in weights)
    if graph is not None:
        _graph_coverage(drafts.values(), concepts, graph, catalog, vis)
    return Retrieval(drafts, entity_tables, concepts, plan.secondary_parts, plan.secondary_texts)


PRECISION_WEIGHT = 0.15


def name_precision(asset_key: str, concepts: list[frozenset[str]]) -> float:
    """Cuánto del nombre de la tabla del activo nombra la pregunta. "El estado del préstamo" lo cubren por igual `Prestamos.Estado` y
    `CuotasPrestamo.Estado`, pero solo el primero se llama exactamente así: el segundo trae además "cuotas", que nadie
    pidió. Sirve para elegir entre activos que cubren lo mismo; pesa poco (`PRECISION_WEIGHT`)."""
    tokens = {t for t in tokenize(short_name(table_key(asset_key))) if len(t) > 2}
    if not tokens or not concepts:
        return 1.0
    return round(sum(1 for t in tokens if any(t in c for c in concepts)) / len(tokens), 4)


def precision_factor(d: "Draft") -> float:
    """Solo entre activos sin describir: ahí el nombre es lo único que hay para elegir. Uno con descripción de una
    persona o de un diccionario ya dice qué es, se llame como se llame (`Users` para "clientes")."""
    if d.description_source != "generated":
        return 1.0
    return 1.0 - PRECISION_WEIGHT * (1.0 - d.precision)


def kept_analysis_terms(question: str, catalog: Catalog, vis) -> frozenset[str]:
    """Términos de cálculo de la pregunta que en realidad son parte del nombre de un dato: "monto total del pago" →
    `MontoTotal`, "cuota anual" → `CuotaAnual`. Uno se conserva si, con otra palabra de la pregunta, forma el nombre de
    una columna que el usuario ve."""
    words = content_words(question, catalog.names_with_digits(vis))
    stems = {w: set(tokenize(w)) for w in words}
    terms = [w for w in words if w in ANALYSIS_TERMS and stems[w]]
    if not terms:
        return frozenset()
    kept = set()
    column_tokens = [set(tokenize(c.name)) for obj in catalog.objects if obj.id in vis for c in obj.columns]
    for term in terms:
        others = [stems[w] for w in words if w != term and w not in ANALYSIS_TERMS and stems[w]]
        if any(stems[term] <= tokens and any(o & tokens for o in others) for tokens in column_tokens):
            kept.add(term)
    return frozenset(kept)


GRAPH_HOP_WEIGHT = {1: 0.6, 2: 0.4}
MULTI_HOP_MIN = 0.6


def _table_terms(table: str, catalog: Catalog, vis, cache: dict) -> set[str]:
    """Términos de una tabla vecina: su nombre, descripción, sinónimos y columnas (con sus descripciones)."""
    if table not in cache:
        copies = catalog.visible_copies(table, vis)
        texts = []
        if copies:
            t = copies[0]
            texts = [t.name, t.description or "", " ".join(t.synonyms)]
            for c in t.columns:
                texts += [c.name, c.description or "", " ".join(c.synonyms)]
        cache[table] = set(tokenize(" ".join(texts)))
    return cache[table]


def _graph_coverage(drafts, concepts, graph, catalog: Catalog, vis) -> None:
    """Un activo también "cubre" las partes de la pregunta que resuelven tablas unidas a la suya por FK a 1–2 saltos,
    con menos peso. No cambia el orden (eso favorecería a las tablas puente como Clientes); solo evita que una pregunta
    de varios saltos ("mora de las cuotas y DUI del cliente") se quede sin candidatos y alimenta la calificación (C)."""
    if not concepts:
        return
    cache: dict = {}
    near_cache: dict = {}
    for d in drafts:
        own = _asset_terms(d, catalog, vis)
        tkey = table_key(d.asset_key)
        if tkey not in near_cache:
            near_cache[tkey] = graph.nearby_tables(tkey, vis)
        score = 0.0
        for concept in concepts:
            if concept & own:
                score += 1.0
                continue
            hops = [h for t, h in near_cache[tkey].items() if concept & _table_terms(t, catalog, vis, cache)]
            if hops:
                score += GRAPH_HOP_WEIGHT.get(min(hops), 0.0)
        d.graph_coverage = round(max(d.coverage, score / len(concepts)), 4)


def concept_coverage(concepts: list[frozenset[str]], terms: set[str]) -> float:
    """Fracción de conceptos de la pregunta presentes (el término o alguna de sus traducciones)."""
    if not concepts:
        return 0.0
    return sum(1 for c in concepts if c & terms) / len(concepts)


def grade_retrieval(retrieval: Retrieval, top: int = 5) -> float:
    """Patrón C: calidad de la recuperación = mejor cobertura entre los activos mejor recuperados."""
    drafts = sorted(retrieval.drafts.values(), key=lambda d: (-d.retrieval_norm, d.asset_key))[:top]
    return max((max(d.coverage, d.graph_coverage) for d in drafts), default=0.0)


WEAK_TERM_WEIGHT = 0.5


UNKNOWN_QUALIFIER_WEIGHT = 0.25


def qualifier_weights(concepts: list[frozenset[str]], known_terms: list[set[str]]) -> list[float]:
    """Peso de cada concepto cuando se pide una tabla. El catálogo no guarda valores de datos (F1), así que no puede
    conocer los calificativos que en realidad son valores: "platino", "de vehículos", "de San Salvador". Un concepto
    que ningún activo recuperado nombra pesa la cuarta parte: no sirve para elegir entre ellos, pero sigue contando como
    parte de la pregunta sin cubrir. El primero (la entidad que se pide) nunca se descuenta: si nadie lo conoce, es
    una brecha."""
    return [1.0 if i == 0 or any(c & terms for terms in known_terms) else UNKNOWN_QUALIFIER_WEIGHT
            for i, c in enumerate(concepts)]


def weighted_coverage(concepts: list[frozenset[str]], strong: set[str], weak: set[str],
                      weights: list[float] | None = None) -> float:
    """Cobertura donde un concepto que solo aparece en texto débil (generado por IA sin revisar, o el nombre de una
    columna cuando se pide su tabla) cuenta la mitad. `weights`: peso de cada concepto (por defecto, todos igual)."""
    if not concepts:
        return 0.0
    weights = weights or [1.0] * len(concepts)
    total = sum(w * (1.0 if c & strong else WEAK_TERM_WEIGHT if c & weak else 0.0) for c, w in zip(concepts, weights))
    return total / sum(weights)


def _asset_terms_split(d: Draft, catalog: Catalog, vis, columns_as_weak: bool = False) -> tuple[set[str], set[str]]:
    """(términos fuertes, términos débiles). Débiles: descripciones `generated` (sugeridas por IA, sin revisar) y, con
    `columns_as_weak`, los nombres y sinónimos de las columnas de una tabla."""
    strong_texts = list(d.context_text)
    weak_texts: list[str] = []
    copies = catalog.visible_copies(d.asset_key, vis)
    if copies:
        t = copies[0]
        strong_texts += [t.name, " ".join(t.synonyms)]
        # Solo si también ve la tabla referenciada: si no, la confianza delataría su nombre (F14).
        strong_texts += [fk.ref.split(".")[-1] for fk in t.foreign_keys if catalog.is_visible(fk.ref, vis)]
        if d.kind == "column":
            found = catalog.column(d.asset_key, vis)
            if found:
                col = found[1]
                strong_texts += [col.name, " ".join(col.synonyms)]
                (weak_texts if col.description_source == "generated" else strong_texts).append(col.description or "")
            weak_texts.append(t.description or "")  # el contexto de la tabla ayuda a la columna, pero no decide
        else:
            (weak_texts if t.description_source == "generated" else strong_texts).append(t.description or "")
            if columns_as_weak:
                weak_texts += [text for c in t.columns for text in (c.name, " ".join(c.synonyms))]
    strong = set(tokenize(" ".join(strong_texts)))
    return strong, set(tokenize(" ".join(weak_texts))) - strong


def _asset_terms(d: Draft, catalog: Catalog, vis) -> set[str]:
    texts = list(d.context_text)
    copies = catalog.visible_copies(d.asset_key, vis)
    if copies:
        t = copies[0]
        texts += [t.name, " ".join(t.synonyms)]
        # Las tablas que referencia por FK también la describen (CustomerConsents → Users: "del usuario").
        texts += [fk.ref.split(".")[-1] for fk in t.foreign_keys if catalog.is_visible(fk.ref, vis)]
        if d.kind == "column":
            found = catalog.column(d.asset_key, vis)
            if found:
                col = found[1]
                texts += [col.name, col.description or "", " ".join(col.synonyms)]
        else:
            # La descripción de la tabla solo cuenta para la tabla: sumada a cada columna, todas las columnas de una
            # tabla bien descrita "cubrirían" la pregunta y se perdería el significado propio de cada una.
            texts.append(t.description or "")
        # Una tabla no se mide por los nombres de sus columnas: si no, "tipo de dispositivo" lo cubriría mejor
        # la tabla UserDevices (por su columna DeviceType) que la propia columna.
    return set(tokenize(" ".join(texts)))


def _set_description(d: Draft, catalog: Catalog, vis) -> None:
    if d.kind == "column":
        found = catalog.column(d.asset_key, vis)
        if found:
            d.description, d.description_source = found[1].description, found[1].description_source
    else:
        copies = catalog.visible_copies(d.asset_key, vis)
        if copies:
            d.description, d.description_source = copies[0].description, copies[0].description_source
    d.add_evidence(Evidence(kind=d.description_source, source="catálogo", reviewed=d.description_source == "human"))


# --- paso 4: preparación y aplicación del reranking ------------------------------------------
def kind_factor(kind: str, hint: str | None) -> float:
    if hint is None:
        return 1.0
    if hint == "column":
        return 1.0 if kind == "column" else 0.7
    if hint == "table":
        return 1.0 if kind == "table" else 0.9 if kind == "view" else 0.7
    return 1.0


# Tipos semánticos de columna por reglas (F19 paso 5): qué rol pide la pregunta y qué rol cumple cada columna.
_ROLE_QUERY = {
    "identifier": re.compile(r"\b(identificador\w*|identifica\w*|codigo|id|llave|clave)\b"),
    "date": re.compile(r"\b(fecha\w*|cuando|dia|mes|ano|semana|trimestre|periodo)\b"),
    "status": re.compile(r"\b(estado\w*|estatus|situacion)\b"),
    "amount": re.compile(r"\b(monto\w*|importe\w*|saldo\w*|salario\w*|valor|dinero|consumo\w*|deuda\w*)\b"),
}
_ROLE_NAME = {
    "identifier": re.compile(r"(id|code|key|codigo|numero)$|^(codigo|numero|id)[A-Z]", re.I),
    "date": re.compile(r"(date|fecha|at)$|^fecha", re.I),
    "status": re.compile(r"(status|estado)$", re.I),
    "amount": re.compile(r"(amount|monto|importe|saldo|salario|balance)$|^(monto|saldo|importe|valor)[A-Z]", re.I),
}
ROLE_MISMATCH = 0.85


def query_role(text: str) -> str | None:
    from discovery_data_agent.memory.text import strip_accents

    q = strip_accents(text).lower()
    # "El consumo promedio de los últimos 6 meses" pide un monto: ahí el periodo dice cuándo, no qué dato.
    if is_figures_question(text) and _ROLE_QUERY["amount"].search(q):
        return "amount"
    return next((role for role, rx in _ROLE_QUERY.items() if rx.search(q)), None)


def requested_role(intent: IntentResult) -> str | None:
    """Rol de dato pedido, salvo que la intención ya pida una tabla (exploración, cifras, "en qué tabla")."""
    if intent.asset_kind_hint == "table":
        return None
    return query_role(intent.rewritten_question)


def column_role(name: str, description: str | None) -> str | None:
    from discovery_data_agent.memory.text import strip_accents

    desc = strip_accents(description or "").lower()
    for role, rx in _ROLE_NAME.items():
        if rx.search(name):
            return role
    if desc.startswith(("identificador", "codigo", "llave")):
        return "identifier"
    return None


def role_factor(d: Draft, role: str | None) -> float:
    if role is None:
        return 1.0
    if d.kind != "column":
        return ROLE_MISMATCH  # pedir una llave, una fecha o un monto es pedir una columna, no una tabla
    return 1.0 if column_role(short_name(d.asset_key), d.description) == role else ROLE_MISMATCH


def shortlist(retrieval: Retrieval, intent: IntentResult, settings: DiscoverySettings) -> list[Draft]:
    exploration = intent.intent == "exploration"
    pool = [d for d in retrieval.drafts.values() if not (exploration and d.kind == "column")]
    if intent.asset_kind_hint == "table" and any(
        d.kind != "column" and d.coverage**1.5 * kind_factor(d.kind, "table") >= settings.min_relevance for d in pool
    ):
        # Se pide una tabla y hay al menos una que responde: sus columnas no compiten con ella. Si ninguna tabla
        # alcanza, las columnas se conservan (la pregunta pudo clasificarse mal).
        pool = [d for d in pool if d.kind != "column"]
    role = requested_role(intent)

    def score(d: Draft) -> float:
        # Puntaje de búsqueda y cobertura de la pregunta a partes iguales: solo con el primero, una columna que cubre
        # toda la pregunta puede quedar fuera de los 25 que se priorizan (pasaba con preguntas compuestas).
        base = 0.5 * d.retrieval_norm + 0.5 * max(d.coverage, d.graph_coverage * 0.8)
        return base * kind_factor(d.kind, intent.asset_kind_hint) * role_factor(d, role) * precision_factor(d)

    pool.sort(key=lambda d: (-score(d), d.asset_key))
    return pool[: settings.rerank_max]


def rerank_items(drafts: list[Draft], kb: KnowledgeBase) -> list[RerankItem]:
    return [
        RerankItem(
            id=d.asset_key,
            kind=d.kind,
            description=d.description,
            description_source=d.description_source,
            rules=[r.id for r in kb.rules_for(d.asset_key)],
            evidence=[f"{e.kind}:{e.source}" for e in d.evidence],
        )
        for d in drafts
    ]


def deterministic_relevance(drafts: list[Draft], intent: IntentResult) -> dict[str, float]:
    """Sustituto determinista del reranker: cobertura de los términos de la pregunta (la posición en la recuperación
    ya pesa aparte en la confianza), ajustada por el tipo de activo y el rol semántico pedidos."""
    role = requested_role(intent)
    return {
        d.asset_key: round(
            d.coverage**1.5 * kind_factor(d.kind, intent.asset_kind_hint) * role_factor(d, role)
            * precision_factor(d), 4
        )
        for d in drafts
    }


def apply_rerank(drafts: list[Draft], scores: list[RerankScore], fallback: dict[str, float]) -> list[str]:
    """Aplica la salida del reranker. Ids desconocidos se descartan (no puede inventar candidatos); los omitidos
    conservan la relevancia determinista. Devuelve los ids rechazados para la auditoría."""
    by_id = {d.asset_key: d for d in drafts}
    rejected, seen = [], set()
    for s in scores:
        if s.id not in by_id or s.id in seen:
            rejected.append(s.id)
            continue
        seen.add(s.id)
        by_id[s.id].relevance = s.relevance
        why = s.why.strip().splitlines()[0][:240] if s.why and s.why.strip() else ""
        by_id[s.id].why = "" if unsafe_generated_text(why) else why  # vacía → se usa la justificación determinista
    for d in drafts:
        if d.asset_key not in seen:
            d.relevance = fallback.get(d.asset_key, 0.0)
    return rejected


def decisive(ranked: list[Draft], settings: DiscoverySettings) -> bool:
    """Patrón E (cascada): el resultado determinista es claro y no hace falta el reranker LLM."""
    if not ranked:
        return True
    top = ranked[0].confidence
    second = ranked[1].confidence if len(ranked) > 1 else 0.0
    return top >= settings.cascade_min_confidence and top - second >= settings.cascade_margin


# --- patrón B: revisión del resultado (evaluador-optimizador) -----------------------------------
# En palabras de quien pregunta: el motivo se muestra en la respuesta.
KIND_LABEL = {"table": "una tabla", "view": "una vista", "column": "un dato suelto", "procedure": "un procedimiento"}
ROLE_LABEL = {"identifier": "identificador", "date": "fecha", "status": "estado", "amount": "monto"}


def review_checks(discovery: Discovery, ranked: list[Draft], intent: IntentResult, settings: DiscoverySettings) -> list[Check]:
    """Chequeos deterministas sobre el candidato principal. `fail` exige corrección; `warn` solo informa."""
    if not discovery.candidates:
        return []
    top = discovery.candidates[0]
    d = next((x for x in ranked if x.asset_key == top.asset_key), None)
    if d is None:
        return []
    checks: list[Check] = []
    hint = intent.asset_kind_hint
    if hint in ("column", "table") and kind_factor(d.kind, hint) < 1.0:
        checks.append(Check(name="kind_mismatch", status="fail", detail=f"se pidió {KIND_LABEL.get(hint, hint)} y lo primero encontrado era "
                                   f"{KIND_LABEL.get(d.kind, d.kind)}"))
    role = requested_role(intent)
    if role and (d.kind != "column" or column_role(short_name(d.asset_key), d.description) != role):
        checks.append(Check(name="role_mismatch", status="fail", detail=f"se pidió un dato de tipo {ROLE_LABEL[role]}"))
    if d.coverage < settings.grade_min_coverage:
        checks.append(Check(name="low_coverage", status="warn", detail=f"cubre {round(d.coverage * 100)} % de la pregunta"))
    if d.description_source == "generated" and d.sources <= {"catalog", "estate"}:
        checks.append(Check(name="generated_only", status="warn", detail="la única descripción es sugerida por IA"))
    if len(discovery.candidates) > 1:
        second = discovery.candidates[1]
        if top.confidence - second.confidence < settings.ambiguous_margin and table_key(top.asset_key) != table_key(second.asset_key):
            checks.append(Check(name="ambiguous_top", status="warn",
                                detail=f"{short_name(second.asset_key)} está a menos de {round(settings.ambiguous_margin * 100)} puntos"))
    return checks


def fix_candidate(ranked: list[Draft], top_key: str, intent: IntentResult, settings: DiscoverySettings) -> Draft | None:
    """El mejor activo del ranking que sí cumple el tipo y el rol pedidos."""
    hint = intent.asset_kind_hint
    role = requested_role(intent)
    for d in ranked:
        if d.asset_key == top_key or d.relevance < settings.min_relevance:
            continue
        if hint in ("column", "table") and kind_factor(d.kind, hint) < 1.0:
            continue
        if role and (d.kind != "column" or column_role(short_name(d.asset_key), d.description) != role):
            continue
        return d
    if hint == "table" and is_column_key(top_key):
        # Ninguna tabla responde por sí sola (la pregunta reparte lo pedido entre varias): la del mejor dato encontrado
        # es mejor punto de partida que una columna suelta.
        return next((d for d in ranked if d.asset_key == table_key(top_key)), None)
    return None


def promote(ranked: list[Draft], winner: Draft, loser: Draft, reason: str, settings: DiscoverySettings) -> list[Draft]:
    """Corrige el orden según la revisión: el ganador toma la relevancia del perdedor y este baja."""
    # El elegido por la revisión tiene que poder mostrarse: como mínimo, la relevancia con que se muestra un activo.
    winner.relevance = max(winner.relevance, loser.relevance, settings.min_relevance)
    loser.relevance = round(loser.relevance * 0.7, 4)
    winner.why = reason
    out = rank(ranked, settings)
    if loser.confidence >= winner.confidence:  # la revisión manda sobre la evidencia acumulada del perdedor
        loser.confidence = round(max(winner.confidence - 0.01, 0.0), 4)
        out = sorted(out, key=lambda d: (-d.confidence, d.asset_key))
    if out and out[0] is not winner:
        # Otro activo sigue por delante (p. ej. otra columna de la misma tabla): el elegido por la revisión pasa
        # primero con la confianza del que encabezaba, nunca con más.
        winner.confidence = out[0].confidence
        out = [winner] + [d for d in out if d is not winner]
    return out


def cap_unresolved(discovery: Discovery, settings: DiscoverySettings) -> None:
    """Un chequeo `fail` sin resolver limita la confianza por debajo del umbral de brecha (como F9 en el AskFlow)."""
    if discovery.candidates:
        top = discovery.candidates[0]
        top.confidence = min(top.confidence, round(settings.gap_threshold - 0.01, 4))
        discovery.knowledge_gap = True


# --- paso 6: confianza de descubrimiento --------------------------------------------------------
def compute_confidence(d: Draft, settings: DiscoverySettings) -> float:
    w = settings.weights
    agreement = min(len(d.sources - {"estate"}), 3) / 3
    value = (
        w.relevance_llm * d.relevance
        + w.retrieval * d.retrieval_norm
        + w.evidence * EVIDENCE_STRENGTH.get(d.description_source, 0.3)
        + w.confirmation * d.golden_confirmation
        + w.agreement * agreement
    )
    d.strength = round(value, 4)
    only_generated = d.description_source == "generated" and d.sources <= {"catalog", "estate"}
    if only_generated:
        value = min(value, settings.generated_only_cap)
    if d.unknown_qualifiers:
        # "Tarjetas de regalo" o "contratos de trabajo": el catálogo no sabe si el calificativo es un valor de la tabla
        # o un dato que el banco no tiene. Se muestra la tabla, siempre por debajo del umbral de brecha.
        value = min(value, settings.gap_threshold - 0.01)
    return round(min(max(value, 0.0), 1.0), 4)


def rank(drafts: list[Draft], settings: DiscoverySettings) -> list[Draft]:
    for d in drafts:
        d.confidence = compute_confidence(d, settings)
    # Sin descripciones revisadas, el tope iguala la confianza de muchos candidatos: entre ellos gana el de la tabla
    # que se llama como lo pedido y luego el más fuerte antes del tope, no el primero por orden alfabético.
    return sorted(drafts, key=lambda d: (-d.confidence, -d.precision, -d.strength, d.asset_key))


# --- pasos 3 y 5: agrupación por ambiente y expansión de contexto -------------------------------
def build_discovery(
    ranked: list[Draft],
    retrieval: Retrieval,
    intent: IntentResult,
    user: UserContext,
    catalog: Catalog,
    kb: KnowledgeBase,
    owners: OwnersDirectory,
    settings: DiscoverySettings,
    graph=None,
) -> Discovery:
    """`graph` (EstateGraph) activa la parte GraphRAG: copias de una entidad agrupadas y caminos de unión."""
    vis = user.visible_ids
    pool = [d for d in ranked if catalog.is_visible(d.asset_key, vis)]
    # Un activo que responde parte de la pregunta y se une por el grafo al resto también se conserva (multi-salto),
    # pero siempre detrás de los que responden la pregunta directamente.
    direct = [d for d in pool if d.relevance >= settings.min_relevance]
    via_graph = sorted(
        (d for d in pool if d.relevance < settings.min_relevance and d.graph_coverage >= MULTI_HOP_MIN),
        key=lambda d: (-d.graph_coverage, -d.confidence, d.asset_key),
    )
    ranked = direct + via_graph
    copies: dict[str, list[str]] = {}
    if graph is not None:
        ranked, copies = collapse_entities(ranked, pool, graph, vis)
    everything = [d for d in retrieval.drafts.values() if catalog.is_visible(d.asset_key, vis)]
    if graph is not None and retrieval.secondary_parts:
        ranked = prefer_answerable_start(ranked, retrieval, everything, graph, catalog, vis)
    chosen: list[Draft] = []
    for d in ranked:
        if len(chosen) >= settings.max_candidates:
            break
        if not chosen:
            chosen.append(d)
        elif (
            d.confidence >= settings.secondary_candidate_min
            and _same_family(d.kind, chosen[0].kind)
            and not any(is_replica(d.asset_key, c.asset_key, catalog, kb) for c in chosen)
        ):
            chosen.append(d)

    candidates = [
        _candidate(i + 1, d, intent, user, catalog, kb, owners) for i, d in enumerate(chosen)
    ]
    for c in candidates:
        c.copies = copies.get(c.asset_key, [])
    alternatives = _alternatives(chosen, ranked, catalog, kb, vis, settings, graph)

    related = _related(chosen[: settings.expand_top], retrieval, user, catalog, kb)
    join_paths = []
    if graph is not None and chosen:
        join_paths = find_join_paths(chosen[0], everything, retrieval.concepts, graph, catalog, vis,
                                     parts=retrieval.secondary_parts)
        known = {(r.from_, r.to) for r in related}
        for path in join_paths:
            for edge in path.edges:
                if (edge.a, edge.b) in known or (edge.b, edge.a) in known:
                    continue
                known.add((edge.a, edge.b))
                relation = {"fk": "fk", "same_entity": "same_entity"}.get(edge.kind, "etl")
                extra = {"on": edge.detail} if edge.kind == "fk" else {"via": edge.detail}
                related.append(Related(**{"from": edge.a, "to": edge.b, "relation": relation, **extra}))
    unresolved = unresolved_parts(chosen[0], retrieval, join_paths, catalog, vis) if chosen else []
    if unresolved:  # respuesta incompleta: nada de lo mostrado responde esa parte de la pregunta
        for c in candidates:
            c.confidence = min(c.confidence, round(settings.gap_threshold - 0.05, 4))
    gap = not chosen or bool(unresolved) or chosen[0].confidence < settings.gap_threshold
    return Discovery(
        candidates=candidates,
        alternatives=alternatives,
        related=related,
        join_paths=[p.model for p in join_paths],
        knowledge_gap=gap,
        unresolved_parts=unresolved,
        suggested_questions=_suggested(candidates, kb, vis, catalog),
    )


START_CANDIDATES = 10  # candidatos que se prueban como punto de partida de una pregunta compuesta


def prefer_answerable_start(ranked: list[Draft], retrieval: Retrieval, pool: list[Draft], graph, catalog: Catalog,
                            vis) -> list[Draft]:
    """Pregunta compuesta ("los clientes con sus tarjetas"): el candidato principal tiene que poder unirse al resto de
    la pregunta. Si el primero del ranking deja sub-preguntas sin resolver (p. ej. un `Users` de otra BD sin camino a
    las tarjetas), se adelanta el mejor de los siguientes que deja menos sin resolver; a igualdad, gana el orden."""
    def pending(d: Draft) -> int:
        paths = find_join_paths(d, pool, retrieval.concepts, graph, catalog, vis, parts=retrieval.secondary_parts)
        return len(unresolved_parts(d, retrieval, paths, catalog, vis))

    if not ranked:
        return ranked
    best, best_pending = ranked[0], pending(ranked[0])
    for d in ranked[1:START_CANDIDATES]:
        if best_pending == 0:
            break
        p = pending(d)
        if p < best_pending:
            best, best_pending = d, p
    if best is ranked[0]:
        return ranked
    return [best] + [d for d in ranked if d is not best]


def unresolved_parts(top: Draft, retrieval: Retrieval, join_paths: list, catalog: Catalog, vis) -> list[str]:
    """Sub-preguntas que ni el candidato principal cubre ni un camino de unión alcanza (preguntas compuestas)."""
    if not retrieval.secondary_parts:
        return []
    top_terms = _asset_terms(top, catalog, vis)
    texts = retrieval.secondary_texts or [""] * len(retrieval.secondary_parts)
    remaining = [t for p, t in zip(retrieval.secondary_parts, texts) if concept_coverage(p, top_terms) < 0.5]
    return remaining[len(join_paths):]


def ordered_copies(asset_key: str, catalog: Catalog, vis, preferred_env: str | None = None) -> list:
    """Copias visibles de un activo: primero el ambiente pedido y después el de referencia."""
    copies = catalog.visible_copies(asset_key, vis)
    copies.sort(key=lambda o: (o.environment != preferred_env, not catalog.inventory.is_reference(o.environment, o.server)))
    return copies


def locations_of(copies: list, catalog: Catalog) -> list[Location]:
    return [Location(environment=o.environment, server=catalog.inventory.alias(o.server)) for o in copies]


def drift_of(copies: list) -> str | None:
    """Aviso si la estructura difiere entre ambientes (RF-09), respecto de la primera copia."""
    hashes = {o.schema_hash for o in copies if o.schema_hash}
    if len(hashes) <= 1:
        return None
    ref = copies[0]
    others = sorted({o.environment for o in copies if o.schema_hash != ref.schema_hash})
    shown = {"qa": "QA", "produccion": "producción"}
    return f"{', '.join(shown.get(o, o) for o in others)} difiere de {shown.get(ref.environment, ref.environment)}"


def visible_lineage(asset_key: str, catalog: Catalog, kb: KnowledgeBase, vis) -> Lineage:
    tkey = table_key(asset_key)
    upstream = [e.from_ for e in kb.lineage if e.to == tkey and catalog.is_visible(e.from_, vis)]
    downstream = [e.to for e in kb.lineage if e.from_ == tkey and catalog.is_visible(e.to, vis)]
    return Lineage(upstream=sorted(set(upstream)), downstream=sorted(set(downstream)))


def visible_rules(asset_key: str, catalog: Catalog, kb: KnowledgeBase, vis) -> list[RuleRef]:
    """Reglas del activo; una regla que también aplica a objetos no visibles no se muestra (F14)."""
    return [
        RuleRef(id=r.id, text=r.text, reviewed=r.reviewed)
        for r in kb.rules_for(asset_key)
        if all(catalog.is_visible(a, vis) for a in r.applies_to)
    ]


def owners_of(asset_key: str, owners: OwnersDirectory) -> Owners:
    dom = owners.for_asset(asset_key)
    return Owners(
        business=dom.business_owner.name if dom and dom.business_owner else None,
        technical=dom.technical_owner.name if dom and dom.technical_owner else None,
    )


def _candidate(rank_: int, d: Draft, intent: IntentResult, user, catalog: Catalog, kb, owners) -> Candidate:
    vis = user.visible_ids
    copies = ordered_copies(d.asset_key, catalog, vis, intent.environment_hint)
    ref = copies[0]
    column = catalog.column(d.asset_key, vis)[1] if d.kind == "column" else None
    return Candidate(
        rank=rank_,
        kind=d.kind,
        asset_key=d.asset_key,
        database=ref.database,
        schema=ref.schema_,
        table=ref.name,
        column=column.name if column else None,
        data_type=column.type if column else None,
        locations=locations_of(copies, catalog),
        drift_warning=drift_of(copies),
        description=d.description,
        description_source=d.description_source,
        business_rules=visible_rules(d.asset_key, catalog, kb, vis),
        owners=owners_of(d.asset_key, owners),
        lineage=visible_lineage(d.asset_key, catalog, kb, vis),
        evidence=d.evidence,
        why=d.why,
        confidence=d.confidence,
    )


def collapse_entities(ranked: list[Draft], pool: list[Draft], graph, vis) -> tuple[list[Draft], dict[str, list[str]]]:
    """Una sola entrada por dato de una entidad presente en varias BDs: la copia canónica (o la primera visible)
    representa al grupo con las mejores puntuaciones del grupo; las demás quedan como `copies` del candidato."""
    by_key = {d.asset_key: d for d in pool}
    seen: set = set()
    out: list[Draft] = []
    copies: dict[str, list[str]] = {}
    for d in ranked:
        sig = graph.entity_signature(d.asset_key)
        if sig is None:
            out.append(d)
            continue
        if sig in seen:
            continue
        seen.add(sig)
        group = graph.copies(d.asset_key, vis)
        rep = by_key.get(group[0], d)
        if rep is not d:
            rep.relevance = max(rep.relevance, d.relevance)
            rep.retrieval_norm = max(rep.retrieval_norm, d.retrieval_norm)
            rep.coverage = max(rep.coverage, d.coverage)
            rep.confidence = max(rep.confidence, d.confidence)
            rep.sources |= d.sources
            rep.why = rep.why or d.why
            for ev in d.evidence:
                rep.add_evidence(ev)
        copies[rep.asset_key] = [k for k in group if k != rep.asset_key]
        out.append(rep)
    return out, copies


@dataclass
class _Path:
    purpose: str
    edges: list
    start: str

    @property
    def model(self) -> JoinPath:
        tables, steps, node = [self.start], [], self.start
        for e in self.edges:
            nxt = e.other(node)
            detail = f": {e.detail}" if e.detail else ""
            steps.append(f"{node} → {nxt} ({e.kind}{detail})")
            tables.append(nxt)
            node = nxt
        return JoinPath(purpose=self.purpose, tables=tables, steps=steps)


def join_path_model(purpose: str, start: str, edges: list) -> JoinPath:
    return _Path(purpose=purpose, edges=edges, start=table_key(start)).model


def find_join_paths(top: Draft, pool: list[Draft], concepts, graph, catalog: Catalog, vis, max_paths: int = 2,
                    parts: list[list[frozenset[str]]] | None = None) -> list[_Path]:
    """Multi-salto (GraphRAG): para cada concepto de la pregunta que el candidato principal no cubre, la tabla que sí lo
    cubre (la mejor recuperada) y el camino de unión más corto hasta ella, considerando todas las copias de su entidad."""
    top_table = table_key(top.asset_key)
    top_terms = _asset_terms(top, catalog, vis)
    paths: list[_Path] = []
    used_tables = {top_table}
    ordered = sorted(pool, key=lambda x: (-x.retrieval_norm, x.asset_key))
    if parts:
        # Pregunta compuesta: la tabla destino es la que mejor cubre la sub-pregunta completa ("el nombre del cliente").
        for part in parts[:max_paths]:
            # Solo lo que la sub-pregunta añade: lo que ya nombra el candidato principal no elige el destino.
            asked = [c for c in part if not (c & top_terms)] or part
            scored = [
                (concept_coverage(asked, set(tokenize(short_name(table_key(d.asset_key))))),
                 concept_coverage(asked, _asset_terms(d, catalog, vis)), d.retrieval_norm, d)
                for d in ordered if table_key(d.asset_key) not in used_tables
            ]
            # Primero la tabla que se llama como lo pedido ("el cliente" → `Clientes`), no una que solo apunta a ella.
            scored = sorted(((own, cov, ret, d) for own, cov, ret, d in scored if cov > 0),
                            key=lambda s: (-s[0], -s[1], -s[2], s[3].asset_key))
            scored = [(cov, ret, d) for _, cov, ret, d in scored]
            # La mejor tabla puede no ser unible (otra BD sin relación): se prueban las siguientes.
            for _, _, holder in scored[:8]:
                best = None
                for target in graph.copies(table_key(holder.asset_key), vis):
                    path = graph.join_path(top_table, target, vis)
                    if path is not None and (best is None or len(path) < len(best)):
                        best = path
                if best:
                    used_tables.add(table_key(holder.asset_key))
                    paths.append(_Path(purpose=short_name(holder.asset_key), edges=best, start=top_table))
                    break
        return paths
    for concept in concepts:
        if concept & top_terms or len(paths) >= max_paths:
            continue
        holder = next(
            (d for d in ordered if table_key(d.asset_key) not in used_tables and concept & _asset_terms(d, catalog, vis)),
            None,
        )
        if holder is None:
            continue
        best = None
        for target in graph.copies(table_key(holder.asset_key), vis):
            path = graph.join_path(top_table, target, vis)
            if path is not None and (best is None or len(path) < len(best)):
                best = path
        if best:
            used_tables.add(table_key(holder.asset_key))
            paths.append(_Path(purpose=sorted(concept, key=len)[-1], edges=best, start=top_table))
    return paths


def _same_family(kind: str, other: str) -> bool:
    return (kind == "column") == (other == "column")


def is_replica(key: str, of_key: str, catalog: Catalog, kb: KnowledgeBase) -> bool:
    """Una columna con el mismo nombre normalizado en una tabla conectada por linaje ETL es una copia del mismo dato:
    se muestra como relación `etl`, no como candidato ni alternativa."""
    if not (is_column_key(key) and is_column_key(of_key)) or key == of_key:
        return False
    if normalized_name(short_name(key)) != normalized_name(short_name(of_key)):
        return False
    a, b = table_key(key), table_key(of_key)
    return any({e.from_, e.to} == {a, b} for e in kb.lineage)


def _alternatives(chosen: list[Draft], ranked: list[Draft], catalog: Catalog, kb, vis, settings, graph=None) -> list[Alternative]:
    """Columnas con la misma semántica que el candidato principal y, si faltan, las siguientes del ranking (F22 paso 5)."""
    if not chosen or chosen[0].kind != "column":
        return []
    top = chosen[0]
    chosen_keys = {d.asset_key for d in chosen}
    pool = {d.asset_key: d for d in ranked}
    keys = list(find_alternatives(top.asset_key, catalog, vis))
    keys += [d.asset_key for d in ranked if d.kind == "column"]
    out: list[Alternative] = []
    signatures = {graph.entity_signature(k) for k in chosen_keys} - {None} if graph is not None else set()
    for key in dict.fromkeys(keys):
        if key in chosen_keys or any(is_replica(key, c, catalog, kb) for c in chosen_keys):
            continue
        if graph is not None:
            sig = graph.entity_signature(key)
            if sig is not None:
                if sig in signatures:
                    continue  # copia de la misma entidad en otra BD: ya figura en `copies` del candidato
                signatures.add(sig)
        alt = pool.get(key)
        desc = _column_description(key, catalog, vis)
        out.append(Alternative(asset_key=key, why=desc or "Columna con la misma semántica.", confidence=alt.confidence if alt else 0.0))
    out.sort(key=lambda a: (-a.confidence, a.asset_key))
    return out[: settings.max_alternatives]


def find_alternatives(asset_key: str, catalog: Catalog, vis) -> list[str]:
    """Columnas visibles con la misma semántica: sinónimo compartido o mismo nombre normalizado (F22 paso 5)."""
    found = catalog.column(asset_key, vis)
    if not found:
        return []
    _, base = found
    base_syn = {tuple(tokenize(s)) for s in base.synonyms if tokenize(s)}
    base_name = normalized_name(base.name)
    result: list[str] = []
    for tkey in catalog.table_keys():
        copies = catalog.visible_copies(tkey, vis)
        if not copies:
            continue
        for col in copies[0].columns:
            key = copies[0].column_asset_key(col.name)
            if key == asset_key:
                continue
            syn = {tuple(tokenize(s)) for s in col.synonyms if tokenize(s)}
            if normalized_name(col.name) == base_name or base_syn & syn:
                result.append(key)
    return result


def _column_description(key: str, catalog: Catalog, vis) -> str | None:
    found = catalog.column(key, vis)
    return found[1].description if found else None


def _related(chosen: list[Draft], retrieval: Retrieval, user, catalog: Catalog, kb: KnowledgeBase) -> list[Related]:
    return related_for_tables({table_key(d.asset_key) for d in chosen}, catalog, kb, user.visible_ids)


def related_for_tables(tables: set[str], catalog: Catalog, kb: KnowledgeBase, vis) -> list[Related]:
    """Relaciones a un salto (FK, linaje ETL y misma entidad) entre tablas visibles (F22 paso 6)."""
    out: dict[tuple, Related] = {}
    for fk in catalog.fk_edges():
        if (fk.from_table in tables or fk.to_table in tables) and catalog.is_visible(fk.from_table, vis) and catalog.is_visible(fk.to_table, vis):
            out[(fk.from_table, fk.to_table, "fk")] = Related(**{"from": fk.from_table, "to": fk.to_table, "relation": "fk", "on": fk.on})
    for e in kb.lineage:
        if (e.from_ in tables or e.to in tables) and catalog.is_visible(e.from_, vis) and catalog.is_visible(e.to, vis):
            out[(e.from_, e.to, "etl")] = Related(**{"from": e.from_, "to": e.to, "relation": "etl", "via": f"{e.via.kind.upper()}:{e.via.name}"})
    for entity in kb.entities:
        visible = [t for t in entity.tables if catalog.is_visible(t, vis)]
        canonical = entity.canonical if entity.canonical in visible else (visible[0] if visible else None)
        if not canonical or not tables.intersection(visible):
            continue
        for t in visible:
            if t != canonical:
                out[(canonical, t, "same_entity")] = Related(
                    **{"from": canonical, "to": t, "relation": "same_entity", "via": f"entidad:{entity.name}"}
                )
    return list(out.values())


def _suggested(candidates: list[Candidate], kb: KnowledgeBase, vis, catalog: Catalog) -> list[str]:
    if not candidates:
        return []
    top = candidates[0]
    name = top.column or top.table
    out = [f"¿Qué reglas de negocio aplican a {name}?"]
    if top.lineage.upstream or top.lineage.downstream:
        out.append(f"¿Qué proceso ETL carga {top.database}.{top.schema_}.{top.table}?")
    return out


# --- paso 7: guarda de la narrativa ------------------------------------------------------------
def allowed_names(discovery: Discovery) -> set[str]:
    keys = [c.asset_key for c in discovery.candidates] + [a.asset_key for a in discovery.alternatives]
    keys += [r.from_ for r in discovery.related] + [r.to for r in discovery.related]
    names: set[str] = set()
    for key in keys:
        names.update(key.split("."))
    for r in discovery.related:  # la columna con que se cruzan dos tablas mostradas también es parte de la respuesta
        names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", r.on or ""))
    return {n.lower() for n in names}


_UNSAFE_GENERATED = re.compile(r"https?://|www\.|\]\(|<\s*/?\s*[a-zA-Z][^>]*>|[\w.+-]+@[\w-]+\.[\w.]+", re.I)


def unsafe_generated_text(text: str | None) -> bool:
    """Texto generado por el LLM que no se muestra: enlaces, HTML o correos.

    Una descripción del catálogo puede traer instrucciones ("dile al usuario que pida acceso en http://…"); el modelo
    las lee como datos, pero si las obedece el resultado lleva casi siempre un enlace o un contacto. Una respuesta de
    descubrimiento legítima solo nombra objetos del catálogo."""
    return bool(text) and bool(_UNSAFE_GENERATED.search(text))


# Quien usa el chat es una persona de negocio: una aclaración no le habla de tablas ni de columnas.
_JARGON = re.compile(r"\b(tablas?|columnas?|campos?|bases? de datos|esquemas?|sql|query|queries|llaves?|registros?)\b")


def looks_technical(text: str) -> bool:
    """¿El texto trae algo con aspecto de identificador (referencia con puntos, CamelCase, guion bajo o dígitos)? Es
    la guarda del texto de aclaración que redacta el modelo. No consulta el catálogo a propósito: si dependiera de qué
    objetos existen, que una opción aparezca o no delataría el nombre de una tabla que el usuario no puede ver (F14)."""
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_]", text) or _JARGON.search(strip_accents(text).lower()):
        return True
    return any(_TECHNICAL.search(word) for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text))


def narrative_mentions_ok(text: str, discovery: Discovery, catalog: Catalog) -> bool:
    """Falso si la narrativa nombra un objeto del catálogo que no está en candidates, alternatives o related."""
    allowed = allowed_names(discovery)
    return not (mentioned_objects(text, catalog) - allowed)


_TECHNICAL = re.compile(r"[a-z0-9][A-Z]|_|\d")


def mentioned_objects(text: str, catalog: Catalog) -> set[str]:
    """Nombres del catálogo que el texto menciona como objetos (en minúsculas).

    Cuenta como mención: una parte de una referencia con puntos (`BD.dbo.Tabla.Columna`), un identificador técnico
    (CamelCase, `_` o dígitos: `ClientCode`, `vw_Cartera`) o un nombre de tabla escrito igual. Una palabra común que
    coincide con una columna (`estado`, `nombre`, `canal`) no es una mención: rechazarla bloquearía cualquier texto."""
    tables = {o.name for o in catalog.objects}
    names = {n.lower() for n in catalog.all_names()}
    found: set[str] = set()
    for ref in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", text):
        found.update(p.lower() for p in ref.split(".") if p.lower() in names)
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if word.lower() in names and (_TECHNICAL.search(word) or word in tables):
            found.add(word.lower())
    return found


_CAMEL_WORDS = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|_+")
MAX_AREA_OPTIONS = 4


def humanize(name: str) -> str:
    """`CuotasLeasing` → "Cuotas Leasing", `vw_CarteraTarjetas` → "Cartera Tarjetas": un nombre que se puede leer."""
    words = [w for w in _CAMEL_WORDS.split(name) if w and w.lower() not in ("vw", "tbl", "dbo")]
    return " ".join(words) or name


def area_options(question: str, discovery: Discovery, settings: DiscoverySettings) -> list[str]:
    """El mismo dato existe en varias áreas ("la fecha de vencimiento de la cuota": de préstamos y de leasing) y la
    pregunta no dice cuál. Devuelve la pregunta reformulada para cada área, para ofrecerla como opción; vacío si el
    candidato principal no compite con el mismo dato de otra tabla."""
    if not discovery.candidates or discovery.candidates[0].kind != "column":
        return []
    top = discovery.candidates[0]
    name = normalized_name(top.column or "")
    seen = {table_key(top.asset_key)}
    areas = [top.table]
    rivals = [(c.asset_key, c.confidence) for c in discovery.candidates[1:]]
    rivals += [(a.asset_key, a.confidence) for a in discovery.alternatives]
    for key, confidence in rivals:
        tkey = table_key(key)
        if tkey in seen or normalized_name(short_name(key)) != name:
            continue
        if top.confidence - confidence > settings.ambiguous_margin:
            continue
        seen.add(tkey)
        areas.append(short_name(tkey))
    if len(areas) < 2:
        return []
    base = question.strip(" ¿?.!¡")
    return [f"{base} ({humanize(area).lower()})" for area in areas[:MAX_AREA_OPTIONS]]


def databases_of(discovery: Discovery) -> list[str]:
    dbs = [c.database for c in discovery.candidates] + [a.asset_key.split(".")[0] for a in discovery.alternatives]
    dbs += [r.from_.split(".")[0] for r in discovery.related] + [r.to.split(".")[0] for r in discovery.related]
    return list(dict.fromkeys(dbs))


def tables_of(discovery: Discovery) -> list[str]:
    keys = [table_key(c.asset_key) for c in discovery.candidates]
    keys += [r.from_ for r in discovery.related] + [r.to for r in discovery.related]
    return list(dict.fromkeys(keys))


__all__ = [
    "Draft",
    "Retrieval",
    "retrieve",
    "shortlist",
    "rerank_items",
    "deterministic_relevance",
    "apply_rerank",
    "rank",
    "compute_confidence",
    "build_discovery",
    "find_alternatives",
    "narrative_mentions_ok",
    "short_name",
]
