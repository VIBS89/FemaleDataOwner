# Brechas funcionales

Actualizado el 2026-11-17.

Esta página compara lo que prometen el PRD y las specs con lo que hace el código. Cada estado se comprobó en el código o en
una prueba, no en los documentos de estado. Las rutas son relativas a la raíz del repositorio. Las líneas citadas son las del
árbol de trabajo del 2026-11-17, que incluye cambios sin commit (por ejemplo `GET /admin/manual`).

**Resumen.** Hoy una persona puede hacer de punta a punta todo el ciclo del descubrimiento, en desarrollo con `docker compose`.
Inicia sesión con su login SQL. Pregunta en el chat y recibe candidatos con base de datos, ambiente, servidor, descripción y su
fuente, reglas, responsables, linaje de vistas y confianza. Solo ve lo que su login puede leer. Puede confirmar o rechazar un
candidato y escalar la duda al responsable. El responsable cura descripciones, reglas y diccionarios CSV. El administrador
gestiona el inventario, los responsables, la construcción del catálogo, la auditoría y las métricas. Todo queda en la BD
`ConverData` y la auditoría es fail-closed. Claude y otros agentes pueden usar las mismas herramientas por MCP.

Las brechas que más pesan para el piloto:

1. Bedrock no se ha probado nunca. Todas las cifras de calidad se midieron sin LLM.
2. No hay preguntas reales. Los 89 casos de descubrimiento y las 25 preguntas de reporte los escribió el equipo.
3. No hay instalación en Windows Server. No existe `deploy/`. El build nocturno, la purga y la regresión no están programados.
4. Faltan las fuentes de conocimiento que más mueven las preguntas de reporte: documentos con redacción de datos personales, Excel y linaje de SSIS y de los jobs.
5. No hay informe del piloto: falta `converdata metrics report`, faltan las vistas SQL, el MRR, la línea base y el reporte de brechas por dominio.

Páginas relacionadas: [deuda técnica](deuda-tecnica.md) (lo que hay que arreglar en lo construido), [hoja de ruta on-premise](hoja-de-ruta-on-premise.md) y [hoja de ruta cloud](hoja-de-ruta-cloud.md) (en qué orden se cierran estas brechas) y [arquitectura](../architecture/README.md).

## Leyenda de estados

| Estado | Significa |
|---|---|
| **Construido** | Existe en el código y tiene prueba automática. Puede tener límites conocidos, que se anotan |
| **Parcial** | Una parte existe y otra parte de lo prometido no |
| **No construido** | No hay código |
| **Fuera de alcance (decisión)** | No se construye en esta versión por una decisión registrada: fase 1b, despliegue en AWS posterior al piloto o una pieza retirada en el PRD §13 |
| **Depende del banco** | El código puede estar listo, pero cerrarlo exige algo del banco o de terceros: cuenta de AWS, preguntas, documentos, gMSA o AD |

## Mapa por capacidad de usuario

