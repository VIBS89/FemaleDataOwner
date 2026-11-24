# Descubrimiento (DiscoverFlow)

Actualizado el 2026-11-17.

**Para qué sirve.** Recibe una pregunta en lenguaje natural ("¿dónde está el DUI del cliente?") y devuelve un `AnswerEnvelope`
con candidatos (tabla o columna, ubicación por ambiente, descripción, reglas, relaciones, responsables y confianza), alternativas,
caminos de unión y si hay una brecha de conocimiento. Solo lee el catálogo y el conocimiento en memoria: nunca consulta datos.
Lo usan la API (`/discover`, `/discover/stream`), el MCP (`discover`) y la CLI a través de `DiscoverService`.

**Lo esencial**
- Es un grafo de LangGraph con pasos fijos y dos ciclos acotados a un reintento cada uno. El orden nunca lo decide el modelo.
- Toda búsqueda exige `visible_ids`; sin ellos el índice lanza `ValueError` (`src/discovery_data_agent/memory/memory_store.py:198`).
- La búsqueda es léxica (BM25 en memoria + coincidencia exacta del nombre técnico, fusionadas con RRF). No hay embeddings.
- Con o sin LLM el flujo responde: cada nodo con modelo tiene un respaldo determinista.
- La confianza es una suma ponderada con topes que la bajan del umbral de brecha (0,6) cuando la respuesta no es segura.
- Si la auditoría no se escribe, la respuesta no se entrega (fail-closed).

Diagramas: [flujo de descubrimiento](../../architecture/flujo-descubrimiento.html) ·
[permisos heredados](../../architecture/permisos-heredados.html).

## Responsabilidades
- Clasificar la pregunta (descubrimiento, exploración, consulta de datos, fuera de alcance, ambigua).
- Recuperar activos visibles del catálogo, del conocimiento (glosario, reglas, documentos, ETL, diccionario) y de confirmaciones previas.
- Ordenar, revisar y expandir el resultado (ubicaciones, reglas, linaje, relaciones, alternativas, caminos de unión).
- Calcular la confianza y marcar la brecha de conocimiento.
- Redactar la narrativa sin nombrar objetos ajenos a la respuesta.
- Dejar un registro de auditoría por pregunta, con un paso por nodo.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| `DiscoverService`, `build_discover_graph` | `src/discovery_data_agent/flows/discover.py` | Grafo, estado, nodos, `run` y `stream` |
| `DiscoverDeps` | `src/discovery_data_agent/flows/discover.py:61` | Catálogo, conocimiento, índice, puertos LLM, grafo, auditoría |
| Motor determinista | `src/discovery_data_agent/discovery/engine.py` | Recuperación, cobertura, confianza, revisión, expansión, guardas |
| Implementaciones sin LLM | `src/discovery_data_agent/discovery/deterministic.py` | `RuleBasedIntentClassifier`, `ScoreReranker`, `TemplateNarrator` |
| Plan de consulta | `src/discovery_data_agent/discovery/expansion.py` | Léxico es→en, `decompose`, `QueryPlan`, `plan_query` |
| Puertos | `src/discovery_data_agent/discovery/ports.py` | `IntentClassifier`, `Reranker`, `Narrator`, `QueryExpander`, `Reviewer` |
| Índice | `src/discovery_data_agent/memory/memory_store.py` | `InMemoryVectorStore`: BM25 + nombre exacto + RRF, filtrado por visibilidad |
| Puerto del índice | `src/discovery_data_agent/memory/base.py` | `VectorStore` (nombre histórico; no hay vectores) |
| Texto | `src/discovery_data_agent/memory/text.py` | `tokenize`, stemmer de prefijo, `strip_literals`, `normalized_name` |
| Grafo del patrimonio | `src/discovery_data_agent/graph/estate.py` | Aristas `fk`, `same_entity`, `etl`, `view`; copias y caminos de unión |
| Catálogo en memoria | `src/discovery_data_agent/catalog/store.py` | `Catalog`, `KnowledgeBase`, `CatalogSnapshot`, puertos de repositorio |
| Modelos | `src/discovery_data_agent/models/` | `IntentResult`, `Discovery`, `Candidate`, `AnswerEnvelope`, `UserContext`, `CatalogObject` |
| Ajustes | `src/discovery_data_agent/config.py:81` | `DiscoverySettings`, `ConfidenceWeights`, `Patterns` |
| Ensamblado | `src/discovery_data_agent/bootstrap.py:83` | Indexa y conecta los puertos LLM según el gateway |

