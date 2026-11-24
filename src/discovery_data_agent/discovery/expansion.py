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

from discovery_data_agent.memory.text import strip_accents, strip_literals, tokenize

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
    # Cómo habla el negocio en un chat y cómo suelen llamarse las tablas (genérico de banca, no de un esquema).
    "credito": ["prestamo", "loan"],
    "financiamiento": ["prestamo", "loan"],
    "cobranza": ["cobro", "gestion", "collection"],
    "cobro": ["cobranza", "gestion", "collection"],
    "recuperacion": ["cobro", "pago"],
    "ahorro": ["deposito", "savings"],
    "debito": ["deposito", "debit"],
    "titular": ["cliente", "customer", "holder"],
    "dueno": ["cliente", "customer", "owner"],
    "tarjetahabiente": ["cliente", "customer", "cardholder"],
    "deudor": ["cliente", "customer"],
    "dinero": ["saldo", "monto", "balance"],
    "plata": ["saldo", "monto", "balance"],
    "deuda": ["saldo", "balance"],
    "consumo": ["transaccion", "compra", "purchase"],
    "compra": ["transaccion", "purchase"],
    "atraso": ["mora", "delinquency"],
    "atrasado": ["mora", "delinquency"],
    "atrasada": ["mora", "delinquency"],
    "moroso": ["mora", "delinquency"],
    "vencido": ["mora", "vencimiento"],
    "vencida": ["mora", "vencimiento"],
    "asesor": ["ejecutivo"],
    "gestor": ["ejecutivo", "gestion"],
    "oficina": ["agencia", "branch"],
    "apertura": ["alta", "opened"],
    "abierta": ["apertura", "opened"],
    "abierto": ["apertura", "opened"],
    # Un adjetivo de situación ("activos", "vigentes", "cancelada") es un valor de la columna de estado.
    "activo": ["estado", "status"],
    "activa": ["estado", "status"],
    "vigente": ["estado", "status"],
    "cancelado": ["estado", "status"],
    "cancelada": ["estado", "status"],
    "bloqueada": ["estado", "status", "bloqueo"],
    "bloqueado": ["estado", "status", "bloqueo"],
    "rechazada": ["estado", "status", "rechazo"],
    "rechazado": ["estado", "status", "rechazo"],
    "aprobada": ["estado", "status"],
    "aprobado": ["estado", "status"],
}

# Palabras que dicen qué tipo de respuesta se busca, no qué contiene el activo.
META_TERMS = {"regla", "reglas", "aplica", "aplican", "indicador", "indicadores", "metrica", "guarda", "guardamos",
              "almacena", "ubica", "ubicado", "contiene", "llena", "alimenta", "proceso", "carga",
              "relaciono", "relaciona", "relacionar", "cruzo", "cruza", "cruzar", "unir", "uno", "junto", "como",
              "conecta", "conectan", "conecto", "conectar", "une", "unen",
              "calcula", "calculan", "calcular", "calculo", "define", "definen", "significado"}

# Palabras con que se arma una pregunta en un chat ("necesito saber", "dónde puedo ver", "cuál es cuál") y que ningún
# activo tiene por qué nombrar. Sin esto, cada una cuenta como una parte de la pregunta sin cubrir y una pregunta larga
# se queda sin candidatos aunque nombre bien el dato.
QUESTION_FILLER = frozenset("""
    saber conocer ver veo vemos mirar revisar consultar consulto consulta puedo puede puedes podemos podria podrias
    dame deme danos muestrame mostrar muestra ensename indica indicame dice dicen decir quiere quieren
    tienen tengan tener hubo habia queda quedan quedo corresponde corresponden refiere refieren entiendo entender
    exactamente cada todos todas mismo misma mismos mismas ademas ahora entonces pero aqui alla favor porfa gracias
    columna columnas base bases sistema sistemas distintas distintos diferentes real reales
    disponible disponibles sacar saco obtener obtengo listar lista listado detalle
    hola buenas buenos tardes noches ok okay perfecto genial listo vale excelente entendido
""".split())