| Capacidad | Estado | Qué funciona hoy (con evidencia) | Qué falta | Spec/HU |
|---|---|---|---|---|
| Preguntar y recibir candidatos | Construido | `POST /discover` y `/discover/stream` (`api/converdata_api/main.py:591`, `:605`). Grafo `intent → retrieve ⇄ grade → rerank → expand ⇄ review → respond → finalize` (`src/converdata/flows/discover.py:376-394`). Tarjetas con "Es este", "No es", "Ver relacionadas" y "Ver ficha" (`web/src/components/chat/candidate-card.tsx:184-206`). Botón "Preguntar al responsable" cuando hay brecha (`web/src/components/chat/assistant-message.tsx:114`, `:262`). Pruebas: `tests/test_discover_flow_e2e.py` (8 elementos por candidato, relaciones entre BDs, drift, resumen de dominio, aclaración, fuera de alcance, streaming) | Medir con Bedrock (HU-35) y con preguntas reales (HU-33). Dos fallos abiertos en los sets del equipo (B14, eng-06). Sin opción "El correcto es…" | F3, F22, HU-14, HU-17 |
| Catálogo | Construido | `GET /catalog/databases`, `/catalog/objects`, `/catalog/object`, filtradas por `visible_ids` (`main.py:872-911`). Vista `web/src/app/(app)/catalogo/page.tsx`. Prueba: `api/tests/test_api.py::test_catalog_explorer` | Nada para la fase 1a | F12, F14 |
| Fichas y linaje | Parcial | `GET /assets/{asset_key}` con FKs visibles, reglas, responsables, referencias y copias por ambiente (`main.py:913-949`). Linaje de vistas en el build (`src/converdata/builder/catalog_builder.py:195`), visible en la tarjeta del candidato (`candidate-card.tsx:145`) y en la herramienta MCP `get_lineage`. Aviso de drift entre ambientes (`src/converdata/discovery/engine.py:707`). Prueba: `api/tests/test_security.py::test_la_ficha_de_un_activo_no_revela_tablas_ocultas_por_sus_llaves_foraneas` | La ficha (`/assets`) no devuelve linaje ni documentos vinculados, aunque F12 lo promete. No hay linaje de SSIS, de los jobs ni de `INSERT…SELECT` en SPs (HU-27) | F12, F19, F23, RF-06, RF-10 |
| Curación: dudas escaladas | Construido | `POST /curation/requests`, bandeja y respuesta (`main.py:641`, `:686`, `:713`). Las dudas se guardan en `curation.request` (`db/converdata/002_curacion.sql:32`). La respuesta entra al índice como confirmación del responsable. Webhook con solo el dominio y el enlace (`api/converdata_api/curation.py:87`). Vista Solicitudes (`web/src/app/(app)/solicitudes/page.tsx`). Prueba: `api/tests/test_catalog_db.py::test_una_duda_escalada_vive_en_la_bd_y_su_respuesta_entra_al_indice` | No hay prueba automática que verifique el envío del webhook (sin verificar). Canal sin confirmar (S12). El usuario no recibe aviso; lo ve en Solicitudes | F24, HU-30 |
| Curación: descripciones e historial | Construido | `GET /curation/review` por demanda, `PUT /curation/description` con detector de datos personales, `GET /curation/history` desde las tablas temporales (`main.py:741-800`). Pruebas: `api/tests/test_catalog_db.py::test_el_historial_de_descripciones_se_ve_en_curacion`, `api/tests/test_security.py::test_las_ediciones_de_curacion_no_aceptan_datos_personales` | La cola de revisión y la edición no filtran por `visible_ids` dentro del dominio (pregunta abierta 7). No hay `conflict: true` entre fuentes. Falta el comando `converdata catalog review` | F24, HU-31 |
| Curación: reglas | Construido | `GET`/`PUT`/`DELETE /curation/rules` (`main.py:830-859`), una fila por regla en `knowledge.business_rule`. Pruebas: `api/tests/test_api.py::test_reglas_de_negocio_gestionadas_por_el_steward`, `api/tests/test_catalog_db.py::test_una_regla_curada_y_una_confirmacion_llegan_a_la_bd` | El Builder no sugiere reglas (filtros, `CASE`, `CHECK`, documentos) | F23, HU-28 |
| Curación: diccionario | Parcial | `POST /curation/dictionary` con CSV, sin pisar lo humano (`main.py:803`). Prueba: `api/tests/test_api.py::test_ingesta_de_diccionario_no_pisa_lo_humano_y_es_idempotente` | Excel (no hay dependencia para leerlo). Conector `DictionaryConnector` con `config/knowledge.yaml`. Prueba con 200 columnas reales | F23, HU-25 |
| Votos y aprendizaje | Construido | `POST /discover/feedback` (`main.py:631`), regla de votos `resolve_golden`, plantilla sin literales. Pruebas: `api/tests/test_catalog_db.py::test_el_voto_del_responsable_rige_en_la_siguiente_busqueda`, `api/tests/test_marked_literals.py` | La plantilla no detecta nombres de personas. Cada voto recarga todo el índice | F24, HU-15, HU-29 |
| Métricas | Parcial | `GET /admin/metrics` desde la auditoría (BD o archivos): preguntas, usuarios activos, confirmaciones, tiempo hasta "Es este", escalamientos, tasa de brechas y latencia (`api/converdata_api/curation.py:127`). Vista `web/src/app/(app)/metricas/page.tsx`. `GET /health/metrics` (`main.py:450`) | `converdata metrics report` (CSV y HTML). Vistas SQL del esquema `audit` (no existen en `db/converdata/`). Hit@k y MRR en el informe. Brechas abiertas y cerradas por dominio. Golden por semana. % de activos con descripción revisada. Línea base | F25, HU-23, HU-32 |
| Administración | Construido | Inventario, responsables, build bajo demanda, auditoría, verificación, sesiones y manual (`main.py:952-1064`). Vista con pestañas (`web/src/app/(app)/admin/page.tsx:64-87`). Pruebas: `api/tests/test_security.py::test_el_admin_revoca_las_sesiones_de_un_usuario`, `api/tests/test_api.py::test_los_responsables_se_administran_y_cada_cambio_queda_auditado` | La web no tiene pantalla para las sesiones ni para `GET /admin/audit/verify`: solo existen en la API. Los responsables de negocio y técnico de cada dominio (`curation.owners`) solo llegan publicando el YAML; no se editan desde la web | F12, OP-04 |
| MCP | Construido | 10 herramientas de lectura (`src/converdata/integration/mcp/server.py:94-157`), en `/mcp` con `Bearer` y por stdio (`converdata mcp serve`). Pruebas: `api/tests/test_mcp.py`, `tests/test_mcp_server.py::test_http_publica_solo_herramientas_de_lectura`, `tests/test_mcp_stdio.py` | Probar `/mcp` a través de IIS (HU-37). La prueba de literales marcados no pasa por el cliente MCP | F12, HU-16, HU-42 |
| Inicio de sesión y roles | Parcial | Login SQL validado contra cada servidor, SessionVault cifrado en memoria, bloqueo tras 5 fallos, 5 sesiones por usuario, código de instalación (`main.py:472-565`, `api/converdata_api/vault.py:45`). `data_admin` por lista y `steward` por login y dominio, solo si el login se validó en un servidor de producción. Pruebas: `api/tests/test_security.py` (bloqueo, caducidad, tope de sesiones, `test_un_login_validado_solo_en_desarrollo_no_hereda_roles_por_su_nombre`) | Grupos de AD por LDAP y `curation.user_directory` (no existe; HU-13). Un login distinto por servidor: el código usa una sola credencial para todos los servidores elegidos y no tiene ruta para añadir otra después. gMSA y DPAPI (HU-38). Depende del banco | F14, OP-03, HU-10 a HU-13 |
| Consulta de datos (fase 1b) | Fuera de alcance (decisión) | Nada. No hay `/ask`, AskFlow, validador ni ejecutor; no hay `sqlglot` en las dependencias. Una pregunta de cifras se responde como descubrimiento (`flows/discover.py:150`; prueba `tests/test_discover_flow_e2e.py::test_pregunta_de_datos_sin_askflow_indica_donde_estan`) | Todo F4–F10 | F4–F10, RF-40 |
| Análisis (F20) | Fuera de alcance (decisión) | Nada | Todo F20 | F20, RF-42 |
| Capa semántica (F21) | Fuera de alcance (decisión) | Nada. No existe el esquema `semantic` | Todo F21 | F21, RF-41 |