## Cómo funciona

```
START → intent ─┬─► retrieve → grade ─┬─► rerank → expand → review ─┬─► respond → finalize → END
                │       ▲             │              ▲              ├─► compute ─► respond   (cifras activas)
                │       └─ reintento ─┘ (máx. 1)     └─ corrección ─┘ (máx. 1)
                └─► finalize   (aclaración, fuera de alcance o pregunta sobre el asistente)
```

`compute` solo corre con `features.ask_flow` (o `DISCOVERY_DATA_AGENT_ASK_FLOW=1`) y un ejecutor de la sesión; calcula cifras agregadas de plantilla fija
(`discovery/figures.py`, apagadas por defecto; PRD §13, decisión 17).

Cada nodo (salvo `finalize`) va envuelto en `_timed` (`flows/discover.py:102`), que crea un `StepRecord` con duración, modelo,
error y detalle. El modelo solo se anota si el nodo lo usó de verdad (`_model_used`).

1. **intent** (rol `planner`). Entrada: pregunta e historial. Salida: `IntentResult` y `route`.
   - Clasifica con el puerto; si falla, usa las reglas (`error = fallback:<tipo>`).
   - `out_of_scope` → `finalize`. `ambiguous` o confianza < 0,6 → `clarify` → `finalize` (`flows/discover.py:148`).
   - `data_query`/`procedure` con `features.ask_flow = false` se responde como descubrimiento, con una suposición explícita. Con cifras activas el flujo descubre primero y el nodo `compute` calcula si puede.
   - Pregunta sobre el asistente o cortesía (`discovery/assistant.py`) → intención `assistant` → `finalize` con texto fijo y `discovery: null`. Los seguimientos se completan con el historial (`deterministic.contextualize`). La orden de modificar datos se rechaza mirando solo la pregunta actual (`is_write_request`).
   - **Pista de tipo de entidad**: si la intención no trajo `asset_kind_hint`, `engine.entity_kind_hint`
     (`discovery/engine.py:90`) mira "¿dónde están/se guardan… los/las X?": si X nombra una tabla o vista **visible**, pide `table`.
     No lo hace si una columna visible se llama como las dos primeras palabras, ni si la pregunta es compuesta.
2. **retrieve**. Entrada: intención y plan. Salida: `Retrieval` (borradores por `asset_key`) y `shortlist`.
   - `plan_query` (`discovery/expansion.py:142`): consulta original con peso 1 y, con el patrón D, una variante traducida es→en
     con `variant_weight` (0,8). Los conceptos de la pregunta salen sin literales ni palabras de foco (`META_TERMS`).
   - Por cada consulta: `search_columns` (k=50, salvo exploración), `search_tables` (k=30), `search_knowledge` (k=30) y, una vez,
     `search_golden_discovery` (k=5). Todas reciben `visible_ids`.
   - Puntuación bruta: hit de columna o tabla suma su score; el contexto de la tabla suma `0,5 ×` a sus columnas; el conocimiento
     suma `0,5 × score × cobertura del fragmento`; una confirmación suma `1,0 × score × similitud`; una entidad de negocio nombrada
     suma `0,5 × mejor_bruto × 0,2` a la tabla canónica y `× 0,1` a las copias (`discovery/engine.py:45`).
   - Calcula la cobertura de cada borrador (ver "Confianza y cobertura") y, si el grafo está activo, la cobertura a 1–2 saltos por FK.
3. **grade** (patrón C, rol `fast`). Calidad = mejor cobertura entre los 5 mejor recuperados. Si es < `grade_min_coverage` (0,6) y
   es el primer intento, añade hasta 3 variantes (del `QueryExpander` si existe; si no, la léxica) y vuelve a `retrieve`.
   `MAX_RETRIEVAL_ATTEMPTS = 2`.
4. **rerank** (patrón E, rol `planner`). Relevancia determinista = `cobertura^1,5 × factor_tipo × factor_rol`. Si hay reranker
   LLM y el ranking determinista no es decisivo (`top ≥ 0,85` y margen `≥ 0,10`, `engine.decisive`), llama al modelo.
   `apply_rerank` descarta ids desconocidos o repetidos y anota el error `ids_descartados:N`.
5. **expand**. `build_discovery` (`discovery/engine.py:610`): conserva lo visible con relevancia ≥ `min_relevance` (0,4) y, detrás,
   lo que cubre por el grafo (`graph_coverage ≥ 0,6`); agrupa copias de una entidad; elige hasta 3 candidatos de la misma familia
   (columna o no columna); añade alternativas, relaciones a un salto, caminos de unión y partes sin resolver.
   En exploración usa `expand_top` (5) candidatos.
