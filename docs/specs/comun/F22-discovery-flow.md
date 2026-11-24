# F22 — Discovery Flow (descubrimiento de activos de datos) · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Actualizado el 2026-11-17: preguntas por una entidad, de cruce,
> calificativos desconocidos y literales (§Qué tipo de activo se pide). Actualizado el 2026-11-23: chat para usuarios de negocio, LLM en
> tres pasos y cifras agregadas (§Chat de negocio, §Cifras agregadas; PRD §13, decisión 17).
>
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
| Ejecuta SQL contra datos | **No** (solo catálogo, conocimiento y, si aplica, permisos). Excepción: con las cifras agregadas activas (apagadas por defecto), solo `COUNT`, `COUNT DISTINCT`, `SUM` y `AVG` de plantilla fija, con el login del usuario (§Cifras agregadas) | Sí, con el login del usuario |
| Requiere login SQL del usuario | Sí, para calcular su visibilidad (F14); no consulta datos, salvo las cifras agregadas | Sí |
| Latencia objetivo | p50 < 5 s · p95 < 10 s | p50 < 12 s · p95 < 30 s (producción; el MVP admite p95 < 40 s, OP-01) |
| Salida | `discovery` (candidatos); con cifras, además `figure` y `flow: "ask"` | `data` + `sql` |

## Pasos (grafo de LangGraph determinista)
El grafo completo es `intent → retrieve ⇄ grade → rerank → expand ⇄ review → [compute] → respond → finalize`; `compute` (paso 7) solo corre con cifras activas.

1. **Intent** (F3): `intent = discovery`. Extrae `entities`, `business_context` (p. ej. "onboarding digital"), `asset_kind_hint`
   (columna, tabla, indicador, regla) y `environment_hint` ("producción" por defecto). Si la intención no trae `asset_kind_hint`,
   el nodo lo completa con el catálogo (§Qué tipo de activo se pide).
2. **Recuperación léxica** (BM25 en memoria, F2; sin embeddings en la fase 1a), filtrada por visibilidad (F14):
   - `search_columns(k=50)` y `search_tables(k=30)`;
   - `search_knowledge(kinds=[glossary, business_rule, document, annotation, etl], k=30)` (F23, F24);
   - `search_golden_discovery(k=5)`: preguntas parecidas ya confirmadas por usuarios o expertos (F24).
   Los hits de conocimiento suman puntos a los activos que mencionan (`linked_assets`).
   Si la pregunta nombra una entidad de negocio del grafo del patrimonio ([F19](F19-multi-db-discovery.md), herramienta `where_is`),
   se añaden su tabla canónica y sus copias en otras BDs (aristas `same_entity`).
3. **Agrupación por activo lógico**: los objetos físicos con el mismo `asset_key` en varios ambientes (F1) se agrupan en un candidato con
   `locations[]`. Si los `schema_hash` difieren entre ambientes, se añade el aviso "QA difiere de producción".
4. **Reranking con LLM**: el nodo `rerank` (rol `planner` de F16, el mismo modelo que `intent`; temperatura 0, salida estructurada) recibe hasta 25 candidatos en formato compacto
   (id, descripción, fuente de la descripción, reglas, evidencias) y devuelve un orden con `relevance` (0..1) y una justificación de una línea
   por candidato. **No puede añadir candidatos que no estén en la lista** (se valida el id).
5. **Expansión de contexto** para los 5 primeros:
   - relaciones por FK y relaciones entre BDs (grafo de F4 y F19, `find_join_path`; las inferidas se marcan como tales);
   - linaje ETL de entrada y salida a un salto (F23);
   - reglas de negocio vinculadas (F23);
   - responsable funcional y técnico (F24);
   - indicadores certificados de la capa semántica que usan el activo ([F21](F21-semantic-layer.md), `list_metrics`; fase 1b);
   - **alternativas**: columnas con la misma semántica (sinónimos, mismo término de glosario o mismo nombre normalizado) en otras tablas.