## Spec por spec

| Spec | Título | Estado | Evidencia en código | Brecha concreta |
|---|---|---|---|---|
| F01 | Catalog Builder | Parcial | `converdata catalog build`/`publish`/`export` (`src/converdata/cli.py:139-157`). Flujo `extract → enrich → relate → write` (`src/converdata/flows/catalog_build.py:193-201`). Reutiliza objetos con el mismo `schema_hash` (`builder/catalog_builder.py:133`). Rechaza YAML con valores (`src/converdata/models/catalog.py:13`). Pruebas: `tests/test_catalog_build.py` (refresco que no pisa lo humano, servidor caído, BD `ConverData` excluida) | No hay `catalog refresh` ni `catalog review`, ni `--database` ni `--no-llm`. No hay muestras en memoria (`get_sample_rows`). No resuelve `sys.synonyms`. CA1 se probó con BancosSQL, no con AdventureWorks |
| F02 | Memoria de búsqueda (`VectorStore`) | Construido | `InMemoryVectorStore` BM25 con filtro de permisos previo (`src/converdata/memory/memory_store.py`). Rol `embed` ignorado (`tests/test_llm_gateway.py::test_un_models_yaml_con_el_rol_embed_se_carga_ignorandolo`) | Colección `golden_sql` (fase 1b). El Builder no sugiere entradas de glosario. El título "Memoria semántica" no describe un índice léxico |
| F03 | Intent & Router | Parcial | Intenciones, aclaración y fuera de alcance (`src/converdata/discovery/deterministic.py:46-89`, `flows/discover.py:146-151`). `features.ask_flow: false` (`src/converdata/config.py:116`) | Sin LLM no se rellena `time_range` (CA1). No se midieron CA4 (30 preguntas) ni CA6 (40 preguntas mixtas). El enrutado de `data_query` al AskFlow es de la fase 1b |
| F04 | Schema Linking | Fuera de alcance (decisión) | Ninguna | Fase 1b |
| F05 | Value Resolution | Fuera de alcance (decisión) | Ninguna | Fase 1b (el anexo A del PRD la marca 1b; la spec no lo dice en su cabecera) |
| F06 | Planner T-SQL / SP | Fuera de alcance (decisión) | Ninguna | Fase 1b |
| F07 | Validator | Fuera de alcance (decisión) | Ninguna; no hay `sqlglot` en `requirements/runtime.lock` | Fase 1b |
| F08 | Executor | Fuera de alcance (decisión) | Ninguna | Fase 1b |
| F09 | Result Verifier | Fuera de alcance (decisión) | Ninguna. El flujo de descubrimiento tiene un puerto `Reviewer` para un juez (`src/converdata/discovery/ports.py:51`) sin implementación | Fase 1b |
| F10 | Analyst | Fuera de alcance (decisión) | Ninguna | Fase 1b |
| F11 | Auditoría | Construido | `SqlServerAuditSink` (`src/converdata/audit/sqlserver.py`), tablas `audit.*` y `audit.usp_purge` (`db/converdata/001_esquemas.sql:200-280`). Pruebas: `api/tests/test_audit_db.py` (fail-closed, sin contraseñas), `tests/test_discover_flow_e2e.py::test_auditoria_un_registro_por_pregunta` | Faltan `prompt_tokens`, `completion_tokens`, `user_group`, `rewritten_question`. La purga no está programada. La fecha `ts` la fija quien inserta |
| F12 | Interfaces (API, web, MCP) | Construido | Rutas en `api/converdata_api/main.py:446-1073`. Web en `web/src/app/(app)/`. MCP en `src/converdata/integration/mcp/server.py`. Pruebas: `api/tests/test_security.py::test_toda_ruta_no_publica_exige_sesion`, `api/tests/test_mcp.py` | `/assets` no devuelve linaje ni documentos. El cuerpo del login no es el de la spec. Rutas y herramientas de la fase 1b (`/ask`, `run_select`…) fuera de alcance |
| F13 | Arquitectura documentada | Construido | Cuatro diagramas en `docs/architecture/*.html` con su `*.archify.json` | El texto de la spec está desactualizado (ver la última sección) |
| F14 | Identidad y permisos heredados | Parcial | `AgentRuntime.visible_ids` releída cada 15 min (`api/converdata_api/runtime.py:272`). Pruebas: `api/tests/test_security.py::test_barrido_de_la_api_sin_fugas_para_un_usuario_restringido`, `test_la_visibilidad_se_vuelve_a_leer_de_sql_server`; suite `permisos` de `converdata eval gate` | Grupos de AD y `curation.user_directory` (HU-13). Credencial distinta por servidor. `DENY` por columna. CA3 (`run_select`) es de la fase 1b |
| F16 | Proveedores de LLM | Parcial | Gateway con `bedrock`, `nvidia_nim` y `ollama`, residencia, respaldo y circuit breaker (`src/converdata/llm/factory.py:128`, `gateway.py`). `converdata llm smoke` (`cli.py:102`). Pruebas: `tests/test_llm_gateway.py` | Bedrock nunca se ejecutó (HU-35, depende del banco). Contadores de tokens por paso en la auditoría |
| F17 | Residencia de datos | Parcial | Prueba de 100 literales marcados en archivos y en SQL Server (`api/tests/test_marked_literals.py`). Guarda `data_mode: real` (`tests/test_llm_gateway.py::test_guarda_de_residencia_con_datos_reales`) | No cubre el cliente MCP, `/discover/stream`, el Visor de eventos, `TEMP` de las gMSA, IIS ni los volcados. No detecta nombres de personas. CA2 (invocation logging de Bedrock) depende del banco |
| F18 | `converdata-discovery` | Parcial | Biblioteca con consultas fijas a `sys.databases`, `sys.objects`, `sys.columns` con `MS_Description`, PK, FK, filas, sensibilidad, dependencias y parámetros (`src/converdata/metadata/sqlserver.py:22-87`) | No es un servidor MCP. Faltan Query Store, perfiles, sketches MinHash, muestras, SSISDB, msdb, linked servers y sinónimos. No hay prueba de licencias (CA1) |
| F19 | Grafo del patrimonio entre BDs | Parcial | Entidades por solapamiento de nombres (`builder/catalog_builder.py:159`), linaje de vistas (`:195`), grafo y caminos de unión en memoria (`src/converdata/graph/estate.py:37`, `:116`). MCP `where_is`, `estate_overview`, `find_join_path`. Prueba: `tests/test_discover_flow_e2e.py::test_descubre_relaciones_entre_bases_de_datos` | Query Store, MinHash, tipos semánticos de columna, popularidad, `converdata estate review`. El plan federado es de la fase 1b |
| F20 | Motor de análisis | Fuera de alcance (decisión) | Ninguna | Fase 1b; on-premise sin código libre |
| F21 | Capa semántica | Fuera de alcance (decisión) | Ninguna; no hay esquema `semantic` | Fase 1b |
| F22 | DiscoverFlow | Construido | `src/converdata/flows/discover.py`, `src/converdata/discovery/engine.py`. Pruebas: `tests/test_discover_flow_e2e.py`, `tests/test_graph_rag.py`. Medido en modo determinista: Hit@1 98,0 % (BancosSQL, 58 casos) y 96,2 % (VBank, 31 casos) | Sin medir con LLM real. Fallos B14 y eng-06. Los indicadores certificados (paso 5) son de la fase 1b |
| F23 | Fuentes de conocimiento | Parcial | Diccionario CSV (`main.py:803`), reglas (`main.py:830-859`), linaje de vistas, carga de conocimiento para evaluar (`eval discovery --knowledge`, `cli.py:115`) | Excel, documentos (DOCX, PDF…), Presidio, SSIS, jobs del Agente, `KnowledgeConnector`, `MetadataConnector`, conflictos, reglas sugeridas, `converdata knowledge ingest`/`report` |
| F24 | Curación y captura | Parcial | Votos, golden, escalamiento, cola de revisión, historial, responsables (`main.py:631-859`, `:995-1007`). Pruebas: `api/tests/test_catalog_db.py`, `api/tests/test_security.py` | Opción "El correcto es…" (el modelo solo acepta `confirm` y `reject`, `main.py:96`). Aviso al usuario que preguntó. `converdata knowledge gaps`. Conflictos. Pregunta abierta 7 |
| F25 | Métricas de éxito | Parcial | `GET /admin/metrics` (`curation.py:127`). `eval discovery` con Hit@k, calibración ≥ 0,8, brechas, fugas, latencia y `--min-hit3` (`src/converdata/evaluation/discovery_eval.py:96-117`, `cli.py:117`). `eval gate` con 7 suites (`evaluation/gate.py:42`), en la CI (`.github/workflows/calidad.yml`) | `converdata metrics report`. MRR (no se calcula). Línea base (HU-40). Métricas por perfil (`user_group`). Golden por semana y % de activos revisados |
| OP-01 | Despliegue on-premise | Parcial | Todo corre con `docker-compose.yml`, `api/Dockerfile` y `web/Dockerfile` | Windows Server, IIS y HttpPlatformHandler no existen. La imagen con los bloqueos no se construyó el 2026-11-17 |
| OP-02 | Catálogo y memoria on-premise | Parcial | `db/converdata/001_esquemas.sql`, `002_curacion.sql`, `converdata db migrate`, `src/converdata/storage/catalog_repository.py`, `curation_repository.py`. La API recarga si cambia la versión (`runtime.py:153`). Prueba: `api/tests/test_catalog_db.py::test_la_api_carga_lo_que_publica_el_builder_sin_reiniciar` | Tarea programada del build (CA6). Documentos redactados (CA7). DDL probado en SQL Server 2022, no en 2016. Las pruebas de SQL Server no corren en la CI |
| OP-03 | Identidad on-premise | Parcial | SessionVault Fernet con clave efímera (`vault.py`). `APP=ConverData` y `Encrypt=yes` en la cadena de conexión (`api/converdata_api/connector.py:62`). Pruebas: `api/tests/test_security.py` | gMSA, DPAPI, LDAP, IAM Roles Anywhere. Sin volcados de WER (CA6). Depende del banco |
| OP-04 | Interfaces en IIS | Parcial | Todas las rutas de la tabla de la spec existen (`main.py`). Proxy `/api/*` (`web/src/app/api/[...path]/route.ts`). Pruebas: CA2, CA4, CA6, CA7 y CA9 en `api/tests/` | `web.config`, certificado, firewall, SSE a través de IIS, reinicio automático (CA1, CA3, CA5, CA8, CA10; HU-37) |
| OP-05 | Auditoría y observabilidad | Parcial | Auditoría en `audit.*`, logs JSON con lista blanca (`src/converdata/observability/logging.py`), contadores (`observability/metrics.py`). Pruebas: `api/tests/test_api.py::test_logs_json_sin_contenido`, `tests/test_observability.py` | Vistas SQL del scorecard. Alertas en el monitoreo. Visor de eventos en un Windows real. Tarea semanal de regresión (CA5). Credencial del monitoreo para `/health/metrics` |
| OP-06 | Residencia on-premise | Parcial | Sin estado en disco con la BD (`api/tests/test_catalog_db.py::test_el_servidor_no_guarda_estado_en_disco`). Literales marcados. Detector de 5 patrones (`api/converdata_api/pii.py`) | CA3 (documentos) depende de HU-26. CA4 (TEMP, IIS, volcados) depende de HU-37 |
| OP-07 | Instalación y operación | No construido | No existe `deploy/` (ni `deploy/windows/`). Sí existen lo que usarán los scripts: `converdata db migrate` (`cli.py:136`), `requirements/*.lock` y `tests/test_supply_chain.py` | Scripts 01–10, tareas programadas, respaldo y restauración (HU-39), actualización y rollback. Ningún criterio se comprobó en Windows Server |
| CN-01 | Despliegue en AWS | Fuera de alcance (decisión) | Imágenes Docker de web y API. No hay IaC (ni Terraform, ni CDK, ni CloudFormation) | Posterior al piloto (PRD §13, decisión 14) |
| CN-02 | Catálogo e ingesta en AWS | Fuera de alcance (decisión) | `catalog build --db` sin disco persistente | Tarea ECS y EventBridge Scheduler |
| CN-03 | Identidad en AWS | Fuera de alcance (decisión) | El mismo SessionVault | Secrets Manager e IAM de la tarea |
| CN-04 | Interfaces en AWS | Fuera de alcance (decisión) | Los mismos contenedores | ALB interno y salida del webhook sin internet |
| CN-05 | Auditoría y observabilidad en AWS | Fuera de alcance (decisión) | La auditoría ya va a la BD | El logger escribe a archivo, no a la salida estándar que recoge CloudWatch |
| CN-06 | Residencia en AWS | Fuera de alcance (decisión) | Los mismos controles de la API | VPN, VPC endpoints y KMS |

