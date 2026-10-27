"""Patrón D — reescritura y expansión de la consulta (multi-query).

Determinista: los sistemas del banco mezclan nombres en español e inglés (`ClientCode`, `CreatedAt`, `CustomerConsents`)
y muchas columnas no tienen descripción. Un léxico técnico es→en convierte los términos de negocio de la pregunta en los
nombres que suelen tener las columnas. Con LLM (rol `fast`), el `QueryExpander` propone variantes adicionales cuando la
recuperación es pobre (patrón C).

También separa el **foco** de la pregunta: las palabras que describen qué se busca ("reglas", "aplican", "tabla")
no son términos que el activo deba contener.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from converdata.memory.text import strip_accents, tokenize

# Términos de negocio en español → nombres técnicos habituales en inglés. Genérico de datos, no del fixture.
LEXICON: dict[str, list[str]] = {
    "cliente": ["client", "customer"],
    "usuario": ["user"],
    "fecha": ["date"],
    "alta": ["created", "registered", "signup"],
    "registro": ["created", "registered"],
    "registraron": ["created", "registered"],
    "creacion": ["created"],
    "ingreso": ["login", "signin"],
    "sesion": ["session", "login"],
    "ultimo": ["last"],
    "ultima": ["last"],
    "consentimiento": ["consent"],
    "aceptado": ["accepted"],
    "aceptados": ["accepted"],
    "acepto": ["accepted"],
    "firmo": ["signed", "accepted"],
    "tipo": ["type"],
    "estado": ["status", "state"],
    "codigo": ["code"],
    "identificador": ["id"],
    "dispositivo": ["device"],
    "solicitud": ["request", "application"],
    "documento": ["document"],
    "correo": ["email", "mail"],
    "telefono": ["phone"],
    "monto": ["amount"],
    "saldo": ["balance"],
    "cuenta": ["account"],
    "tarjeta": ["card"],
    "prestamo": ["loan"],
    "pago": ["payment"],
    "transaccion": ["transaction"],
    "nombre": ["name"],
    "direccion": ["address"],
    "segmento": ["segment"],
    "llave": ["key"],
    # Glosario bancario: sinónimos en español y nombres técnicos habituales en los esquemas.
    "billetera": ["wallet"],
    "monedero": ["wallet"],
    "huella": ["fingerprint"],
    "sueldo": ["ingreso", "salario", "income"],
    "salario": ["ingreso", "sueldo", "income"],
    "expiracion": ["vencimiento", "expiry", "expiration"],
    "caducidad": ["vencimiento", "expiry"],
    "vencimiento": ["expiry", "due"],
    "arrendamiento": ["leasing", "lease"],
    "interes": ["tasa", "rate", "interest"],
    "tasa": ["rate"],
    "tokenizacion": ["token"],
    "tokenizada": ["token"],
    "comercio": ["merchant"],
    "sucursal": ["agencia", "branch"],
    "agencia": ["branch"],
    "cajero": ["atm"],
    "cuota": ["installment"],
    "garantia": ["collateral"],
    "mora": ["delinquency", "atraso"],
    "deposito": ["deposit"],
    "bloqueo": ["block"],
}

# Palabras que dicen qué tipo de respuesta se busca, no qué contiene el activo.
META_TERMS = {"regla", "reglas", "aplica", "aplican", "indicador", "indicadores", "metrica", "guarda", "guardamos",
              "almacena", "ubica", "ubicado", "contiene", "llena", "alimenta", "proceso", "carga",
              "relaciono", "relaciona", "relacionar", "cruzo", "cruza", "cruzar", "unir", "uno", "junto", "como"}

def _translations(word: str) -> list[str]:
    """Traducciones de una palabra cruda (sin tildes, minúsculas), también en plural."""
    for cand in (word, word[:-2] if word.endswith("es") else None, word[:-1] if word.endswith("s") else None):
        if cand and cand in LEXICON:
            return LEXICON[cand]
    return []


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", strip_accents(text).lower()) if w not in META_TERMS]


# Conjunción que separa dos datos pedidos: "… de las cuotas y el DUI del cliente", "… del token con el dispositivo".
_SPLIT = re.compile(r"\s+(?:y|con|junto con|ademas de)\s+(?=(?:el|la|los|las|su|sus)\b)", re.I)


def decompose(text: str) -> list[str]:
    """Descomposición en sub-preguntas (multi-salto): la primera parte decide el candidato principal y las demás se
    resuelven con caminos de unión del grafo. Sin conjunción explícita, una sola parte."""
    parts = [p.strip(" ¿?.,;") for p in _SPLIT.split(strip_accents(text).lower()) if p and p.strip(" ¿?.,;")]
    return parts if len(parts) > 1 and all(_words(p) for p in parts) else [text]


@dataclass
class QueryPlan:
    """Consultas a ejecutar (texto, peso) y conceptos de la pregunta para medir la cobertura."""

    queries: list[tuple[str, float]]
    concepts: list[frozenset[str]] = field(default_factory=list)  # cada concepto: stem original ∪ traducciones
    primary_concepts: list[frozenset[str]] | None = None  # conceptos de la primera sub-pregunta, si se descompuso
    secondary_parts: list[list[frozenset[str]]] = field(default_factory=list)  # conceptos de cada sub-pregunta siguiente
    secondary_texts: list[str] = field(default_factory=list)  # texto de cada sub-pregunta siguiente (para explicarlas)

    def add_variants(self, variants: list[str], weight: float) -> list[str]:
        known = {q for q, _ in self.queries}
        new = [v for v in variants if v and v not in known]
        self.queries.extend((v, weight) for v in new)
        return new


def concepts_of(text: str, expand: bool) -> list[frozenset[str]]:
    """Un concepto por palabra con contenido: su stem más (si `expand`) los stems de sus traducciones."""
    if not expand:
        return [frozenset({t}) for t in dict.fromkeys(tokenize(text))]
    out: dict[frozenset[str], None] = {}
    for word in _words(text):
        stems = set(tokenize(word)) | {s for en in _translations(word) for s in tokenize(en)}
        if stems:
            out[frozenset(stems)] = None
    return list(out)


def plan_query(question: str, business_context: str | None, expand: bool, variant_weight: float) -> QueryPlan:
    base = " ".join(filter(None, [question, business_context]))
    plan = QueryPlan(queries=[(base, 1.0)], concepts=concepts_of(base, expand))
    parts = decompose(question)
    if len(parts) > 1:
        plan.primary_concepts = concepts_of(parts[0], expand)
        plan.secondary_parts = [concepts_of(p, expand) for p in parts[1:]]
        plan.secondary_texts = list(parts[1:])
    if expand:
        translated = lexicon_variant(base)
        if translated:
            plan.add_variants([translated], variant_weight)
    return plan


def lexicon_variant(text: str) -> str | None:
    """Variante con los términos técnicos en inglés; None si ningún término tiene traducción."""
    extra = [en for w in _words(text) for en in _translations(w)]
    return " ".join(dict.fromkeys(extra)) or None
