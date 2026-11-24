"""Arma la presentación del hackathon a partir de sus fuentes en docs/pitch/project/:

- docs/pitch/presentacion.html: se abre en cualquier navegador, sin servidor: flechas para avanzar, N para las notas,
  F para pantalla completa e Imprimir para guardarlo en PDF.
- docs/wiki/hackathon-pitch.md: la misma presentación como página de la wiki, con el texto de cada diapositiva y sus
  notas del orador; la aplicación la muestra en Administración → Documentación. Omite lo marcado con la clase
  `equipo` (nombres de personas, que la wiki no lleva).

Uso: .venv/Scripts/python scripts/build_pitch.py

Las fuentes son las del artifact de Slides en claude.ai: `deck.json` (orden y tipografías), `deck.css` (estilos
compartidos) y una `slides/<id>.html` por diapositiva.
"""

from __future__ import annotations

import json
import re
import unicodedata
from html import escape
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "docs" / "pitch"
SRC = ROOT / "project"
OUT = ROOT / "presentacion.html"
WIKI_OUT = REPO / "docs" / "wiki" / "hackathon-pitch.md"
BLOCKS = {"h1", "h2", "h3", "p", "li", "td", "th"}

VIEWER_CSS = """
html, body { margin: 0; height: 100%; background: #0E0F13; overflow: hidden; }
#stage { position: absolute; left: 50%; top: 50%; width: 1920px; height: 1080px; transform-origin: center; }
#stage > section { position: absolute; inset: 0; box-sizing: border-box; overflow: hidden; display: none; }
#stage > section.on { display: flex; }
section aside { display: none; }
x-shape { display: block; }
x-shape[kind="arrow-right"] { clip-path: polygon(0 30%, 60% 30%, 60% 0, 100% 50%, 60% 100%, 60% 70%, 0 70%); }
#notes { position: fixed; left: 0; right: 0; bottom: 0; max-height: 38vh; overflow: auto; display: none;
  background: #1B1C22; color: #F4F4F7; font: 16px/1.5 'Nunito Sans', Arial, sans-serif; padding: 16px 24px;
  white-space: pre-wrap; border-top: 3px solid #D9272E; }
#notes.on { display: block; }
#hud { position: fixed; right: 16px; bottom: 12px; color: #8A8F9C; font: 14px Arial, sans-serif; }
@media print {
  @page { size: 1920px 1080px; margin: 0; }
  html, body { overflow: visible; height: auto; background: none; }
  #stage { position: static; transform: none !important; width: auto; height: auto; }
  #stage > section { position: relative; display: flex !important; width: 1920px; height: 1080px; page-break-after: always; }
  #notes, #hud { display: none !important; }
  .in { animation: none !important; }
}
"""

VIEWER_JS = """
const slides = [...document.querySelectorAll('#stage > section')];
const notes = document.getElementById('notes'), hud = document.getElementById('hud'), stage = document.getElementById('stage');
let i = Math.max(0, Math.min(slides.length - 1, (parseInt(location.hash.replace('#slide-', '')) || 1) - 1));
function fit() { const s = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = `translate(-50%, -50%) scale(${s})`; }
function show(n) {
  i = Math.max(0, Math.min(slides.length - 1, n));
  slides.forEach((s, k) => s.classList.toggle('on', k === i));
  const a = slides[i].querySelector('aside'); notes.textContent = a ? a.textContent.trim() : '(sin notas)';
  hud.textContent = `${i + 1} / ${slides.length} · N notas · F pantalla completa`;
  history.replaceState(null, '', '#slide-' + (i + 1));
}
addEventListener('keydown', e => {
  if (['ArrowRight', 'PageDown', ' '].includes(e.key)) show(i + 1);
  else if (['ArrowLeft', 'PageUp'].includes(e.key)) show(i - 1);
  else if (e.key === 'Home') show(0);
  else if (e.key === 'End') show(slides.length - 1);
  else if (e.key.toLowerCase() === 'n') notes.classList.toggle('on');
  else if (e.key.toLowerCase() === 'f') document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
});
addEventListener('click', e => { if (!notes.contains(e.target)) show(e.clientX > innerWidth / 2 ? i + 1 : i - 1); });
addEventListener('resize', fit); fit(); show(i);
"""