Recuento de la tabla (37 specs): 5 construidas, 16 parciales, 1 no construida, 15 fuera de alcance por decisión (9 de la fase 1b
y 6 del despliegue en AWS).

## Brechas por tipo

### (a) Funcionales del producto
- **Fuentes de conocimiento** (F23, HU-25 a HU-27). No se ingieren documentos ni Excel, no hay Presidio y no hay linaje de SSIS ni de los jobs. Es lo que más mueve las preguntas de reporte: 16 % → 60 % de Hit@1 con un glosario de prueba (`tests/test_graph_rag.py::test_las_fuentes_de_conocimiento_mueven_las_preguntas_de_reporte`).
- **Informe de métricas** (F25, HU-23, HU-32). Faltan `converdata metrics report`, las vistas SQL, el MRR y el reporte de brechas abiertas y cerradas por dominio.
- **Ficha del activo**. `/assets` no devuelve linaje ni documentos vinculados (`main.py:923-949`).
- **Curación**. No existen "El correcto es…", la detección de conflictos entre fuentes, las reglas sugeridas, el aviso al usuario que preguntó ni los comandos `catalog review` y `knowledge gaps`.
- **Credenciales por servidor**. El login acepta una sola credencial para todos los servidores (`main.py:65-75`) y no hay ruta para añadir otra. F14 y OP-03 prometen una por servidor.
- **Builder**. No hay `catalog refresh` ni las opciones `--database` y `--no-llm`. Faltan Query Store, MinHash, tipos semánticos y `estate review` (F18, F19).
- **Calidad**. Los fallos B14 y eng-06 (entidad con un calificativo que otra tabla conoce) siguen abiertos.
- **Límites conocidos**. La cola de revisión no filtra por visibilidad (pregunta abierta 7). Las estadísticas BM25 son globales. Cada escritura de curación recarga todo el índice. `/admin/metrics` lee como máximo 20 000 filas de auditoría (`main.py:865`).
- **Fase 1b** (F4–F10, F20, F21). Nada construido, por decisión.