6. **review** (patrón B, rol `judge`). Chequeos deterministas sobre el principal: `kind_mismatch` y `role_mismatch` (fallos),
   `low_coverage`, `generated_only`, `ambiguous_top` (avisos). Con un fallo, busca otro candidato que cumpla (`fix_candidate`),
   lo promueve y vuelve a `expand`. `MAX_REVIEW_ATTEMPTS = 2`. Si el fallo queda sin resolver, `cap_unresolved` baja la confianza a
   `gap_threshold − 0,01` y marca brecha.
7. **respond** (rol `fast`). Narrativa del puerto; se rechaza si nombra objetos fuera de la respuesta o trae enlaces, HTML o correos,
   y entonces se usa `TemplateNarrator` (`flows/discover.py:326`).
8. **finalize**. Arma el `AnswerEnvelope` según la ruta, escribe la auditoría y, si falla y `audit.fail_open` es falso, devuelve
   `status = error` sin contenido (`flows/discover.py:363`).

`stream` emite un evento `step` (nombre y etiqueta del nodo, sin contenido) al terminar cada nodo y un `answer` con el envelope al final.

### Confianza y cobertura
- **Cobertura** (`weighted_coverage`, `discovery/engine.py:309`): fracción ponderada de conceptos de la pregunta presentes en los
  términos del activo. Un concepto solo en texto débil cuenta `WEAK_TERM_WEIGHT = 0,5`. Débil = descripción `generated`, la
  descripción de la tabla para una columna y, si se pide una tabla, los nombres de sus columnas.
- **Calificativos desconocidos** (solo si se pide una tabla): un concepto que ningún activo recuperado nombra pesa
  `UNKNOWN_QUALIFIER_WEIGHT = 0,25` (`discovery/engine.py:296`). El primero (la entidad) nunca se descuenta. Si se descontó alguno,
  `unknown_qualifiers` se marca **en todos los borradores** y su confianza queda en `gap_threshold − 0,01`.
- **Confianza** (`compute_confidence`, `discovery/engine.py:583`):
  `0,35·relevancia + 0,25·recuperación_norm + 0,15·evidencia + 0,15·confirmación + 0,10·acuerdo`.
  Evidencia: `human` 1,0 · `data_dictionary` 0,9 · `ms_description` 0,8 · `document` 0,6 · `generated` 0,3.
  Confirmación: 1,0 si la confirmó un responsable con similitud ≥ 0,85; 0,7 con ≥ 2 confirmaciones de usuarios.
  Acuerdo: fuentes distintas (sin contar `estate`), hasta 3.
- **Topes**: solo descripción `generated` y fuentes `catalog`/`estate` → 0,6 (`generated_only_cap`; no es brecha porque la brecha es
  `< 0,6`). Partes de una pregunta compuesta sin resolver → `gap_threshold − 0,05` en todos los candidatos. Fallo de revisión sin
  corregir → `gap_threshold − 0,01`.
- **Brecha**: sin candidatos, con partes sin resolver o con el principal < `gap_threshold` (`discovery/engine.py:674`).

### Expansión es→en
`LEXICON` (`discovery/expansion.py:20`) traduce términos de negocio a nombres técnicos habituales ("cliente" → `client`,
`customer`; "mora" → `delinquency`, `atraso`). Se usa dos veces: cada concepto incluye los stems de sus traducciones, y la variante
de consulta junta todas las traducciones. Plurales en `-s`/`-es` se resuelven antes de buscar en el léxico.

### Índice y filtro de visibilidad
- Un documento por `asset_key` de tabla y uno por columna (unión de columnas entre ambientes; gana la descripción de mejor fuente).
- `access_ids` de cada documento = ids físicos de sus copias. El filtro (`access_ids & visible_ids`) se aplica **antes** de puntuar
  (`memory/memory_store.py:122`).
- Conocimiento: visible si todos sus activos vinculados lo son y, con ACL de origen, si el usuario pertenece a algún grupo.
  Confirmaciones: visibles si todos sus `asset_keys` lo son.
- El motor vuelve a filtrar en cada salida: ubicaciones, alternativas, reglas (todas sus `applies_to` visibles), linaje, FKs como
  término de cobertura (`discovery/engine.py:330`), caminos del grafo y vecinos.

