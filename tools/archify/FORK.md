# Archify — fork de ConverData

Copia de [tt-a1i/archify](https://github.com/tt-a1i/archify) v3.1.0 (MIT) con un cambio: los componentes aceptan un
campo **`description`**, que se muestra en la ficha del componente (*Semantic Passport*) al hacer clic.

## Cambios respecto al original
| Archivo | Cambio |
|---|---|
| `schemas/architecture.schema.json` | `components[].description` (string, de 1 a 600 caracteres) |
| `schemas/workflow.schema.json` | `nodes[].description` |
| `schemas/sequence.schema.json` | `participants[].description` |
| `renderers/shared/generated-validators.mjs` | Regenerado con `node scripts/generate-validators.mjs` (requiere `ajv@8.17.1`) |
| `scripts/generate-validators.mjs` | Copiado del repositorio fuente (no viene en el paquete de la skill) |
| `renderers/shared/cli.mjs` | `focusNodeAttrs` emite `data-node-description`; `focusNodeTitle` la incluye en el `<title>` SVG |
| `renderers/architecture/render-architecture.mjs`, `renderers/workflow/workflow-compiler.mjs`, `renderers/sequence/render-sequence.mjs` | Pasan `description` al passport |
| `assets/template.html` | Elemento `#focus-description` en la ficha, su CSS y una línea en `renderPassport()` que lo rellena |

## Uso
```bash
node tools/archify/bin/archify.mjs finalize architecture docs/architecture/<x>.archify.json docs/architecture/<x>.html --quality showcase --json
```
Los diagramas con `description` **deben** renderizarse con este fork: la skill global los rechaza por `additionalProperties`.

## Regenerar validadores tras tocar un schema
```bash
cd tools/archify && npm install --no-save ajv@8.17.1 && node scripts/generate-validators.mjs && node bin/archify.mjs doctor
```

## Actualizar desde upstream
Reaplicar la tabla de cambios sobre la nueva versión. Son unas 15 líneas, aisladas y fáciles de portar.