### (b) Operación e instalación on-premise
- No existe `deploy/windows/` (OP-07, HU-37): IIS, HttpPlatformHandler, `web.config`, certificado, firewall y endurecimiento.
- Las tareas programadas no existen: build nocturno (HU-18), purga de 180 días y regresión semanal (HU-24).
- No hay respaldo ni restauración probados (HU-39), ni actualización y rollback.
- No hay alertas en el monitoreo. Falta decidir con qué credencial lee el monitoreo `/health/metrics`.
- La imagen con los bloqueos no se construyó. `msodbcsql18` y `unixodbc` van sin versión fijada. No hay firma ni análisis de la imagen.
- Las pruebas de SQL Server no corren en la CI. El DDL no se probó en SQL Server 2016.
- La API es un solo proceso: un reinicio cierra todas las sesiones.

### (c) Despliegue en la nube
- Fuera de alcance por decisión (PRD §13, decisión 14). No hay IaC.
- Cuando se retome: el logger escribe a archivo y no a la salida estándar (CN-05), y la salida del webhook de Teams sin internet está por definir (CN-04).
- El código ya sirve para una tarea sin disco: `catalog build --db` trabaja en un directorio temporal y la API recarga la versión de la BD cada 15 s (`runtime.py:153`).

### (d) Dependen del banco
| Necesidad | Bloquea | HU |
|---|---|---|
| Cuenta de AWS con Bedrock e IAM Roles Anywhere | Probar el LLM real, latencia y coste; repetir las suites `inyeccion` y `guardas` | HU-35, HU-36, HU-38 |
| 50–80 preguntas reales validadas por un responsable | D1 y D2 con datos válidos | HU-33 |
| Ubicación de diccionarios y documentos; acceso a SSISDB y msdb | Ingesta de documentos y linaje ETL | HU-26, HU-27 |
| Windows Server, instancia para la BD, gMSA y certificado de la PKI | Instalación y secretos sin contraseñas | HU-37, HU-38 |
| LDAP de solo lectura y cuentas de AD | Roles por grupo y métricas por perfil | HU-13 |
| Gestor de requerimientos y canal de consultas | Línea base de D3 y D4 | HU-40 |
| Decisiones abiertas del PRD §13 | Guardrails (6), visibilidad del responsable en Curación (7), lecturas auditadas (8), validación del login para dar roles (9), canal de notificación (4) | — |