6. **Cálculo de confianza** (abajo).
7. **Cifras** (solo con `features.ask_flow` y un ejecutor de la sesión; §Cifras agregadas): el nodo `compute` arma el plan y ejecuta el agregado.
8. **Respuesta**: el nodo `respond` (rol `fast` de F16, que puede apuntar al mismo modelo; en streaming) redacta 1 a 4 frases que recomiendan el candidato principal y explican
   por qué, con un prompt para una persona de negocio; **no puede mencionar objetos que no estén en `candidates`, `alternatives` o `related`** (validación por id,
   `engine.narrative_mentions_ok`: compara contra todo el catálogo, no contra lo visible; DT-75). Si hay cifra, el texto lo arma el código y el modelo no interviene. Las tarjetas se
   envían antes que la narrativa, así que el usuario ve los candidatos sin esperar al texto.
9. **Brecha de conocimiento**: si ningún candidato llega a 0.6, `knowledge_gap = true` y se ofrece "Preguntar al responsable del dominio" (F24).
   Una brecha puede llevar candidatos: se muestran con su confianza baja (§Qué tipo de activo se pide).

> **Estado al 2026-11-17:**
> - Las tarjetas no salen antes que la narrativa: `DiscoverFlow.stream` (`src/discovery_data_agent/flows/discover.py`) emite un evento `step` por nodo y un único `answer` al final con el sobre completo (candidatos y texto juntos).
> - `estate_overview` existe como herramienta (`DiscoveryTools`, `/mcp`), pero el flujo no la llama: en `exploration` usa la misma recuperación y deja solo tablas (`src/discovery_data_agent/discovery/engine.py`).
> - Las relaciones (`related`) son `fk`, `same_entity`, `etl` y `view`; no hay relaciones inferidas marcadas como tales.
> - `search_knowledge` busca también en `data_dictionary`: la lista real es `glossary`, `business_rule`, `document`, `annotation`, `etl` y `data_dictionary`.
>
> Ver [brechas funcionales](../../wiki/brechas-funcionales.md).

## Qué tipo de activo se pide (2026-11-17)
Reglas deterministas. Las de `discovery/engine.py` y la del nodo `intent` del flujo se aplican con y sin LLM; las de cruce están en
el clasificador de intención sin LLM (`RuleBasedIntentClassifier` en `discovery/deterministic.py`): con LLM, el tipo lo da el
modelo (F3) y no se ha medido (HU-35).

- **Preguntas de cruce.** "¿Cómo relaciono / cruzo / uno A con B?" pide **tablas** y el camino para unirlas (`_JOIN`). "Cada uno
  de los clientes" no es un cruce. "¿Con qué campo (columna, llave) cruzo…?" pide la **columna** (`_ASKS_FIELD`), aunque hable de
  cruzar.