### Guardas contra objetos inventados
- El reranker no puede añadir candidatos: ids desconocidos se descartan (`engine.apply_rerank`).
- El juez solo puede elegir un id de la lista ordenada (`flows/discover.py:274`).
- La narrativa no puede nombrar objetos del catálogo fuera de `candidates`, `alternatives` o `related` (`narrative_mentions_ok`).
  Una mención es una parte de una referencia con puntos, un identificador técnico (CamelCase, `_`, dígitos) o un nombre de tabla exacto.
- Texto generado con enlaces, HTML o correos no se muestra (`unsafe_generated_text`), en la narrativa y en el `why` del reranker.

### Modo determinista frente a modo con LLM
| Nodo | Sin LLM | Con LLM (si el rol existe) |
|---|---|---|
| intent | `RuleBasedIntentClassifier` (regex) | `LlmIntentClassifier` (`planner`); fallo → reglas |
| grade | variante léxica | `QueryExpander` (`fast`) — **no hay implementación conectada**: siempre léxica |
| rerank | relevancia por cobertura | `LlmReranker` (`planner`), salvo cascada |
| review | chequeos + `fix_candidate` | juez (`judge`) — **no hay implementación conectada** |
| respond | `TemplateNarrator` | `LlmNarrator` (`fast`); rechazo o fallo → plantilla |

`bootstrap.build_service_from_snapshot` (`src/discovery_data_agent/bootstrap.py:96`) solo conecta `intent_classifier`, `reranker` y `narrator`.

## Contratos y datos
- Entrada: `question`, `UserContext` (`user_id`, `groups`, `visible_ids`, `roles`), `history`, `client`. `visible_ids = None` lanza
  `ValueError` (`flows/discover.py:413`).
- Ids: físico `<env>:<server>.<db>.<schema>.<obj>`; lógico `asset_key` `<db>.<schema>.<obj>[.<col>]` (`src/discovery_data_agent/catalog/ids.py`).
- Salida: `AnswerEnvelope` (`src/discovery_data_agent/models/discovery.py:113`) con `status` `ok | needs_clarification | rejected | error`,
  `answer_text`, `assumptions`, `confidence`, `databases`, `tables_used`, `validation` (chequeos y veredicto del juez) y `discovery`.
- `Candidate`: rango, tipo, BD/esquema/tabla/columna, tipo de dato, `locations` (ambiente y alias, nunca host), `drift_warning`,
  descripción y fuente, reglas, responsables, linaje, evidencias, `why`, `confidence`, `copies`.
- Auditoría: `TraceRecord` con la pregunta, el envelope, la intención y los `StepRecord` (`src/discovery_data_agent/audit/recorder.py`).

## Configuración
`config/settings.yaml` (opcional; `load_settings`), bajo `discovery:`, `patterns:`, `features:` y `audit:`.

| Ajuste | Por defecto | Efecto |
|---|---|---|
| `k_columns`, `k_tables`, `k_knowledge`, `k_golden` | 50, 30, 30, 5 | Hits por búsqueda |
| `rerank_max` | 25 | Tamaño de la lista priorizada |
| `max_candidates`, `expand_top`, `max_alternatives` | 3, 5, 3 | Tamaño de la respuesta |
| `min_relevance` | 0,4 | Por debajo no responde la pregunta |
| `secondary_candidate_min` | 0,5 | Confianza mínima del 2.º y 3.º candidato |
| `gap_threshold`, `generated_only_cap` | 0,6, 0,6 | Umbral de brecha y tope de lo solo generado |
| `golden_similarity_min` | 0,85 | Similitud para que una confirmación cuente como evidencia |
| `weights` | 0,35/0,25/0,15/0,15/0,10 | Pesos de la confianza |
| `variant_weight`, `grade_min_coverage` | 0,8, 0,6 | Patrones D y C |
| `cascade_min_confidence`, `cascade_margin` | 0,85, 0,10 | Patrón E |
| `review_judge_band`, `ambiguous_margin` | (0,5, 0,75), 0,05 | Patrón B |
| `patterns.query_expansion/grade/review/cascade/graph` | todos `true` | Activan cada patrón |
| `features.ask_flow` | `false` | Fase 1a: preguntas de datos como descubrimiento. Con `true` (o `DISCOVERY_DATA_AGENT_ASK_FLOW=1` en la API) se calculan cifras agregadas |
| `audit.fail_open` | `false` | Solo desarrollo; qa/prod no arranca con `true` |

