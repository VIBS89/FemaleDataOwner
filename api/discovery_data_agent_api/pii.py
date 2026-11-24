"""Detector de datos personales en los textos de curación (OP-06 CA5).

Las descripciones, reglas y diccionarios que escribe un responsable se indexan, los ven todos los usuarios con acceso al
activo y viajan al proveedor de LLM dentro de los prompts. Deben describir el dato, no traer ejemplos reales.
Es una lista corta de patrones de El Salvador y genéricos; se amplía con el equipo de Seguridad del banco.
"""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern] = {
    "DUI": re.compile(r"(?<!\d)\d{8}-\d(?!\d)"),
    "NIT": re.compile(r"(?<!\d)\d{4}-\d{6}-\d{3}-\d(?!\d)"),
    "correo": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "teléfono": re.compile(r"(?<![\d-])(?:\+?503[ -]?)?[267]\d{3}[ -]\d{4}(?![\d-])"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
}
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def find_pii(text: str) -> list[str]:
    """Tipos de dato personal que el texto parece contener (vacío si ninguno)."""
    found = [kind for kind, pattern in _PATTERNS.items() if pattern.search(text)]
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("tarjeta")
            break
    return found
