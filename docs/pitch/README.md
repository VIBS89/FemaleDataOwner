# Presentación del hackathon (Shark Tank)

Pitch de Discovery Data Agent para el hackathon AWS Builders League · Women Agentic 2026: 7 diapositivas para 5 minutos más
3 de anexo para la ronda de preguntas. Cada diapositiva trae en sus notas el tiempo, quién habla y qué decir.

| Archivo | Qué es |
|---|---|
| [presentacion.html](presentacion.html) | La presentación lista para abrir en el navegador. Se genera; no se edita a mano |
| `project/deck.json` | Título, orden de las diapositivas, secciones y tipografías |
| `project/deck.css` | Colores (rojo de marca `#D9272E`), tipografías (Nunito, Nunito Sans) y estilos compartidos |
| `project/slides/<id>.html` | Una diapositiva por archivo: un `<section>` de 1920×1080 con sus notas en `<aside>` |

## Verla y presentarla
Abrir `presentacion.html` en el navegador (doble clic; no necesita servidor).

| Tecla | Acción |
|---|---|
| → / Espacio / clic a la derecha | Siguiente |
| ← / clic a la izquierda | Anterior |
| N | Mostrar u ocultar las notas del orador |
| F | Pantalla completa |
| Ctrl+P → Guardar como PDF | Exportar a PDF, una página por diapositiva |

Las tipografías se cargan de Google Fonts: sin internet se ven con Arial. Para PowerPoint, usar la versión en claude.ai
(Compartir → Exportar).

## Actualizarla con Claude
Pidan a Claude Code, en este repositorio, el cambio en lenguaje natural. Por ejemplo:

> En la presentación de `docs/pitch`, completa la diapositiva `problema` con 12 entrevistas y 6 h por semana, y
> actualiza la de `impacto` con el cálculo. Después vuelve a generar `presentacion.html`.

Reglas para quien edite, persona o Claude:
1. Editar solo `project/` y después regenerar el HTML:
   ```bash
   .venv/Scripts/python scripts/build_pitch.py
   ```
2. Una diapositiva es un único `<section id="<id>">`; su `id` es el nombre del archivo y debe estar en `order` de
   `deck.json`. Para añadir una, crear el archivo y poner su id en `order`.
3. Estilos compartidos en `deck.css` con clases (`card`, `box`, `step`…), no con `#id`. Texto de 24 px como mínimo.
4. Las notas van en el `<aside>`, como último hijo del `<section>`.
5. No inventar cifras: los marcadores `[N]`, `[x h]` y `[__]` se completan con datos reales del equipo.

## Versión en claude.ai
La presentación también vive como artifact de Slides en claude.ai, donde se edita con el ratón y se exporta a PowerPoint o
PDF. Si se cambia allí, pedir a Claude que la vuelva a descargar a `docs/pitch/project/` y regenere el HTML, para que el
repositorio no quede atrás. Si se cambia aquí, pedirle que la vuelva a publicar en el artifact.
