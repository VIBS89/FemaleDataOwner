"""Arma docs/pitch/presentacion.html a partir de las fuentes de la presentación en docs/pitch/project/.

Uso: .venv/Scripts/python scripts/build_pitch.py

Las fuentes son las del artifact de Slides en claude.ai: `deck.json` (orden y tipografías), `deck.css` (estilos
compartidos) y una `slides/<id>.html` por diapositiva. El HTML resultante se abre en cualquier navegador, sin
servidor: flechas para avanzar, N para las notas, F para pantalla completa e Imprimir para guardarlo en PDF.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs" / "pitch"
SRC = ROOT / "project"
OUT = ROOT / "presentacion.html"

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


def build() -> Path:
    deck = json.loads((SRC / "deck.json").read_text(encoding="utf-8"))
    css = (SRC / "deck.css").read_text(encoding="utf-8")
    fonts = sorted({face["href"] for face in deck.get("faces", {}).values() if face.get("href")})
    sections = []
    for slide_id in deck["order"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", slide_id):
            raise SystemExit(f"Id de diapositiva no válido en deck.json: {slide_id!r}")
        sections.append((SRC / "slides" / f"{slide_id}.html").read_text(encoding="utf-8").strip())
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