## Criterios de salida del piloto

| Criterio | ¿Se mide hoy? | Por qué |
|---|---|---|
| D1 · Hit@3 ≥ 85 %, Hit@1 ≥ 65 % | Mecanismo sí, dato válido no | `eval discovery` y la suite `calidad` lo calculan. Pero el set es del equipo y no hay preguntas reales (HU-33) |
| D2 · Calibración ≥ 85 % | Mecanismo sí, dato válido no | `calibration@0.8` en `discovery_eval.py:102`. Mismo problema que D1 |
| D3 · Tiempo de localización −50 % | Solo el "después" | `time_to_confirm_s` en `/admin/metrics`. No hay línea base (HU-40) ni perfil por usuario (`user_group`) |
| D4 · Consultas a expertos −30 % | Solo una parte | Se cuentan los escalamientos. No hay línea base ni encuesta (HU-40) |
| D5 · p50 < 5 s, p95 < 10 s | Solo sin LLM | Modo determinista: 19 / 27 ms en BancosSQL. Con Bedrock no se ha medido (HU-35) |
| D6 · 0 fugas y 0 valores de cliente | Sí, en lo que cubre | Suite `permisos`: 0 fugas en 1 065 preguntas × usuario. `test_marked_literals.py` para literales. Sin documentos ingeridos, el índice no se probó con documentos reales; no detecta nombres de personas |
| D7 · Adopción ≥ 70 % (2 de 4 semanas) | No directamente | La auditoría tiene los datos, pero ni `/admin/metrics` ni ningún comando calcula "activo 2 de 4 semanas" |
| F25 · MRR ≥ 0,75 | No | El código no calcula MRR |
| F25 · Brechas marcadas ≥ 4 de 5 | Sí, con el set del equipo | `gap_ok` en `discovery_eval.py` |
| F25 · 0 objetos inventados | Sí, sin LLM | Suite `guardas` con un LLM simulado hostil; con Bedrock falta |
| F25 · Golden por semana, % de activos revisados, dominios con responsable | No | No están en `metrics_report` |
| F25 · Análisis de requerimientos y reprocesos | No | Dependen de etiquetas en el gestor de requerimientos del banco |