## Pruebas que lo cubren
- `tests/test_discover_flow_e2e.py`: casos de la propuesta, permisos, aclaración, auditoría fail-closed, stream, determinismo.
- `tests/test_graph_rag.py`: entidades entre BDs, caminos de unión con permisos, preguntas compuestas, pista de tabla, calificativos
  desconocidos, FK a tabla oculta que no mueve la confianza.
- `tests/test_core.py`: índice (nombre técnico primero, visibilidad, ACL, golden), intención, fórmula y tope de confianza, PII redactada.
- `tests/test_llm_guards.py`, `tests/test_prompt_injection.py`: reranker sin ids nuevos, narrativa ajena reemplazada, respaldo.
- `tests/test_application_discovery.py`: herramientas MCP sobre el mismo motor.
- Medición: `discovery-data-agent eval discovery` y `discovery-data-agent eval gate` (`tests/test_gate.py`).

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md).
- `QueryExpander` y `Reviewer` existen como puertos, pero nada los conecta: los patrones C y B corren solo en su parte determinista.
- Las estadísticas BM25 (`df`, `avgdl`) se calculan sobre todo el índice, incluidos objetos que el usuario no ve
  (`memory/memory_store.py:46`). La confianza puede variar ~0,006; no se muestra ningún nombre oculto.
- La similitud de una confirmación es léxica: `|pregunta ∩ plantilla| / |plantilla|` (`memory/memory_store.py:156`).
- El stemmer es de prefijo (6 caracteres): puede unir palabras distintas con el mismo prefijo.
- `unknown_qualifiers` es una marca global: si se descuenta un calificativo, todos los candidatos quedan bajo la brecha.
- Una entidad con un calificativo que sí nombra otra tabla no se descuenta y puede quedar sin candidatos (F22, límite conocido).
- El grafo y el índice viven en memoria del proceso; se reconstruyen en cada recarga del catálogo.
- `_timed` anota el modelo de `intent` aunque haya caído al respaldo por reglas (el error `fallback:` lo indica).
- La visibilidad es por objeto: no se modelan permisos a nivel de columna.

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Ajustar pesos, umbrales o tamaños | `config/settings.yaml` (modelo en `src/discovery_data_agent/config.py:71`) |
| Añadir un término es→en | `LEXICON` en `src/discovery_data_agent/discovery/expansion.py` |
| Cambiar qué palabras son de foco | `META_TERMS` en `src/discovery_data_agent/discovery/expansion.py` |
| Cambiar la fórmula de confianza o sus topes | `compute_confidence` en `src/discovery_data_agent/discovery/engine.py` |
| Cambiar cuándo se pide tabla o columna | `_kind_hint` (`deterministic.py`) y `entity_kind_hint` (`engine.py`) |
| Añadir un chequeo de revisión | `review_checks` y `fix_candidate` en `engine.py` |
| Cambiar el orden o los ciclos del grafo | `build_discover_graph` en `src/discovery_data_agent/flows/discover.py` |
| Cambiar la búsqueda | `InMemoryVectorStore` en `src/discovery_data_agent/memory/memory_store.py` |
| Cambiar la tokenización o los literales | `src/discovery_data_agent/memory/text.py` |
| Conectar un expansor o un juez con LLM | Implementar el puerto en `src/discovery_data_agent/llm/nodes.py` y pasarlo en `bootstrap.py` |
| Cambiar qué cuenta como objeto mencionado | `mentioned_objects` en `engine.py` |

Toda mejora se mide con `discovery-data-agent eval discovery` por tipo de pregunta antes de aceptarla.

## Specs y contradicciones
Specs: [F22](../../specs/comun/F22-discovery-flow.md), [F02](../../specs/comun/F02-semantic-memory.md),
[F03](../../specs/comun/F03-intent-router.md), [F19](../../specs/comun/F19-multi-db-discovery.md),
[F14](../../specs/comun/F14-identity.md), [F24](../../specs/comun/F24-knowledge-curation.md).

La spec contradice al código en:
- F22 paso 7: "las tarjetas se envían antes que la narrativa". El stream solo emite `step` (sin contenido) y un único `answer` al final.
- F22 §Resumen de dominio: dice que la exploración usa `estate_overview(domain)`. El código no la llama: solo omite columnas,
  sube el conocimiento a nivel de tabla y amplía a 5 candidatos.
- F22 paso 2: lista `kinds` sin `data_dictionary`; el código lo incluye.
- F22 paso 5: "las relaciones inferidas se marcan como tales". No hay relaciones inferidas en el código.
- `flows/discover.py` (docstring) describe el juez LLM y el expansor como activos; no están conectados (ver arriba).
