# F22 — Discovery Flow (descubrimiento de activos de datos) · común

> Origen: Propuesta "Enterprise Data Discovery Agent" (Banco Atlántida), secciones 3 y 5. Es el **caso de uso principal** de la propuesta;
> el AskFlow de texto a SQL (F4–F10) corresponde a la visión futura "Recomendación y generación de SQL".

## Historia de usuario
Como **ingeniero de datos, analista, científico de datos o Product Owner**, quiero describir en lenguaje natural el dato que necesito
("el identificador único del cliente usado en onboarding digital") y recibir en segundos una lista priorizada de campos y tablas
candidatas, con su ubicación (base de datos, ambiente, servidor), descripción funcional, reglas de negocio, relaciones y nivel de confianza,
para no depender de expertos ni de documentación dispersa.

## Diferencia con el AskFlow
| | DiscoverFlow (F22) | AskFlow (F3–F10) |
|---|---|---|
| Pregunta típica | "¿Dónde está el dato X?", "¿qué significa el campo Y?" | "¿Cuánto vendimos en Q3?" |
| Ejecuta SQL contra datos | **No** (solo catálogo, conocimiento y, si aplica, permisos) | Sí, con el login del usuario |
| Requiere login SQL del usuario | Sí, para calcular su visibilidad (F14); no consulta datos | Sí |
| Latencia objetivo | p50 < 5 s · p95 < 10 s | p50 < 12 s · p95 < 30 s (producción; el MVP admite p95 < 40 s, OP-01) |
| Salida | `discovery` (candidatos) | `data` + `sql` |

## Pasos (grafo de LangGraph determinista)
1. **Intent** (F3): `intent = discovery`. Extrae `entities`, `business_context` (p. ej. "onboarding digital"), `asset_kind_hint`
   (columna, tabla, indicador, regla) y `environment_hint` ("producción" por defecto).
2. **Recuperación híbrida** (F2), filtrada por visibilidad (F14):
   - `search_columns(k=50)` y `search_tables(k=30)`;
   - `search_knowledge(kinds=[glossary, business_rule, document, annotation, etl], k=30)` (F23, F24);
   - `search_golden_discovery(k=5)`: preguntas parecidas ya confirmadas por usuarios o expertos (F24).
   Los hits de conocimiento suman puntos a los activos que mencionan (`linked_assets`).
   Si la pregunta nombra una entidad de negocio del grafo del patrimonio ([F19](F19-multi-db-discovery.md), herramienta `where_is`),
   se añaden su tabla canónica y sus copias en otras BDs (aristas `same_entity`).
3. **Agrupación por activo lógico**: los objetos físicos con el mismo `asset_key` en varios ambientes (F1) se agrupan en un candidato con
   `locations[]`. Si los `schema_hash` difieren entre ambientes, se añade el aviso "QA difiere de producción".
4. **Reranking con LLM**: el nodo `rerank` (rol `planner` de F16, temperatura 0, salida estructurada) recibe hasta 25 candidatos en formato compacto
   (id, descripción, fuente de la descripción, reglas, evidencias) y devuelve un orden con `relevance` (0..1) y una justificación de una línea
   por candidato. **No puede añadir candidatos que no estén en la lista** (se valida el id).
5. **Expansión de contexto** para los 5 primeros:
   - relaciones por FK y relaciones entre BDs (grafo de F4 y F19, `find_join_path`; las inferidas se marcan como tales);
   - linaje ETL de entrada y salida a un salto (F23);
   - reglas de negocio vinculadas (F23);
   - responsable funcional y técnico (F24);
   - indicadores certificados de la capa semántica que usan el activo ([F21](F21-semantic-layer.md), `list_metrics`);
   - **alternativas**: columnas con la misma semántica (sinónimos, mismo término de glosario o mismo nombre normalizado) en otras tablas.
6. **Cálculo de confianza** (abajo).
7. **Respuesta**: el nodo `respond` (rol `fast` de F16, en streaming) redacta 1 a 4 frases que recomiendan el candidato principal y explican
   por qué; **no puede mencionar objetos que no estén en `candidates`, `alternatives` o `related`** (validación por id). Las tarjetas se
   envían antes que la narrativa, así que el usuario ve los candidatos sin esperar al texto.
8. **Brecha de conocimiento**: si ningún candidato llega a 0.6, `knowledge_gap = true` y se ofrece "Preguntar al responsable del dominio" (F24).

## Resumen de dominio (intent `exploration`)
Para "¿qué datos tenemos de X?" (F3, RF-11) el flow usa el mismo grafo con otro paso 2: `estate_overview(domain)` (F19) y `search_tables`
filtrados por visibilidad. Devuelve como `candidates` las tablas principales del dominio (`kind: table`, tabla canónica primero), sus columnas
clave, responsables, reglas destacadas y `suggested_questions`. No ejecuta SQL sobre datos.