- **Preguntas por una entidad** (`engine.entity_kind_hint`). En "¿dónde están / se guardan / se encuentran / quedan los…?", si lo
  primero que se nombra en plural es el nombre de una tabla o vista **que el usuario puede ver**, se pide esa tabla ("¿dónde están
  los arrendamientos financieros de vehículos?"). No aplica si una columna visible se llama como las dos primeras palabras ("los
  pagos mínimos" → `PagoMinimo`: se pide el atributo) ni en preguntas compuestas ("las transacciones rechazadas y su motivo"). Lo
  aplica el nodo `intent` del flujo solo cuando la intención no trajo ya un tipo, y solo con `intent = discovery`.
- **Cuando se pide una tabla**:
  - los nombres y sinónimos de sus columnas también la describen, como términos débiles (pesan la mitad, igual que el texto generado
    por IA sin revisar);
  - **calificativos desconocidos**: el catálogo no guarda valores de datos (F1), así que no puede conocer calificativos que en
    realidad son valores ("de vehículos", "de San Salvador", "platino"). Un concepto de la pregunta que ningún activo recuperado
    nombra pesa 0,25 en la cobertura (`qualifier_weights`, `UNKNOWN_QUALIFIER_WEIGHT`): no sirve para elegir entre candidatos, pero
    sigue contando como parte de la pregunta sin cubrir. El primer concepto (la entidad pedida) nunca se descuenta: si nadie lo
    conoce, es una brecha;
  - si alguna tabla alcanza la relevancia mínima, sus columnas no compiten con ella (`shortlist` las descarta); si ninguna la
    alcanza, las columnas se conservan, por si la pregunta se clasificó mal;
  - una respuesta que descontó calificativos queda **siempre por debajo del umbral de brecha** (`Draft.unknown_qualifiers`,
    `compute_confidence`): el catálogo no sabe si "tarjetas de regalo" es un valor de la tabla de tarjetas o un dato que el banco no
    tiene. Se muestra la tabla con confianza baja, `knowledge_gap = true` y la oferta de preguntar al responsable.
- **Literales.** Los valores concretos que trae la pregunta no cuentan como conceptos que un activo deba cubrir: "el DUI del
  cliente 01234567-8" pregunta por el DUI del cliente. Los quita `discovery_data_agent.memory.text.strip_literals(question, known)`, la misma
  función que usa la plantilla de las confirmaciones (F24, F17 clase D4): tras normalizar con NFKC, toda palabra con algún dígito
  o con arroba es un literal, salvo el vocabulario conocido. Para medir la cobertura, el vocabulario son los nombres con dígitos
  de lo que el usuario ve (`Catalog.names_with_digits(visible_ids)`, p. ej. `Ultimos4`): un nombre de un objeto oculto no cuenta.
- **Permisos en los términos de un activo** (revisión de seguridad del 2026-11-17). El nombre de una tabla referenciada por llave
  foránea solo cuenta como término de un activo si el usuario también ve esa tabla (`_asset_terms_split`, `_asset_terms`). Antes,
  quien no la veía podía confirmar su nombre por la confianza de la respuesta. Prueba:
  `tests/test_graph_rag.py::test_el_nombre_de_una_tabla_que_no_se_ve_no_mueve_la_confianza`. Queda una deuda: las estadísticas
  BM25 son globales, así que la confianza de un mismo usuario varía hasta ~0,006 según existan objetos que no ve; no aparece
  ningún nombre oculto ([calidad bancaria §5](../../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto)).

Limitación conocida: una entidad con un calificativo que **sí** conoce otra tabla no se descuenta, y la pregunta puede quedar sin
candidatos. Son los dos fallos que quedan en los sets de evaluación del equipo: "¿Dónde están los dispositivos Android
bloqueados?" (B14, BancosSQL) y "¿Dónde están los dispositivos iOS de clientes premium?" (eng-06, VBank). Estas reglas se
ajustaron y midieron con preguntas escritas por el equipo; falta el set real (HU-33). Pruebas: `tests/test_graph_rag.py`
(`test_un_plural_que_nombra_una_tabla_pide_la_tabla`, `test_una_pregunta_de_cruce_pide_tablas`,
`test_un_calificativo_que_nadie_conoce_pesa_menos_pero_la_entidad_no`,
`test_una_entidad_con_calificativos_desconocidos_se_responde_con_confianza_baja`,
`test_lo_que_el_banco_no_tiene_nunca_sale_como_respuesta_segura`).

Sin `config/models.yaml`, o con el tope diario de tokens agotado, los pasos 1, 4 y 8 corren en **modo determinista** (sin LLM) y el
flow sigue respondiendo. Las guardas sobre el texto generado y la compuerta `discovery-data-agent eval gate` están en [calidad bancaria](../../calidad-bancaria.md).

## Chat de negocio (2026-11-23)
Reglas del DiscoverFlow para quien escribe como en un chat; aplican con y sin LLM salvo donde se dice.
- **Preguntas sobre el asistente y cortesía.** El nodo `intent` las detecta antes de buscar (`discovery/assistant.py::topic_of`, intención
  `assistant`) y responde con un texto fijo. El sobre trae `status: ok` y `discovery: null`. El tema `databases`
  lista solo las bases visibles para el usuario. La web no muestra "Cómo lo obtuve" cuando no hay `discovery`.
- **Seguimientos.** `deterministic.contextualize` completa un mensaje corto o con anáfora con la pregunta anterior del historial (hasta tres
  turnos). El paso `intent` lo anota como `seguimiento:<n>` en la traza.
- **Lo que no es parte de lo pedido.** Palabras de relleno (`expansion.QUESTION_FILLER`) y términos de cálculo y de periodo
  (`ANALYSIS_TERMS`, salvo los que forman parte de un nombre del catálogo: `engine.kept_analysis_terms`) no cuentan como conceptos sin
  cubrir. `LEXICON` (`discovery/expansion.py`) trae sinónimos bancarios.
- **Aclaración no bloqueante por áreas.** Si el mismo dato existe en varias áreas (`engine.area_options`, hasta cuatro opciones), se
  responde con el candidato principal y además se ofrece precisar; la web muestra las opciones también cuando hay respuesta. Solo se
  usan áreas de lo que el usuario ve; la guarda de las opciones no consulta el catálogo (F14).
- **Escrituras.** La orden de modificar datos se rechaza mirando solo la pregunta actual (`deterministic.is_write_request`), no el historial.
- **LLM, rol `fast`, además de la narrativa.** (a) `LlmQueryExpander`: reformula cuando la búsqueda cubre poco (patrón C de la medición).
  **Reinterpretación de preguntas de reporte:** si hay modelo y la reformulación cambió algo, su primera variante pasa a ser lo que se
  mide contra el catálogo (`flows/discover.py::grade_node`: sustituye los conceptos de la búsqueda) y el sobre añade el supuesto
  "Entendí que necesitas: «…»". No aplica a preguntas compuestas, de cruce ni de cifras, que ya dicen qué datos quieren. El modelo solo
  redacta la búsqueda; qué activos existen y cuáles ve el usuario lo sigue decidiendo el catálogo. Sin modelo, la reformulación es
  la léxica (`lexicon_variant`) y no cambia los conceptos medidos.
  (b) `LlmGuide`: solo corre sin candidatos; reconoce una pregunta sobre el asistente entre los temas fijos o propone una aclaración en
  lenguaje de negocio, con las guardas `engine.looks_technical` y `engine.unsafe_generated_text`. **Respuesta sin candidatos con
  aclaración:** ya no es solo una pregunta. El sobre sale con `status: ok`, `discovery` con la brecha (sin candidatos, confianza 0) y
  `clarification` (hasta cuatro opciones), y el texto dice que no se encontró el dato y a continuación pregunta cómo precisarlo
  (`finalize_node`, rama `state.get("clarification") and not candidates`): el dato puede no existir en el banco, así que la aclaración
  acompaña a la respuesta en vez de sustituirla. Al modelo no le llegan los literales de la
  pregunta ni del historial (`strip_literals`). El orden de los candidatos sigue siendo determinista; el rol `planner` (intención y
  reordenamiento con LLM) sigue desaconsejado por la medición.
- **Medición.** `tests/fixtures/bancos/eval/chat.yaml`, 67 casos de usuarios de negocio, con `history`, `expect_assistant` y `expect_rejected`
  (`EvalCase`). Hit@1 97,8 % y Hit@3 100 % el 2026-11-23, con un fallo abierto (L09) ([plan §2](../../PLAN-desarrollo.md#2-resultados-medidos)).
  Preguntas de reporte (25, sin glosario): determinista 28 % Hit@1 y 32 % Hit@3; con `nemotron-3.5-bolt-e4b` 52 % y 56 %; con Claude
  Sonnet 5.5 68 % y 80 % ([F16](F16-llm-providers.md#perfiles-elegibles-en-pantalla-2026-11-23)). Con el perfil de Claude, el set de chat sigue en
  97,8 % y 100 %, y el set base en 98,0 % y 98,0 %, con brechas correctas al 100 % en ambos.
  Pruebas: `tests/test_chat_conversacional.py`.

## Cifras agregadas (primer corte del AskFlow, 2026-11-23)
**Apagadas por defecto.** Decisión 17 del PRD §13: se adelanta un subconjunto acotado de la fase 1b para que el chat responda "¿cuántos…?" y
"¿cuál es el saldo total…?" con el número. Se activan con `features.ask_flow` o `DISCOVERY_DATA_AGENT_ASK_FLOW=1`; sin ellas, una pregunta de cifras se
responde con la tabla donde está la información (F3). En la CLI: `discovery-data-agent discover "<pregunta>" --root <dir> --figures config/databases.local.yaml`.
- **Qué calcula** (`src/discovery_data_agent/discovery/figures.py`, `src/discovery_data_agent/models/figures.py`): `COUNT`, `COUNT DISTINCT`, `SUM` y `AVG` sobre una tabla,
  con desglose opcional por una columna de categoría de hasta 25 valores distintos, que se comprueba antes con otra consulta (`is_category`: nunca medidas ni nombres de persona). Si la categoría pedida ("por segmento", "por tipo de crédito", "por marca") no está en la tabla principal, `figures._related_category` la busca en una tabla a la que apunta una llave foránea de una sola columna, visible para el usuario y de la misma base, servidor y ambiente, y hace **una** unión por esa llave, con las mismas reglas.
- **Cómo.** SQL de plantilla fija con identificadores del catálogo que el usuario ve, entre corchetes; nada de lo que escribe el usuario ni de lo que produce un
  modelo llega al SQL. Nunca se usan columnas `pii`. Se ejecuta con la credencial de la sesión (`AgentRuntime.figure_executor`), en una
  transacción que siempre se revierte, `SET LOCK_TIMEOUT 5000`, lectura sin bloqueos, `OPTION (MAXDOP 1)`, como máximo 50 filas, tope de 15 s y dos cifras a la vez. El ejecutor valida el SQL contra la plantilla (`figures.ALLOWED_SQL`, `check_sql`). SQL Server decide si el
  usuario puede leer la tabla; si niega el permiso o falla, se responde sin cifra y sin el mensaje de error.
- **El número no pasa por el LLM.** El texto (`figures.answer_text`) lo arma el código. El sobre lleva `flow: "ask"` y `figure` (el SQL que se ejecutó
  y los grupos); la web lo muestra en una tarjeta (`web/src/components/chat/figure-card.tsx`).
- **Supresión de grupos pequeños.** Un total o un grupo calculado sobre menos de 10 registros no se muestra (`figures.MIN_ROWS`, `_safe_groups`), con supresión complementaria: si se oculta un grupo, se oculta también el visible más pequeño para que no se deduzca por resta; la nota dice cuántos se ocultaron.
- **No calcula, y lo dice** (en `assumptions`): con periodo, con filtro por valor, con una condición que combina tablas ("clientes con préstamo y también tarjeta"), con cruce entre bases o sistemas, con una unión de más de un salto, con una medida no numérica, con empate entre datos de
  tablas distintas o si no identifica qué contar. Tampoco filtra por valor: un adjetivo de estado ("activos") desglosa por la columna de estado.
- **Auditoría.** El paso `compute` queda en los pasos de la traza con la operación, el número de grupos y la duración, sin el SQL ni valores. Además, cada consulta se audita **antes** de ejecutarse con el evento `figure_query` (quién, dónde y qué consulta, sin valores); si la auditoría falla, no se ejecuta y se responde sin cifra. La fila de la pregunta guarda `flow: ask`. El ambiente se muestra con la cifra.
- **Verificado** contra el SQL Server local con datos ficticios: 1 790 clientes con préstamo de 3 000; saldo de cartera 25 507 803,93; promedio
  desembolsado 14 566,69; desglose por una tabla relacionada: saldo de cartera por segmento del cliente (Preferente 12 090 634,54; Emergente
  9 847 477,15; Masivo 1 924 810,63; Premium 1 644 881,61), préstamos por tipo de crédito (Personal 1 438; Vehículo 376; Hipotecario 368; PYME 258;
  Garantizado 217; Educativo 123) y tarjetas por marca (Visa 2 180; Mastercard 1 078), iguales a la consulta directa. Pruebas: `tests/test_cifras_agregadas.py`, `api/tests/test_cifras.py`.
- **Revisión de seguridad (terminó el 2026-11-23).** No encontró inyección SQL ni fugas de permisos (F14); dio dos bloqueantes, la supresión de grupos pequeños y la auditoría previa, ambos corregidos el mismo día. Un servidor de producción exige `figures: true` en el inventario y `--figures` se niega con servidores de producción (`api/tests/test_cifras.py::test_politica_de_cifras_por_servidor`).
- **Pendiente.** DT-78, DT-79 y DT-80; aceptarlo con Seguridad de la Información y revisar los criterios D1–D7
  de OP-01 antes de activarlo en el piloto. No se midió con preguntas de usuarios reales ni con Bedrock. Sin periodo, filtros por valor, condiciones entre tablas ni cruces (DT-76, reducida: el desglose con una unión sí se calcula).

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
| `retrieval_score_norm` | Score de recuperación (BM25) normalizado al mejor hit de la consulta |
| `evidence_strength` | `human` 1.0 · `data_dictionary` 0.9 · `ms_description` 0.8 · `document` 0.6 · `generated` 0.3 |
| `confirmation_score` | 1.0 si un experto confirmó este activo para una pregunta similar (≥ 0.85); 0.7 si lo confirmaron ≥ 2 usuarios; 0 en otro caso |
| `source_agreement` | Fuentes independientes que apuntan al activo (catálogo, diccionario, documento, ETL, golden), normalizado a 3 |

- Tope de 0.6 si la única evidencia es `generated`.
- Tope justo por debajo del umbral de brecha (0.59 con el umbral por defecto de 0.6) si la respuesta descontó calificativos que el
  catálogo no conoce (§Qué tipo de activo se pide).
- Se muestra en porcentaje (p. ej. "92 %"). La calibración se mide en F25.

## Herramientas
`discover(question)`, `get_asset(asset_key)`, `get_related(asset_key, depth=1)`, `get_lineage(asset_key, direction, depth)`,
`list_business_rules(asset_key|domain)`, `find_alternatives(asset_key)`. Todas reciben la identidad desde el contexto autenticado (F14).

## Criterios de aceptación
1. Con el catálogo de prueba `VBank_ING` (fixture de la propuesta), "Necesito encontrar el identificador único del cliente utilizado en procesos
   de onboarding digital" devuelve `ClientCode`, `LegalClientId` y `UserId` entre los 3 primeros (candidatos + alternativas), con base de datos,
   tabla, ambiente, servidor, descripción y confianza.
2. Cada candidato trae los 8 elementos de la propuesta: tabla, campo, base de datos, ambiente, servidor, descripción, confianza y relaciones.
3. Con las cifras apagadas (el valor por defecto), el DiscoverFlow no consulta tablas de datos: el login del usuario solo se usa para
   calcular `visible_ids` (test: ninguna consulta de datos queda en la traza, `tests/test_cifras_agregadas.py::test_apagado_no_llama_al_ejecutor_y_avisa`).
   Con las cifras activas solo se ejecutan agregados de plantilla fija, con el login del usuario, y no se guardan valores.
4. Un usuario sin permiso sobre `VBank_ING` no recibe ningún candidato, ubicación, relación, regla ni evidencia de esa BD; recibe
   "no encontré datos disponibles para ti sobre …" sin mención a sus tablas (F14).
5. Ningún objeto mencionado en la narrativa está fuera de `candidates`, `alternatives` o `related` (test sobre el set de evaluación).
6. Hit@3 ≥ 85 % y Hit@1 ≥ 65 % en el set de evaluación de descubrimiento (F25).
7. p95 < 10 s en el set de evaluación.

Estado de los criterios 6 y 7 (2026-11-17, modo determinista, sets escritos por el equipo): BancosSQL, 58 casos, Hit@1 y Hit@3
98,0 %, p95 27 ms; VBank, 31 casos, 96,2 %, p95 8 ms. Faltan el set de preguntas reales (HU-33) y la medición con Bedrock (HU-35).
