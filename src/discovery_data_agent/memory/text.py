"""Normalización léxica determinista para la parte BM25 de la búsqueda híbrida (español + nombres técnicos)."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset(
    """
    a al algo algun alguna algunas alguno algunos ante como con cual cuales cuando de del desde donde dos el ella
    ellos en entre era es esa ese eso esta estan este esto fue ha hay la las le lo los mas me mi mis muy necesito
    ni no nos o otra otro para pero por que quien se segun ser si sin sobre son su sus tambien te tiene un una uno
    unos y ya encontrar buscar quiero dime donde esta estan utilizado utilizada usado usada usa usan the of and
    dato datos campo campos tabla tablas tenemos existen necesitamos proceso procesos informacion
    cuanto cuanta cuantos cuantas mes pasado ultimo ultimos ultima significa
    """.split()
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[A-Za-z0-9]+")
STEM_LEN = 6


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def stem(word: str) -> str:
    """Stemmer de prefijo: plural → singular y truncado a 6 caracteres (identificador ≈ identifica)."""
    if len(word) > 4 and word.endswith("es"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s"):
        word = word[:-1]
    return word[:STEM_LEN]


# Marcadores que deja la redacción de PII (F23): `<DUI>`, `<CUENTA_BANCARIA>`. Indican que hubo un dato, no de qué
# trata el texto, así que no se indexan (si no, "¿dónde está el DUI?" encontraría cualquier documento redactado).
_REDACTION = re.compile(r"<[A-Z][A-Z0-9_]*>")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD.findall(strip_accents(_REDACTION.sub(" ", text or ""))):
        for part in _CAMEL.split(raw):
            word = part.lower()
            if len(word) < 2 or word in STOPWORDS:
                continue
            tokens.append(stem(word))
    return tokens


# --- literales de una pregunta ---------------------------------------------------------------------------
# Un literal es un valor concreto que alguien escribe al preguntar: un documento, una cuenta, una fecha, un monto, un
# correo, un código de cliente. No describe qué dato se busca, así que ni cuenta para medir si un activo responde la
# pregunta ni se guarda en la plantilla de una confirmación (F17, clase D4).
#
# La regla es deliberadamente estricta: toda palabra con algún dígito o con una arroba es un literal, salvo que sea
# vocabulario conocido del banco (el nombre de un objeto del catálogo como `Ultimos4`, o un código del glosario como
# `NCB-022`). Las listas de formatos concretos (DUI, cuenta, IBAN) siempre se dejan alguno; "tiene un dígito" no.
_EDGE = "¿?¡!.,;:()[]{}\"'«»“”‘’<>"
# "juan.perez @ banco.com". Solo se intenta al inicio de cada palabra: sin eso, una palabra de miles de caracteres se
# recorre una vez por cada carácter (segundos con 20 000) y el resultado es el mismo.
_SPACED_AT = re.compile(r"(?<!\S)\S+\s+@\s+\S+")


def _is_literal(word: str, known) -> bool:
    core = strip_accents(word).lower()
    if "@" in core:
        return True
    if not any(ch.isdigit() for ch in core):
        return False
    if core in known:
        return False
    # Una referencia con puntos (`BD.esquema.Tabla2`) vale si cada parte con dígitos es un nombre conocido.
    parts = [part for part in core.split(".") if part]
    return not (len(parts) > 1 and all(part in known for part in parts if any(ch.isdigit() for ch in part)))


def strip_literals(question: str, known=frozenset()) -> str:
    """La pregunta sin sus literales. `known`: palabras con dígitos que son vocabulario y no valores (en minúsculas y
    sin tildes). Normaliza antes con NFKC: los dígitos en superíndice, de ancho completo o en círculo son dígitos."""
    text = _SPACED_AT.sub(" ", unicodedata.normalize("NFKC", question))
    return " ".join(word for word in text.split() if not _is_literal(word.strip(_EDGE), known))


def has_literals(question: str, known=frozenset()) -> bool:
    """¿La pregunta trae algo que la plantilla descarta? Entonces su texto original no se guarda fuera de la auditoría."""
    return strip_literals(question, known) != " ".join(unicodedata.normalize("NFKC", question).split())


def normalized_name(name: str) -> str:
    """`Client_Code` / `ClientCode` / `clientcode` → `clientcode` (para alternativas por nombre)."""
    return re.sub(r"[^a-z0-9]", "", strip_accents(name).lower())
