# F24 — Curación y captura del conocimiento institucional · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Regla de votos, plantilla e historial actualizados el 2026-11-17.
>
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
Los grupos se resuelven como indica F14 (§Grupos y roles): AD por LDAP (pendiente, HU-13). Hoy los responsables de curación se
asignan por login SQL y dominio: los administra el `data_admin` desde la pestaña Responsables de Administración
(`GET`/`PUT /admin/stewards`), y cada cambio se audita antes de aplicarse (`stewards_updated`). Un rol que se da por nombre de login solo cuenta si la sesión validó ese login en un servidor con `environment: produccion`, cuando el inventario tiene alguno (`identity_trusted`): quien administra un servidor de desarrollo o de QA puede crear allí un login con cualquier nombre. Es una política por confirmar con el banco (PRD §13, pregunta abierta 9). Las personas no se
guardan en el catálogo, solo grupos o roles. On-premise, `owners.yaml` se carga en la tabla `curation.owners` (OP-02).

## Captura desde el uso
1. **Confirmación de candidatos**: cada candidato de F22 tiene "✔ Es este", "✖ No es" y "El correcto es…" (búsqueda en el catálogo).
2. **Golden discovery**: una confirmación genera un par `plantilla de la pregunta → asset_key`.
   - **Plantilla anónima** (`converdata.curation.question_template`): la pregunta normalizada y sin literales. Regla
     (`converdata.memory.text.strip_literals(question, known)`, endurecida tras la revisión de seguridad del 2026-11-17; ya no hay
     lista de formatos): la pregunta se normaliza con NFKC (los dígitos en superíndice, de ancho completo o en círculo cuentan como
     dígitos) y **toda palabra con algún dígito o con arroba es un literal**, salvo que sea vocabulario conocido del banco: un
     nombre del catálogo con dígitos (`Catalog.names_with_digits`, p. ej. `Ultimos4`) o un código del conocimiento con letras y
     dígitos (`KnowledgeBase.codes`, p. ej. `NCB-022`, `BR-ONB-004`). Para la plantilla y para decidir si se guarda el original, el
     vocabulario es el del catálogo entero más los códigos del conocimiento (`AgentRuntime._vocabulary`). Consecuencias: `T24` o
     `F14` salen de la plantilla si no son nombres del catálogo ni códigos del glosario (antes se conservaban); `NCB-022` se
     conserva solo si el glosario del banco lo nombra; `ACME090`, `ACME_TEST_123`, `AB12CD34`, los correos con tildes y los números
     con formatos raros ya no pasan. Motivo: la revisión reprodujo que formas realistas (`ACME090`, dígitos en superíndice, guion
     final, raya) llegaban a la plantilla y al texto original con la regla por formatos. Es la misma función con la que el
     descubrimiento deja de contar los literales como conceptos (F22). Dos preguntas que solo difieren en un código que el banco
     no tiene en su glosario comparten plantilla y confirmación.
     Se quitan todos los números, también los
     umbrales de negocio: "mora mayor a 90 días" y "a 30 días" son la misma confirmación (decisión del 2026-11-17). Si tras quitar
     los literales aún parece llevar datos personales, el voto cuenta y se audita, pero no se aprende. El texto original se guarda
     aparte (on-premise, `golden.golden_discovery_original`) solo si la pregunta no tiene ningún literal con esta regla (`has_literals`)
     ni dispara el detector de datos personales (`find_pii`). Limitaciones: no detecta nombres de personas, texto entre comillas
     ni los trozos solo de letras de un código partido por espacios (un IBAN escrito con espacios deja sus grupos de letras) (F17).
     Prueba de punta a punta con 100 literales distintos en 10 formas: `api/tests/test_marked_literals.py` (ninguno llega a las
     plantillas, a los votos ni al índice, y las plantillas solo contienen palabras de las preguntas base).
   - El voto no lleva comentario ni otro texto libre.
   - **Regla de votos** (`converdata.curation.resolve_golden`):
     - Voto de un `steward` del dominio: entra al índice de inmediato (`confirmation_score = 1.0`), y su "✖" retira el par. El
       índice se actualiza antes de responderle, así que rige en la siguiente búsqueda (CA2); el voto de un usuario reindexa en
       segundo plano.
     - Votos de usuarios: cuentan las **confirmaciones netas** (confirmaciones menos rechazos, con el último voto de cada usuario).
       Con 2 o más pesa en la confianza (`0.7`); con 0 o menos el par se retira del índice. Un solo "✖" no retira lo que
       confirmaron varios.
     - Si el par ya lo confirmó un `steward`, los votos de usuarios no cambian su decisión.