## Specs que ya no describen el código

| Ruta | Qué dice mal |
|---|---|
| `docs/PRD.md` (cabecera, línea 9) | Dice que falta la BD `ConverData`. Existe desde el bloque A (`db/converdata/`, `converdata db migrate`) |
| `docs/specs/comun/F11-audit.md` (§Modelo de datos) | Lista `curation.curation_request` como pendiente y "hoy en archivo". Con la BD vive en `curation.request` (`db/converdata/002_curacion.sql:32`) |
| `docs/specs/on-premise/OP-05-auditoria-observabilidad.md` (línea 9) | "Las solicitudes escaladas, todavía en un archivo (pasarán a `curation`)". Ya están en `curation.request` |
| `docs/specs/on-premise/OP-01-despliegue-local.md` (tabla de componentes, fila "Auditoría + golden") | "Hoy: JSONL con cadena de hashes". Con `CONVERDATA_DB` la auditoría va a `audit.*`; el JSONL es solo para desarrollo |
| `docs/specs/comun/F12-interfaces.md`, `OP-03-identidad.md`, `OP-04-interfaces.md` | El cuerpo del login es `{credentials: [{server, login, password}]}`, y OP-04 cita una ruta `/credentials`. El código recibe `{login, password, auth, servers[], host, alias, environment, trust_server_certificate, setup_token}` (`main.py:65-75`) y no tiene `/credentials` |
| `docs/specs/comun/F14-identity.md` (§Flujo, paso 1) | "Puede añadir credenciales de otros servidores más tarde". No hay ruta para eso; solo el administrador añade servidores con su propia credencial (`PUT /admin/inventory`) |
| `docs/specs/comun/F12-interfaces.md` (fila `GET /assets`) | Promete linaje y documentos vinculados. `object_detail` no los devuelve (`main.py:923-949`) |
| `docs/specs/comun/F24-knowledge-curation.md` (§Captura, punto 1, y tabla de roles) | Ofrece "El correcto es…": el código solo acepta `confirm` y `reject` (`main.py:96`), igual que F12. La tabla de roles dice que el `steward` está en `config/owners.yaml`; está en `curation.steward` |
| `docs/specs/cloud-native/CN-02-catalogo-memoria.md` (línea 27) | Dice que el mecanismo para recargar tras un Builder externo "está por confirmar". La API ya recarga cuando cambia `catalog.catalog_version` (`runtime.py:139-153`; `api/tests/test_catalog_db.py::test_la_api_carga_lo_que_publica_el_builder_sin_reiniciar`) |
| `docs/specs/comun/F13-architecture-docs.md` (criterios 1 y 2) | Habla de "las tres vistas" (son cuatro) y de componentes que son "un servicio de Windows" (no hay servicios propios, decisiones 11 y 12) |
| `docs/specs/comun/F18-discovery-mcp.md` | Lo describe como un servidor MCP (FastMCP) con 18 herramientas y campos de inventario `metadata_secret` y `query_store`. Es una biblioteca con 9 consultas fijas (`src/converdata/metadata/sqlserver.py`) y `ServerConfig` no tiene esos campos (`src/converdata/config.py:13-27`) |
| `docs/specs/comun/F01-catalog-builder.md` (§Fuentes) | Presenta `converdata-discovery` como "MCP propio" y las muestras en memoria como fuente. Ninguna de las dos existe |
| `docs/specs/comun/F19-multi-db-discovery.md` (§Salida) | Dice que entidades y aristas se guardan en el esquema `catalog`. Están en `knowledge.business_entity` y `knowledge.lineage_edge` (`db/converdata/001_esquemas.sql:142-155`). También cita `catalog/_estate/` |
| `docs/specs/comun/F23-knowledge-sources.md` (§Linaje) | "El linaje se carga en el mismo grafo `networkx` de F4". No se usa `networkx`: el grafo es `EstateGraph` (`src/converdata/graph/estate.py:37`) |
| `docs/specs/comun/F16-llm-providers.md` y `config/models.local.example.yaml` | La spec dice que no hay juez en la fase 1a. El ejemplo local aún declara `judge`, y el flujo etiqueta el nodo `review` con ese rol (`flows/discover.py:381`), aunque no hay implementación del puerto `Reviewer` |
| `docs/specs/comun/F05-value-resolution.md` | No dice en la cabecera que es de la fase 1b, como sí dicen F04, F06 y F09; el anexo A del PRD la marca 1b |
| `docs/backlog/on-premise.md` (estado de HU-23) | "Desde la auditoría en archivos". `/admin/metrics` lee el destino activo, también `audit.*` en SQL Server (`src/converdata/audit/sqlserver.py:175`) |

No se encontraron menciones vigentes a Chainlit, vectores, `SqlServerVectorStore`, OpenSearch ni a un servicio Builder en las
specs: las que quedan explican por qué se retiraron.