## Contrato: sección `discovery` del `AnswerEnvelope`
```json
"discovery": {
  "candidates": [
    {
      "rank": 1,
      "kind": "column",
      "asset_key": "VBank_ING.dbo.Users.ClientCode",
      "database": "VBank_ING", "schema": "dbo", "table": "Users", "column": "ClientCode",
      "data_type": "varchar(20)",
      "locations": [
        {"environment": "produccion", "server": "SRVPRDSQL01"},
        {"environment": "qa", "server": "SRVQASQL01"}
      ],
      "description": "Código que identifica a los clientes digitales registrados.",
      "description_source": "human",
      "business_rules": [{"id": "BR-ONB-004", "text": "Se asigna al completar la verificación de identidad.", "reviewed": true}],
      "owners": {"business": "Producto Banca Digital", "technical": "Ingeniería de Datos — Canales"},
      "lineage": {"upstream": ["Onboarding.dbo.Solicitud"], "downstream": ["DWH.dim.Cliente"]},
      "evidence": [
        {"kind": "data_dictionary", "source": "Diccionario_VBank.xlsx#Users", "reviewed": true},
        {"kind": "golden_discovery", "source": "3 confirmaciones previas"}
      ],
      "why": "Es la clave que usa el flujo de onboarding y la que replica el DWH.",
      "confidence": 0.92
    }
  ],
  "alternatives": [
    {"asset_key": "VBank_ING.dbo.Users.LegalClientId", "why": "Identificador legal del cliente (core), no el digital.", "confidence": 0.71},
    {"asset_key": "VBank_ING.dbo.Users.UserId", "why": "Identificador técnico del usuario de la app.", "confidence": 0.64}
  ],
  "related": [
    {"from": "VBank_ING.dbo.Users", "to": "VBank_ING.dbo.UserDevices", "relation": "fk", "on": "UserId"},
    {"from": "Onboarding.dbo.Solicitud", "to": "VBank_ING.dbo.Users", "relation": "etl", "via": "SSIS:ONB_CargaUsuarios"}
  ],
  "knowledge_gap": false,
  "suggested_questions": ["¿Qué reglas aplican al estado de la solicitud de onboarding?"]
}
```
- **Solo se devuelve lo que el usuario puede leer** (F14): candidatos, ubicaciones, alternativas, relaciones, linaje, reglas y evidencias se
  filtran por `visible_ids`. Una ubicación en un ambiente sin permiso no aparece.
- `server` se muestra como alias configurable (`alias` en `config/databases.yaml`, F1), nunca como cadena de conexión.
- `description_source`: `human` | `data_dictionary` | `ms_description` | `document` | `generated`. La UI etiqueta las descripciones
  `generated` como "sugerida por IA, sin revisar".

## Confianza de descubrimiento
```
confidence = 0.35*relevance_llm + 0.25*retrieval_score_norm + 0.15*evidence_strength
           + 0.15*confirmation_score + 0.10*source_agreement
```
| Factor | Cálculo |
|---|---|
| `relevance_llm` | Puntuación del reranker (paso 4) |
| `retrieval_score_norm` | Score híbrido normalizado al mejor hit de la consulta |
| `evidence_strength` | `human` 1.0 · `data_dictionary` 0.9 · `ms_description` 0.8 · `document` 0.6 · `generated` 0.3 |
| `confirmation_score` | 1.0 si un experto confirmó este activo para una pregunta similar (≥ 0.85); 0.7 si lo confirmaron ≥ 2 usuarios; 0 en otro caso |
| `source_agreement` | Fuentes independientes que apuntan al activo (catálogo, diccionario, documento, ETL, golden), normalizado a 3 |

- Tope de 0.6 si la única evidencia es `generated`.
- Se muestra en porcentaje (p. ej. "92 %"). La calibración se mide en F25.

## Herramientas
`discover(question)`, `get_asset(asset_key)`, `get_related(asset_key, depth=1)`, `get_lineage(asset_key, direction, depth)`,
`list_business_rules(asset_key|domain)`, `find_alternatives(asset_key)`. Todas reciben la identidad desde el contexto autenticado (F14).

## Criterios de aceptación
1. Con el catálogo de prueba `VBank_ING` (fixture de la propuesta), "Necesito encontrar el identificador único del cliente utilizado en procesos
   de onboarding digital" devuelve `ClientCode`, `LegalClientId` y `UserId` entre los 3 primeros (candidatos + alternativas), con base de datos,
   tabla, ambiente, servidor, descripción y confianza.
2. Cada candidato trae los 8 elementos de la propuesta: tabla, campo, base de datos, ambiente, servidor, descripción, confianza y relaciones.
3. El DiscoverFlow no consulta tablas de datos: el login del usuario solo se usa para calcular `visible_ids` (test: ninguna consulta de datos
   queda en la traza).
4. Un usuario sin permiso sobre `VBank_ING` no recibe ningún candidato, ubicación, relación, regla ni evidencia de esa BD; recibe
   "no encontré datos disponibles para ti sobre …" sin mención a sus tablas (F14).
5. Ningún objeto mencionado en la narrativa está fuera de `candidates`, `alternatives` o `related` (test sobre el set de evaluación).
6. Hit@3 ≥ 85 % y Hit@1 ≥ 65 % en el set de evaluación de descubrimiento (F25).
7. p95 < 10 s en el set de evaluación.