3. **Escalamiento al responsable**: con `knowledge_gap = true` o a petición del usuario, "Preguntar al responsable" crea una
   `curation_request` (pregunta reescrita, candidatos mostrados y dominio probable) asignada al grupo `steward` del dominio.
   - La crea la ruta `POST /curation/requests` de la API (F12) y se guarda solo on-premise (F17).
  - Se notifica por un webhook de Teams (`CONVERDATA_NOTIFY_WEBHOOK`). La notificación solo lleva el dominio y un enlace a la vista Curación; el texto de la pregunta se lee dentro de la aplicación (OP-04, CN-04).
   - La respuesta del steward puede: elegir un activo, escribir o corregir una descripción, crear una regla de negocio o marcar el dato como
     "no existe en las fuentes catalogadas" (registrado como brecha).
   - La respuesta se convierte en conocimiento revisado (`description_source: human`, `reviewed: true`) y en golden discovery, y se notifica al
     usuario que preguntó.
   - **Permisos**: la respuesta al usuario sigue filtrada por sus `visible_ids` (F14). Si el activo correcto está fuera de su visibilidad,
     el usuario solo recibe "el responsable indicó que requieres acceso; solicítalo por el proceso de accesos", sin nombres de objetos;
     el steward es quien decide si lo concede.

## Revisión del catálogo
- **Ser responsable no da lectura**: fuera de sus dominios, un activo que su login no puede ver responde igual que uno que no
  existe; el historial de una descripción exige además poder ver el activo; la bandeja solo muestra, de lo que se enseñó al
  usuario, los activos de sus dominios. Dentro de sus dominios, la cola de revisión y la edición no filtran por visibilidad
  (PRD §13, pregunta abierta 7).
- Una regla cuyos activos ya no existen solo la gestiona quien cura el dominio de la regla.
- Vista web **Curación** (solo `steward` y `data_admin`), filtrada por dominio:
  - descripciones `generated` o con `conflict: true`, ordenadas por **número de búsquedas** (lo más consultado primero);
  - reglas sugeridas y vínculos documento→activo sin revisar;
  - solicitudes escaladas pendientes, con antigüedad.
- Las ediciones humanas se guardan separadas de lo generado (`description_source: human`) y **nunca se sobrescriben en un `refresh`**;
  quedan versionadas con el autor (hoy el login; el grupo, con HU-13) y la fecha en las *temporal tables* de la BD `ConverData`
  (OP-02). Cada edición escribe sus filas en la BD y queda en la auditoría; tras cada una se recarga el índice en memoria. Sin BD
  (desarrollo y modo demo) se guardan en archivos.
- **Historial de una descripción**: el botón "Historial" de la vista Curación y de la ficha del activo muestra sus versiones con
  autor y fecha (`GET /curation/history?asset_key=`, solo para responsables del dominio del activo que además pueden verlo con su login; sin BD
  no hay historial). Cada entrada es un cambio real de la descripción, atribuido a quien la escribió.
- `converdata catalog review --unreviewed --domain <d>` por CLI: pendiente.

## Reporte de brechas de conocimiento
`converdata knowledge gaps` (pendiente como comando; hoy, la cola de revisión de Curación, `GET /curation/review`) lista:
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
3. Un `catalog refresh` no sobrescribe ninguna edición humana (test en ambos despliegues).
4. Un `consumer` no puede editar descripciones ni ver la vista Curación (403).
5. El reporte de brechas lista las 3 preguntas de prueba sin respuesta sembradas en el set de evaluación.
