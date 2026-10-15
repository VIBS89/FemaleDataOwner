# F24 — Curación y captura del conocimiento institucional · común

> Origen: Propuesta — "reducir la dependencia del conocimiento tribal", "preservación del conocimiento institucional",
> "conocimiento institucional obtenido de interacciones históricas y aportes de expertos".

## Historia de usuario
Como **responsable funcional o técnico de un dominio de datos**, quiero responder una sola vez las dudas sobre mis datos y que esa respuesta
quede disponible para todos, en lugar de contestar la misma pregunta a cada equipo.

## Roles
| Rol | Quién | Qué puede hacer |
|---|---|---|
| `consumer` | Cualquier colaborador autorizado | Descubrir, confirmar o rechazar candidatos, escalar dudas |
| `steward` | Responsable de un dominio (funcional o técnico), en `config/owners.yaml` | Revisar descripciones, reglas y vínculos de su dominio; responder dudas escaladas |
| `data_admin` | Gerencia de Datos / Plataformas de Datos | Todo lo anterior, gestionar fuentes y dominios |

```yaml
# config/owners.yaml
- domain: onboarding_digital
  assets: ["VBank_ING.dbo.*", "Onboarding.dbo.*"]
  business_owner: {name: "Producto Banca Digital", group: "GG-Datos-BancaDigital"}
  technical_owner: {name: "Ingeniería de Datos — Canales", group: "GG-IngDatos-Canales"}
```
Los grupos se resuelven contra el IdP corporativo (F14). Las personas no se guardan en el catálogo, solo grupos o roles.

## Captura desde el uso
1. **Confirmación de candidatos**: cada candidato de F22 tiene "✔ Es este", "✖ No es" y "El correcto es…" (búsqueda en el catálogo).
2. **Golden discovery**: una confirmación genera un par `plantilla de la pregunta → asset_key` (literales sustituidos, como en F2).
   - Confirmado por un `steward` del dominio: entra al índice de inmediato (`confirmation_score = 1.0`).
   - Confirmado por usuarios: entra al índice cuando lo confirman ≥ 2 usuarios distintos sin rechazos (`0.7`).
   - Un "✖" de un `steward` retira el par del índice.
3. **Escalamiento al responsable**: con `knowledge_gap = true` o a petición del usuario, "Preguntar al responsable" crea una
   `curation_request` (pregunta reescrita, candidatos mostrados y dominio probable) asignada al grupo `steward` del dominio.
   - Se notifica por correo o Teams (webhook configurable). El contenido viaja dentro de la red corporativa.
   - La respuesta del steward puede: elegir un activo, escribir o corregir una descripción, crear una regla de negocio o marcar el dato como
     "no existe en las fuentes catalogadas" (registrado como brecha).
   - La respuesta se convierte en conocimiento revisado (`description_source: human`, `reviewed: true`) y en golden discovery, y se notifica al
     usuario que preguntó.
   - **Permisos**: la respuesta al usuario sigue filtrada por sus `visible_ids` (F14). Si el activo correcto está fuera de su visibilidad,
     el usuario solo recibe "el responsable indicó que requieres acceso; solicítalo por el proceso de accesos", sin nombres de objetos;
     el steward es quien decide si lo concede.

## Revisión del catálogo
- Vista web **Curación** (solo `steward` y `data_admin`), filtrada por dominio:
  - descripciones `generated` o con `conflict: true`, ordenadas por **número de búsquedas** (lo más consultado primero);
  - reglas sugeridas y vínculos documento→activo sin revisar;
  - solicitudes escaladas pendientes, con antigüedad.
- Las ediciones se escriben como `*.human.yaml` junto al YAML generado (nunca se sobrescriben en un `refresh`) y se versionan en git con el
  autor (grupo) y la fecha. El indexador reindexa solo el activo editado.
- `converdata catalog review --unreviewed --domain <d>` sigue disponible por CLI.

## Reporte de brechas de conocimiento
`converdata knowledge gaps` (y la pestaña "Brechas" de Curación) lista:
- preguntas sin candidato ≥ 0.6, agrupadas por similitud (temas que nadie ha documentado);
- activos más buscados con descripción `generated` o sin descripción;
- activos con conflictos entre fuentes;
- dominios sin `steward` asignado;
- documentos obsoletos (origen modificado o sin vínculos válidos).
Es la base de la visión futura "Identificación de brechas de conocimiento" y alimenta la métrica de activos documentados (F25).

## Criterios de aceptación
1. Una duda escalada y respondida por el steward aparece como candidato principal (confianza ≥ 0.85) cuando otro usuario hace una pregunta
   equivalente.
2. Un "✖" del steward retira el golden discovery y el activo deja de recibir el bonus en la siguiente búsqueda.
3. Un `catalog refresh` no sobrescribe ningún `*.human.yaml` (test).
4. Un `consumer` no puede editar descripciones ni ver la vista Curación (403).
5. El reporte de brechas lista las 3 preguntas de prueba sin respuesta sembradas en el set de evaluación.
