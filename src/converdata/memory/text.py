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


def normalized_name(name: str) -> str:
    """`Client_Code` / `ClientCode` / `clientcode` → `clientcode` (para alternativas por nombre)."""
    return re.sub(r"[^a-z0-9]", "", strip_accents(name).lower())