# Palabras que dicen qué cálculo o qué periodo se pide en una pregunta de cifras ("el total", "el promedio", "top 10",
# "por mes", "este año"). Describen la operación, no el dato: solo se descartan cuando la pregunta es de cifras, porque
# en otra pueden ser parte del nombre del dato ("monto total del pago").
ANALYSIS_TERMS = frozenset("""
    total totales suma sumatoria promedio media conteo cantidad top mayor mayores menor menores mejores peores
    grande grandes pequeno pequenos primeros ultimas maximo minimo ranking separado separados agrupado agrupados
    ano anos anual mensual meses semana semanas trimestre trimestres semestre hoy ayer actual actualmente cierre
    este esta estos estas reciente recientes historico
""".split())

def _translations(word: str) -> list[str]:
    """Traducciones de una palabra cruda (sin tildes, minúsculas), también en plural."""
    for cand in (word, word[:-2] if word.endswith("es") else None, word[:-1] if word.endswith("s") else None):
        if cand and cand in LEXICON:
            return LEXICON[cand]
    return []


def _words(text: str, known=frozenset(), ignore=frozenset()) -> list[str]:
    """Palabras con contenido de la pregunta. Sin sus literales: "el DUI del cliente 01234567-8" pregunta por el DUI
    del cliente; el número no es algo que un activo del catálogo deba nombrar. `known`: nombres del catálogo con
    dígitos que el usuario ve (`Ultimos4`), que sí son parte de lo que se pregunta. `ignore`: palabras que en esta
    pregunta no nombran un dato (los términos de cálculo de una pregunta de cifras)."""
    return [w for w in re.findall(r"[a-z0-9]+", strip_accents(strip_literals(text, known)).lower())
            if w not in META_TERMS and w not in QUESTION_FILLER and w not in ignore]


def content_words(text: str, known=frozenset()) -> list[str]:
    """Las palabras con contenido tal como se escribieron (sin tildes, en minúsculas), sin traducir ni expandir."""
    return [w for w in _words(text, known) if tokenize(w)]


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


# "El tipo de activo arrendado", "los activos del contrato": tras un artículo o una preposición, "activo" es el bien
# (un sustantivo), no el adjetivo de situación que equivale a la columna de estado.
_NOUN_ACTIVO = re.compile(r"\b(?:el|del|de|los|un|al|cada|tipo de|cuantos|que)\s+activos?\b")


def concepts_of(text: str, expand: bool, known=frozenset(), ignore=frozenset()) -> list[frozenset[str]]:
    """Un concepto por palabra con contenido: su stem más (si `expand`) los stems de sus traducciones."""
    if not expand:
        return [frozenset({t}) for t in dict.fromkeys(tokenize(strip_literals(text, known)))]
    out: dict[frozenset[str], None] = {}
    noun_activo = bool(_NOUN_ACTIVO.search(strip_accents(text).lower()))
    for word in _words(text, known, ignore):
        translations = [] if noun_activo and word in ("activo", "activos") else _translations(word)
        stems = set(tokenize(word)) | {s for en in translations for s in tokenize(en)}
        if stems:
            out[frozenset(stems)] = None
    return list(out)


def plan_query(question: str, business_context: str | None, expand: bool, variant_weight: float,
               known=frozenset(), ignore=frozenset()) -> QueryPlan:
    """`ignore`: palabras que no cuentan como parte de lo pedido (`ANALYSIS_TERMS` en una pregunta de cifras)."""
    base = " ".join(filter(None, [question, business_context]))
    plan = QueryPlan(queries=[(base, 1.0)], concepts=concepts_of(base, expand, known, ignore))
    parts = decompose(question)
    if len(parts) > 1:
        plan.primary_concepts = concepts_of(parts[0], expand, known, ignore)
        plan.secondary_parts = [concepts_of(p, expand, known, ignore) for p in parts[1:]]
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