class SlideText(HTMLParser):
    """Texto de una diapositiva: cada bloque (título, párrafo, celda) con su etiqueta y clases, y las notas."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, set[str], str]] = []
        self.notes = ""
        self._open: list[tuple[str, set[str]]] = []  # bloque abierto: etiqueta y clases
        self._buffer: list[str] = []
        self._in_notes = False
        self._skip = 0  # profundidad dentro de un elemento `equipo`

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get("class") or "").split())
        if self._skip or "equipo" in classes:
            self._skip += 1
            return
        if tag == "aside":
            self._in_notes = True
        elif tag in BLOCKS and not self._open:
            self._open.append((tag, classes))
            self._buffer = []
        elif tag == "br":
            self._buffer.append(" ")

    def handle_endtag(self, tag):
        if self._skip:
            self._skip -= 1
            return
        if tag == "aside":
            self._in_notes = False
        elif self._open and tag == self._open[-1][0]:
            name, classes = self._open.pop()
            text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
            if text:
                self.blocks.append((name, classes, text))

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_notes:
            self.notes += data
        elif self._open:
            self._buffer.append(data)


def heading_slug(text: str) -> str:
    """El ancla que la web da a un título (`web/src/components/markdown.tsx`): minúsculas, sin acentos, guiones."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", text))


def wiki_page(deck: dict, slides: list[tuple[str, str]]) -> str:
    lines = [
        "# Hackathon pitch",
        "",
        "Presentación de Discovery Data Agent para el hackathon AWS Builders League · Women Agentic 2026 (formato Shark",
        "Tank: 5 minutos de pitch y 2 de preguntas). Las diapositivas principales van primero y los anexos, para la ronda",
        "de preguntas, al final. Cada una lleva sus notas del orador: tiempo, quién habla y qué decir.",
        "",
        "Esta página se genera con `scripts/build_pitch.py` desde [docs/pitch](../pitch/README.md); no se edita a mano.",
        "La presentación para proyectar es `docs/pitch/presentacion.html`. Los marcadores `[N]`, `[x h]` y `[__]` se",
        "completan con datos reales del equipo antes del pitch.",
        "",
        "| # | Diapositiva |",
        "|---|---|",
    ]
    parsed = []
    for slide_id, html in slides:
        parser = SlideText()
        parser.feed(html)
        title = next((t for tag, _, t in parser.blocks if tag in ("h1", "h2")), slide_id)
        parsed.append((slide_id, title, parser))
    for n, (slide_id, title, _) in enumerate(parsed, 1):
        lines.append(f"| {n} | [{title}](#{heading_slug(f'{n}. {title}')}) |")
    for n, (slide_id, title, parser) in enumerate(parsed, 1):
        eyebrow = next((t for _, classes, t in parser.blocks if "eyebrow" in classes), "")
        lines += ["", f"## {n}. {title}", ""]
        if eyebrow:
            lines += [f"*{eyebrow}*", ""]
        for tag, classes, text in parser.blocks:
            if text in (title, eyebrow):
                continue
            lines.append(f"- **{text}**" if tag == "h3" or "dt" in classes or "k" in classes else f"- {text}")
        notes = parser.notes.strip()
        if notes:
            lines += ["", "**Notas del orador**", ""]
            lines += ["> " + line if line.strip() else ">" for line in notes.splitlines()]
    return "\n".join(lines) + "\n"


def build() -> Path:
    deck = json.loads((SRC / "deck.json").read_text(encoding="utf-8"))
    css = (SRC / "deck.css").read_text(encoding="utf-8")
    fonts = sorted({face["href"] for face in deck.get("faces", {}).values() if face.get("href")})
    sections = []
    for slide_id in deck["order"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", slide_id):
            raise SystemExit(f"Id de diapositiva no válido en deck.json: {slide_id!r}")
        sections.append((SRC / "slides" / f"{slide_id}.html").read_text(encoding="utf-8").strip())
    WIKI_OUT.write_text(wiki_page(deck, list(zip(deck["order"], sections))), encoding="utf-8")
    links = "\n".join(f'<link rel="stylesheet" href="{escape(href)}">' for href in fonts)
    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(deck["title"])}</title>
<!-- Generado por scripts/build_pitch.py desde docs/pitch/project/. No editar a mano. -->
{links}
<style>
{css}
{VIEWER_CSS}
</style>
</head>
<body>
<div id="stage">
{chr(10).join(sections)}
</div>
<div id="notes"></div>
<div id="hud"></div>
<script>{VIEWER_JS}</script>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(f"Generado {build().relative_to(ROOT.parents[1])}")
