# Calidad para un despliegue bancario: controles y cómo se verifican

> Creado: 2026-11-15. Actualizado: 2026-11-16 (auditoría y catálogo en la BD `ConverData`) y 2026-11-17 (curación en la BD; cadena de suministro y prueba de literales marcados). Diagrama: [controles de una petición y compuerta de calidad](architecture/controles-calidad-bancaria.html).
> Specs relacionadas: [OP-03 identidad](specs/on-premise/OP-03-identidad.md), [OP-04 interfaces](specs/on-premise/OP-04-interfaces.md),
> [OP-05 auditoría](specs/on-premise/OP-05-auditoria-observabilidad.md), [OP-06 residencia](specs/on-premise/OP-06-residencia-datos.md).

Este documento dice qué controla ConverData, dónde está cada control en el código, qué prueba lo fija y **qué falta** para
operar en un banco. Lo que falta está en [§5](#5-lo-que-todavía-no-está-resuelto): no se debe dar por cubierto.

## 1. Cómo verificar que todo funciona
```bash
.venv/Scripts/python -m pytest -q                                   # controles, capas y flujo de punta a punta
.venv/Scripts/python -m converdata.cli eval gate --out reports      # compuerta de calidad sobre los dos catálogos de prueba
.venv/Scripts/python -m converdata.cli audit verify --db            # la cuenta de CONVERDATA_DB no puede modificar la auditoría
.venv/Scripts/python -m converdata.cli audit verify --dir data/audit  # desarrollo sin BD: cadena de hashes en archivos
```
Todos salen con código distinto de 0 si algo falla.

Las pruebas contra un SQL Server real (migraciones, permisos de los roles, auditoría y catálogo en la BD, API de punta a punta) se
activan con `CONVERDATA_TEST_DB`, una cadena ODBC del servidor sin `DATABASE`; crean una BD `ConverData_test_<aleatorio>` y la eliminan
al terminar. Sin la variable se omiten, así que **la CI todavía no las corre**: hay que ejecutarlas en un equipo con SQL Server antes
de cada entrega (`CONVERDATA_TEST_DB="SERVER=localhost\SQLEXPRESS;Trusted_Connection=yes;TrustServerCertificate=yes"`). La CI ([`.github/workflows/calidad.yml`](../.github/workflows/calidad.yml))
tiene tres trabajos en cada push y PR, y además cada lunes (`schedule`), para detectar una vulnerabilidad nueva en algo ya fijado
aunque nadie haga push:
- `backend`: instala con versiones y hashes fijados (`requirements/build.lock` y `dev.lock`), corre los dos primeros comandos y
  guarda la evidencia de la compuerta como artefacto.
- `web` (desde el 2026-11-17): `npm ci`, tipos (`tsc --noEmit`), lint (`eslint --max-warnings=0`) y build.
- `cadena-de-suministro` (desde el 2026-11-17): instala sus herramientas de `requirements/tools.lock`, con hashes, y corre `pip-audit` sobre `requirements/runtime.lock`, `npm audit --omit=dev
  --audit-level=high` y el inventario de componentes (SBOM CycloneDX) de la API y de la web, publicado como artefacto.

Para un catálogo real: `converdata eval gate --root <directorio del catálogo> --cases <preguntas.yaml> --out reports`.
Con `--models config/models.yaml` corre con el gateway de LLM (el determinismo pasa a ser informativo).

## 2. La compuerta de calidad (`converdata eval gate`)
Código: [`src/converdata/evaluation/gate.py`](../src/converdata/evaluation/gate.py). Siete suites; todas deben aprobar.

| Suite | Qué comprueba | Criterio |
|---|---|---|
| `calidad` | Hit@1 ≥ 65 %, Hit@3 ≥ 85 %, calibración ≥ 85 % (en BancosSQL no se puede medir: ninguna respuesta llega a 0,8; DT-32 de [deuda técnica](wiki/deuda-tecnica.md)), brechas ≥ 90 %, p50 < 5 s, p95 < 10 s, y que ningún indicador ni tipo de pregunta (A–G) baje de `eval/baseline.yaml` | OP-01 D1, D2, D5 |
| `permisos` | Un usuario por BD, uno por cada "todas menos una" y uno sin acceso; cada uno hace todas las preguntas y llama a todas las herramientas. Nada fuera de su `visible_ids` puede aparecer | F14, OP-01 D6 |
| `inyeccion` | 25 inyecciones de prompt que nombran un activo oculto real del catálogo: 0 fugas, 0 objetos inventados | HU-36 |
| `guardas` | Un LLM simulado y hostil: inventa ids, nombra el activo oculto, mete enlaces, HTML y correos. Nada llega a la respuesta | PRD §8.1 |
| `robustez` | 28 entradas malformadas u hostiles (vacías, 20 000 caracteres, bytes nulos, SQL, plantillas, HTML): siempre un sobre válido | — |
| `determinismo` | La misma pregunta da la misma respuesta (sin LLM) | reproducibilidad |
| `auditoria` | Cada respuesta deja un registro con los mismos candidatos que se mostraron; si la auditoría falla, no hay respuesta | F11 |

- El detector de fugas (`LeakScanner`) no usa listas escritas a mano: calcula para cada usuario qué tablas y BDs no puede
  ver y busca sus nombres en todo lo devuelto. El mismo detector se usa sobre las respuestas HTTP en `api/tests/test_security.py`.
- Umbrales por catálogo: `<root>/eval/gate.yaml` (opcional). Línea base: `<root>/eval/baseline.yaml`; se regenera con
  `--write-baseline` **solo** después de revisar que el cambio mejora.
- [`tests/test_gate.py`](../tests/test_gate.py) rompe a propósito cada control y comprueba que su suite falla.

Resultado al 2026-11-17 (modo determinista, sets ampliados ese día): aprobado en `tests/fixtures/vbank` (31 casos, Hit@1 y Hit@3
96,2 %; falla eng-06) y `tests/fixtures/bancos` (58 casos, Hit@1 y Hit@3 98,0 %; falla B14), con 0 fugas en 1 065 preguntas × usuario
y 4 862 llamadas a herramientas. Las líneas base se regeneraron ese día. Los dos catálogos son de prueba y sus preguntas las
escribió el equipo de desarrollo (ver §5).

Resultado anterior (2026-11-16, sets de 25 y 31 casos): Hit@1 100 % en VBank y 93,1 % en BancosSQL, con 0 fugas en 714 preguntas ×
usuario.

Con el catálogo de BancosSQL cargado desde la BD `ConverData` (`eval gate --db --root tests/fixtures/bancos`) el resultado es el
mismo, también con el set ampliado (2026-11-17): Hit@1 y Hit@3 98,0 %, 0 fugas en 737 preguntas × usuario y 4 309 llamadas.

## 3. Controles implementados
| Control | Dónde | Prueba |
|---|---|---|
| Toda ruta no pública exige sesión; `/admin` y `/curation` exigen rol. La matriz se genera de `app.routes` | `api/converdata_api/main.py` | `test_toda_ruta_no_publica_exige_sesion`, `test_rutas_de_administracion_y_curacion_rechazan_al_consumidor` |
| Bloqueo del login: 5 fallos en 10 min por usuario, 30 por origen; un servidor caído no cuenta | `security.LoginThrottle` | `test_el_login_se_bloquea_tras_cinco_fallos` |
| El login y el host no pueden añadir atributos a la cadena ODBC (`x;Trusted_Connection=yes` entraba con la cuenta del servicio) | `security.valid_login`, `connector._braced` | `test_un_login_con_caracteres_de_cadena_odbc_se_rechaza`, `test_la_cadena_de_conexion_escapa_usuario_y_contrasena` |
| Autenticación de Windows apagada por defecto (abría sesión con la cuenta del proceso) | `settings.py` | `test_autenticacion_de_windows_apagada_por_defecto` |
| Primer arranque con código de instalación (`CONVERDATA_SETUP_TOKEN`) | `main.py: login` | `test_el_primer_arranque_exige_el_codigo_de_instalacion` |
| `data_admin` por lista explícita (`CONVERDATA_ADMINS_ONLY`) | `main.py: login` | `test_con_admins_only_ser_sysadmin_de_un_servidor_no_da_el_rol` |
| Sesión: 8 h de inactividad, 12 h de vida total, 5 por usuario, revocable por el admin; el token no sale en `repr` | `vault.py`, `/admin/sessions` | `test_la_sesion_caduca_…`, `test_el_admin_revoca_…` |
| Permisos de SQL Server releídos cada 15 min | `runtime.visible_ids` | `test_la_visibilidad_se_vuelve_a_leer_de_sql_server` |
| La ficha de un activo no muestra llaves foráneas hacia tablas ocultas | `main.py: object_detail` | `test_la_ficha_de_un_activo_no_revela_…`, `test_barrido_de_la_api_sin_fugas_…` |
| Cabeceras de seguridad, `Cache-Control: no-store`, HSTS con HTTPS; CSRF por `Origin`; tope de 4 MB (valen en la API; el proxy de la web no reenvía `Origin` ni devuelve las cabeceras al navegador, hoy protege `SameSite=lax`: DT-01 y DT-03 de [deuda técnica](wiki/deuda-tecnica.md)) | `security.SecurityMiddleware` | `test_cabeceras_…`, `test_cambio_de_estado_con_cookie_desde_otro_origen_…`, `test_cuerpo_demasiado_grande_…` |
| Ritmo por usuario (no por sesión) y tope diario de tokens, también por `/mcp` | `main.py: check_rate, mcp_guard` | `test_el_limite_de_ritmo_es_por_usuario_…`, `test_mcp_respeta_el_tope_de_tokens_…` |
| Auditoría en la BD `ConverData`: una transacción por pregunta; la cuenta de la API inserta y lee, pero no modifica ni borra; la purga solo la ejecuta otro rol y nunca por debajo de 180 días | `converdata.audit.sqlserver`, `db/converdata/001_esquemas.sql` | `test_la_api_no_puede_modificar_ni_borrar_la_auditoria`, `test_la_purga_exige_180_dias_…`, `test_pregunta_voto_y_lecturas_quedan_en_el_esquema_audit` |
| Sin auditoría no hay respuesta ni cambio, tampoco con la BD caída | `flows/discover.py`, `main.py` | `test_si_la_bd_no_responde_no_hay_respuesta_ni_cambios`, `test_sin_auditoria_no_se_aplica_…` |
| Sin BD (desarrollo): auditoría en archivo con cadena de hashes y enlace entre días | `converdata.audit.chain`, `api/converdata_api/audit.py` | `test_la_auditoria_detecta_filas_…` |
| Catálogo en la BD con historial y autor de cada cambio; un refresco no pisa lo humano ni toca reglas, confirmaciones o responsables; dos procesos no se pisan (bloqueo; versión esperada al publicar) | `converdata.storage.catalog_repository` | `test_una_edicion_humana_queda_en_el_historial_con_su_autor`, `test_un_refresco_del_builder_no_pisa_…`, `test_no_se_publica_sobre_una_version_que_ya_no_es_la_vigente` |
| Roles de BD de mínimo privilegio: el Builder solo toca lo que deriva de los metadatos y no lee preguntas ni confirmaciones; el auditor solo lee `audit`; ni la API ni el Builder pueden apagar el historial ni bajar la versión | `db/converdata/001_esquemas.sql` | `test_el_builder_solo_toca_lo_que_deriva_de_los_metadatos`, `test_la_cuenta_del_builder_refresca_sin_leer_ni_tocar_lo_curado`, `test_la_api_no_puede_reescribir_el_historial_ni_la_version`, `test_el_auditor_solo_lee_la_auditoria` |
| La cuenta de la API, con su rol real, pasa `verify` (esquema y cada tabla de `audit`, la purga y el historial) | `audit.sqlserver.verify` | `test_la_cuenta_de_la_api_publica_carga_audita_y_pasa_verify` |
| Una edición de curación es atómica: las comprobaciones y la escritura de sus filas corren bajo un solo candado y sobre el catálogo vigente (si otro proceso publicó, primero se carga lo suyo); si la escritura falla, no queda nada a medias | `runtime.editing`, `converdata.curation.KnowledgeWriter` | `test_dos_ediciones_a_la_vez_…`, `test_si_la_escritura_falla_no_queda_nada_a_medias`, `test_una_edicion_no_pisa_lo_que_escribio_otro_proceso` |
| Con `CONVERDATA_DB` el servidor de aplicación no guarda estado en disco: catálogo, inventario, responsables, dudas escaladas y votos viven en la BD; el build usa un directorio temporal que se borra | `runtime.py`, `storage/curation_repository.py`, `db/converdata/002_curacion.sql` | `test_el_servidor_no_guarda_estado_en_disco`, `test_otra_instancia_arranca_con_lo_publicado_sin_archivos_previos` |
| Dar o quitar el rol de responsable queda auditado antes de aplicarse (`stewards_updated`) y en el historial temporal de `curation.steward`; solo `data_admin` | `main.py: put_stewards` | `test_los_responsables_se_administran_desde_la_api_y_quedan_auditados` |
| Regla de votos: los usuarios cuentan confirmaciones netas (último voto de cada uno); un solo "✖" no retira lo que confirmaron varios; el responsable del dominio manda | `converdata.curation.resolve_golden` | `test_los_usuarios_cuentan_confirmaciones_netas`, `test_un_solo_rechazo_no_retira_lo_que_confirmaron_varios`, `test_el_responsable_manda_sobre_los_usuarios` |
| Votos, solicitudes y ediciones se auditan antes de aplicarse; un voto escribe una sola fila | `runtime.record_feedback`, `main.py` | `test_pregunta_voto_y_lecturas_…`, `test_un_voto_escribe_una_sola_fila_y_sube_la_version` |
| La confirmación guarda una plantilla anónima: la pregunta normalizada sin literales. Regla endurecida tras la revisión de seguridad del 2026-11-17 (ya no hay lista de formatos): tras normalizar con NFKC (los dígitos en superíndice, de ancho completo o en círculo cuentan como dígitos), toda palabra con algún dígito o con arroba es un literal, salvo el vocabulario conocido del banco: nombres del catálogo con dígitos (`Ultimos4`) y códigos del conocimiento con letras y dígitos (`NCB-022`, `BR-ONB-004`). `T24` o `F14` salen si no son nombres del catálogo ni códigos del glosario. La revisión reprodujo que `ACME090`, los dígitos en superíndice, el guion final o la raya llegaban a la plantilla y al original con la regla por formatos. Si aun así parece llevar datos personales, el voto cuenta pero no se aprende. El original va a `golden` solo si la pregunta no tiene ningún literal con esta regla ni dispara `find_pii`; las confirmaciones no se exportan a git | `converdata.memory.text.strip_literals`, `has_literals`, `Catalog.names_with_digits`, `KnowledgeBase.codes`, `runtime._vocabulary`, `converdata.curation.question_template`, `runtime.record_feedback`, `runtime._store_golden`, `write_snapshot` | `test_la_plantilla_no_conserva_literales`, `test_una_pregunta_con_literales_se_reconoce_para_no_guardar_su_texto`, `test_el_vocabulario_del_banco_no_es_un_literal`, `test_una_pregunta_que_es_solo_literales_no_se_aprende`, `test_la_confirmacion_guarda_una_plantilla_sin_literales`, `test_un_identificador_alfanumerico_tampoco_llega_a_la_plantilla`, `test_la_exportacion_para_git_no_lleva_preguntas` |
| El literal de una pregunta solo queda donde vive el texto de las preguntas (F17 CA1, OP-02 CA5, OP-06 CA1 y CA4). 100 preguntas con 100 literales distintos en 10 formas (códigos `ACME-TEST-nnn`, documentos, cuentas alfanuméricas, correos, números, alfanumérico corto, dígitos en superíndice, raya, guion bajo con guion final y ancho completo), hechas por la API con tres usuarios (el literal va también en `history`), votadas, 20 escaladas con nota y varias respondidas por un responsable. Después se busca el literal, también transformado (minúsculas, NFKC, recortado a los 6 caracteres del stemmer), en el índice en memoria, en todo el disco del servidor (logs incluidos) y en toda columna de toda tabla de la BD que no sea número, fecha, bit o `uniqueidentifier`, convertida a texto (historial incluido): solo aparece en `audit.audit_question.question`, `curation.request.question` y `curation.request.note` (en modo archivos, en `audit/*.jsonl` y `curation/requests.json`). Las plantillas solo contienen palabras de las preguntas base. No cubre el cliente MCP, `/discover/stream`, el Visor de eventos, `TEMP` de las gMSA, carpetas de IIS ni volcados de memoria (§5) | `converdata.memory.text.strip_literals`, `converdata.curation.question_template`, `runtime.record_feedback` | `api/tests/test_marked_literals.py`: `test_el_literal_de_una_pregunta_solo_queda_donde_viven_las_preguntas` (en archivos y, con `CONVERDATA_TEST_DB`, en SQL Server real) |
| El nombre de una tabla referenciada por llave foránea solo cuenta como término de un activo si el usuario también ve esa tabla: quien no la ve no puede confirmar su nombre por la confianza de la respuesta (ocurría también en el código anterior; revisión de seguridad del 2026-11-17) | `engine._asset_terms_split`, `engine._asset_terms` | `tests/test_graph_rag.py::test_el_nombre_de_una_tabla_que_no_se_ve_no_mueve_la_confianza` |
| Un literal de la pregunta (toda palabra con un dígito o una arroba que no sea un nombre con dígitos de lo que el usuario ve) no cuenta como concepto que un activo deba cubrir: no cambia qué se encuentra ni entra al cálculo de cobertura | `discovery/expansion.py` (`_words`, `concepts_of`), `Catalog.names_with_digits(visible_ids)` | Sin prueba unitaria propia: lo ejercitan las 100 preguntas de `test_marked_literals.py` (al menos 80 deben traer candidato y voto) |
| Una respuesta que descontó un calificativo que el catálogo no conoce queda siempre por debajo del umbral de brecha: se muestra la tabla con confianza baja y se ofrece preguntar al responsable, nunca como respuesta segura | `engine.qualifier_weights`, `engine.compute_confidence` (`Draft.unknown_qualifiers`) | `tests/test_graph_rag.py`: `test_un_calificativo_que_nadie_conoce_pesa_menos_pero_la_entidad_no`, `test_una_entidad_con_calificativos_desconocidos_se_responde_con_confianza_baja`, `test_lo_que_el_banco_no_tiene_nunca_sale_como_respuesta_segura`; casos `G6` y `G7` del set de BancosSQL (suite `calidad`, brechas reconocidas) |
| Cadena de suministro: todas las dependencias de Python con versión exacta y hash (`requirements/runtime.lock`, `dev.lock`, `build.lock` y `tools.lock`, este con `pip-audit` y `cyclonedx-bom`: el trabajo `cadena-de-suministro` ya no instala nada sin hash); la imagen y la CI instalan con `pip install --require-hashes --only-binary :all:` (sin compilar nada desde código) y el paquete con `--no-deps --no-build-isolation --no-index`; la clave con la que Microsoft firma su repositorio se acepta solo si su huella es la fijada (`MICROSOFT_KEY_FINGERPRINT` en `api/Dockerfile`); lo que se despliega no trae herramientas de desarrollo; imágenes base por digest; acciones de GitHub por commit; en la web, Next.js con versión exacta, `npm ci` y `package-lock.json` con la integridad de cada paquete. Dependabot propone las actualizaciones de imágenes, acciones y npm | `requirements/` ([README](../requirements/README.md)), `api/Dockerfile`, `web/Dockerfile`, `.github/workflows/calidad.yml`, `.github/dependabot.yml` | `tests/test_supply_chain.py`: `test_toda_dependencia_declarada_esta_fijada_con_su_hash`, `test_lo_que_se_despliega_no_trae_herramientas_de_desarrollo`, `test_las_imagenes_base_van_por_digest_y_se_instala_con_hashes`, `test_las_acciones_de_la_ci_van_por_commit_y_la_ci_analiza_las_dependencias`, `test_la_web_fija_versiones_exactas_y_su_bloqueo_trae_integridad` |
| Análisis de vulnerabilidades conocidas e inventario de componentes en cada push y PR, y cada lunes (`schedule`): `pip-audit` sobre lo que se despliega, `npm audit --omit=dev --audit-level=high` y SBOM CycloneDX de la API y de la web. El 2026-11-17 encontró vulnerabilidades reales en Next.js 15.5.4 (entre otras, ejecución remota de código en servidores Windows), actualizado a 15.5.29, y en `postcss` transitivo, forzado a 8.5.33 con `overrides`; `npm audit --omit=dev` queda en 0 y `pip-audit` no encontró nada | Trabajo `cadena-de-suministro` de `.github/workflows/calidad.yml`, `web/package.json` | El propio trabajo de la CI (falla el PR); `test_las_acciones_de_la_ci_van_por_commit_y_la_ci_analiza_las_dependencias` comprueba que el análisis sigue en el workflow |
| La web se comprueba en la CI: tipos, lint sin avisos y build | Trabajo `web` de `.github/workflows/calidad.yml` | El propio trabajo de la CI |
| Los roles que se dan por nombre de login (lista `CONVERDATA_ADMINS` y responsables) solo cuentan si la sesión validó ese login en un servidor con `environment: produccion`, cuando el inventario tiene alguno: quien administra un servidor de desarrollo puede crear allí un login con cualquier nombre | `main.py: identity_trusted` | `test_un_login_validado_solo_en_desarrollo_no_hereda_roles_por_su_nombre` |
| Curar no revela activos: fuera de sus dominios un responsable recibe 403 solo si ya ve el activo con su login, y 404 si no; el historial exige además visibilidad; la bandeja solo muestra en `shown` activos de sus dominios; `/me/requests` no entrega la nota libre cuando falta acceso; en el diccionario, lo no visible va a `unknown`; una regla sin activos vigentes solo la gestiona quien cura su dominio, y chocar con el id de una regla ajena da un 409 genérico | `main.py: require_curable, manages_rule` | `test_curar_no_revela_activos_que_el_login_no_puede_ver`, `test_la_bandeja_y_la_respuesta_de_una_duda_no_filtran_otros_dominios`, `test_una_regla_sin_activos_vigentes_solo_la_gestiona_su_dominio` |
| El diccionario de un responsable no bloquea el de otro: no hay registro por hash del archivo; repetirlo no escribe nada porque no queda nada que cambiar | `converdata.curation.plan_dictionary` | `test_el_diccionario_de_un_responsable_no_bloquea_el_de_otro` |
| La purga de 180 días alcanza también las dudas escaladas (`curation.request`) y los originales de las confirmaciones; los votos y las plantillas, sin texto libre, se conservan. La cuenta de la API no puede cambiar ni borrar votos ni originales | `db/converdata/002_curacion.sql` (`audit.usp_purge`, `DENY UPDATE, DELETE`) | `test_la_purga_alcanza_las_dudas_y_los_originales_pero_no_los_votos`, `test_la_cuenta_de_la_api_no_puede_cambiar_ni_borrar_votos_ni_originales` |
| Un refresco no revierte una corrección humana hecha mientras corría el build: la descripción humana de la BD gana siempre | `catalog_repository._protect` | `test_el_refresco_no_revierte_una_correccion_humana_hecha_durante_el_build` |
| El historial atribuye cada descripción a quien la escribió, no a quien tocó la fila después | `catalog_repository.description_history` | `test_el_historial_atribuye_la_descripcion_a_quien_la_escribio_no_a_quien_toco_la_fila` |
| Si el catálogo vigente no se puede cargar, la API queda sin catálogo (409) en vez de servir el anterior, y quien editó recibe el error | `runtime.reload`, `runtime._written` | `test_si_el_catalogo_no_recarga_tras_editar_no_se_sirve_lo_anterior` |
| Un cambio anunciado en la auditoría que falla deja `<evento>_failed` con el tipo del error (`feedback_failed` para el voto); `catalog_build_finished` no lleva el texto del error, solo los ids de los servidores que fallaron | `main.py: applying`, `runtime.record_feedback` | `test_un_cambio_que_falla_deja_constancia_de_que_no_se_aplico` |
| El voto y la confirmación que resulta se escriben bajo un mismo candado; el voto de un responsable rige en la siguiente búsqueda | `runtime.record_feedback` | `test_dos_votos_a_la_vez_cuentan_los_dos`, `test_el_voto_del_responsable_rige_en_la_siguiente_busqueda` |
| Con `CONVERDATA_DB` la API no arranca si faltan migraciones, y dice que se ejecute `converdata db migrate` | `storage.migrations.require_current` | `test_la_api_no_arranca_con_migraciones_pendientes_y_lo_dice_claro` |
| El Builder programado solo se conecta, con la cuenta del servicio, a los hosts de `CONVERDATA_BUILDER_HOSTS` (obligatoria en qa y prod): el inventario de la BD lo edita un administrador desde la web | `cli.py: builder_hosts_refused` | `test_el_builder_solo_va_a_los_hosts_permitidos` |
| Las pruebas nunca corren contra una BD existente | `conftest.py`, `storage.connection.names_database` | `test_las_pruebas_no_aceptan_una_cadena_que_nombre_una_bd` |
| Se auditan además: accesos denegados, bloqueos, lectura de la auditoría, cambios de inventario con host anterior y nuevo, revocaciones | `main.py` | `test_rutas_de_administracion_…`, `test_el_primer_arranque_…` |
| Un responsable solo documenta activos de sus dominios, y sin datos personales (DUI, NIT, correo, teléfono, IBAN, tarjeta) | `main.py: curation_answer`, `pii.py` | `test_un_responsable_no_documenta_…`, `test_las_ediciones_de_curacion_no_aceptan_datos_personales` |
| Nombres de objetos con `.`, `/`, `\`, `:` no entran al catálogo ni escriben fuera de él | `builder.unsafe_name`, `object_path` | `test_el_build_omite_…`, `test_un_objeto_no_se_escribe_fuera_del_catalogo` |
| Texto del LLM con enlaces, HTML o correos se reemplaza por el determinista; el contenido del catálogo va delimitado en los prompts | `engine.unsafe_generated_text`, `llm/nodes.py` | `test_texto_generado_…`, suite `guardas` |
| Errores internos: al público solo un mensaje genérico; en los logs solo el tipo de excepción | `runtime.reload`, `/setup/status` | `test_el_error_de_carga_del_catalogo_no_se_publica` |

## 4. Configuración obligatoria en qa y prod
Con `CONVERDATA_ENV=qa` o `prod` la API **no arranca** si algo de esto falta (`security.production_violations` para los ajustes y
`security.inventory_violations` para el inventario, que se revisa ya cargado de la BD;
`test_la_api_no_arranca_en_produccion_con_ajustes_inseguros`, `test_produccion_revisa_inventario_modelos_y_auditoria_del_catalogo`):

| Variable | Valor |
|---|---|
| `CONVERDATA_DEMO` | sin definir |
| `CONVERDATA_COOKIE_SECURE` | `1` (HTTPS) |
| `CONVERDATA_CORS_ORIGINS`, `CONVERDATA_PUBLIC_URL` | la URL `https://` del sitio |
| `CONVERDATA_MCP_HOSTS` | nombre del servidor (o `CONVERDATA_MCP=0`) |
| `CONVERDATA_ALLOW_WINDOWS_AUTH` | sin definir |
| `CONVERDATA_ADMINS_ONLY=1`, `CONVERDATA_ADMINS` | logins de los administradores de datos |
| `CONVERDATA_SETUP_TOKEN` | secreto del instalador, mientras no exista inventario |
| `CONVERDATA_LOG_DIR` | directorio de logs (hoy no se exige: `settings.py` le da `data/logs` por defecto y nunca falta; DT-06 de [deuda técnica](wiki/deuda-tecnica.md)) |
| `CONVERDATA_DB` | cadena ODBC de la BD `ConverData`, sin contraseña (`Trusted_Connection=yes`), con `Encrypt=yes` y sin `TrustServerCertificate`, y con una cuenta que solo pertenezca a `converdata_app` (la API comprueba al arrancar que no puede modificar ni borrar la auditoría) |
| `config/models.yaml` | `data_mode: real`; sin rol `embed` (retirado: fuera de qa y prod se ignora con un aviso) |
| Inventario (en la BD `ConverData`) y `config/settings.yaml` | sin `trust_server_certificate`; sin `audit.fail_open` |
| Migraciones de la BD `ConverData` | al día (`converdata db migrate`); la API lo comprueba al arrancar en cualquier ambiente que use `CONVERDATA_DB` |
| `CONVERDATA_BUILDER_HOSTS` (tarea del Builder, no la API) | hosts o sufijos de dominio (`.banco.local`), separados por coma, a los que `catalog build --db` puede conectarse; sin ella el comando se niega en qa y prod |

Además `/docs` y `/openapi.json` dejan de publicarse. Opcionales: `CONVERDATA_SESSION_MAX_AGE_S`, `CONVERDATA_MAX_SESSIONS`,
`CONVERDATA_LOGIN_MAX_FAILURES`, `CONVERDATA_LOGIN_LOCKOUT_S`, `CONVERDATA_TRUST_PROXY` (detrás de un proxy propio),
`CONVERDATA_VISIBILITY_TTL_S`, `CONVERDATA_MAX_BODY_BYTES`, `CONVERDATA_MANUAL` (ruta del manual de desarrollo), `CONVERDATA_SESSION_TTL_S`, `CONVERDATA_LOGIN_WINDOW_S`,
`CONVERDATA_LOGIN_IP_MAX_FAILURES`.

⚠️ Sin `CONVERDATA_ENV` el valor es `dev` y nada de esto se exige: el instalador debe fijarlo (HU-37).

La web se compiló el 2026-11-17 (`npx tsc --noEmit`, `eslint` y `npm --prefix web run build`, sin errores). Ese día se probaron en un
navegador, contra la API real y el SQL Server local, el inicio de sesión, la pestaña Responsables y el historial de una descripción;
el resto de las pantallas no se volvió a recorrer a mano.

## 5. Lo que todavía no está resuelto
Nada de esta lista se cubre con el código actual. Cada punto necesita infraestructura, una decisión o trabajo aparte.
La deuda técnica detectada en el código, con su prioridad, está en [wiki/deuda-tecnica.md](wiki/deuda-tecnica.md).

| Pendiente | Por qué importa | Qué hace falta |
|---|---|---|
| La plantilla anónima de las confirmaciones no detecta nombres de personas, texto entre comillas ni los trozos solo de letras de un código partido por espacios (un IBAN escrito con espacios deja sus grupos de letras) | Quita toda palabra con un dígito o una arroba que no sea vocabulario del banco; una pregunta con un nombre propio queda en `knowledge.golden_discovery` y en el índice. Mitigado: no se aprende si tras quitar los literales coincide con los seis tipos de datos personales de `pii.py`; el Builder no la lee; no se exporta | Detector de nombres (Presidio, HU-26) o revisión del responsable antes de reutilizar |
| Los roles por nombre de login exigen haber validado el login en un servidor de producción (`identity_trusted`) | Es una política elegida en el código; el banco puede preferir un servidor de referencia designado. Si el inventario no tiene ningún servidor de producción, cualquier servidor vale | Confirmarla con el banco (PRD §13, pregunta abierta 9); queda superada con los grupos de AD (HU-13) |
| Las estadísticas BM25 del índice son globales, no por usuario (`memory/memory_store.py`) | La confianza de una respuesta para un mismo usuario varía hasta ~0,006 según existan objetos que no ve. No aparece ningún nombre oculto, pero es una señal mínima de que existe algo más | Calcular las estadísticas sobre lo visible, o aceptar el riesgo |
| Dos preguntas que solo difieren en un código que el banco no tiene en su glosario comparten plantilla y confirmación | El código sale de la plantilla como literal: una confirmación hecha para una norma puede dar el bonus a la pregunta por otra | Cargar los códigos en el glosario o en las reglas (`KnowledgeBase.codes`), o revisión del responsable |
| La prueba de literales marcados (§3) no cubre el cliente MCP, `/discover/stream`, el Visor de eventos de Windows (`event_log` va apagado en la prueba), `TEMP` de las gMSA, las carpetas de IIS ni los volcados de memoria | OP-06 CA4 nombra los del servidor del piloto; el MCP y el streaming usan el mismo flujo, pero la prueba no pasa por ellos. La prueba recorre el directorio de datos y de logs de la API y, con `CONVERDATA_TEST_DB`, todas las tablas de la BD; como las demás pruebas de SQL Server, esa parte no corre en la CI | Repetir la búsqueda del literal en el servidor instalado (HU-37) |
| `job.error` del build conserva el texto de la excepción | Un mensaje de conexión puede traer host, instancia o login; solo lo ve el administrador en `GET /admin/catalog/build` (ya no va a la auditoría) | Reducirlo al tipo de error, o aceptarlo para el administrador |
| En modo demo con BD queda un marcador en `curation_dir` (`.demo_history.json`) | Es el único archivo que la API escribe con BD; el modo demo no se admite en qa ni en prod | Llevarlo a la BD si la demo debe correr sin disco |
| `tests/test_architecture.py` no analiza `api/converdata_api`; la orquestación de votos vive en la API y la CLI no usa `open_stores` | La regla de capas no se verifica en la API ([capas-backend](architecture/capas-backend.md)) | Extender la prueba y mover la orquestación a `converdata.application` |
| La fecha de un registro de auditoría la puede fijar quien lo inserta | Una cuenta comprometida podría antedatar sus filas para que caigan en la siguiente purga | Columna `recorded_at` con valor por defecto y purga por ella (una migración posterior; la `002` no lo incluye) |
| `converdata audit purge` y `eval gate --db` no tienen prueba automática del comando | `db migrate`, `catalog publish`, `catalog export`, `discover --db` y `catalog build --db` ya la tienen (`tests/test_catalog_refresh.py`); de la purga se prueba el procedimiento `audit.usp_purge` | Añadirlos a las pruebas de la CLI contra la BD desechable |
| La purga de 180 días existe (`audit.usp_purge`, `converdata audit purge`) pero no está programada | OP-05 | Tarea programada con una cuenta del rol `converdata_maintenance` (HU-37) |
| Las pruebas contra SQL Server no corren en la CI | Una regresión en el DDL o en los adaptadores no se vería en un PR | Servicio de SQL Server en el workflow, o ejecutarlas a mano antes de cada entrega |
| El DDL (migraciones `001` y `002`) se probó en SQL Server 2022, no en 2016 | PRD §13, decisión 10 dice "2016 o posterior" | Probar en la versión de la instancia del piloto |
| El dueño de la BD (`dbo`, DBA) sí puede modificar la auditoría | Es inherente a SQL Server; el control cubre a la cuenta de la aplicación | SQL Server Audit sobre el esquema `audit`, o exportar a un SIEM, si Seguridad lo exige |
| Gateway de LLM sin probar con Bedrock ni NIM | La compuerta solo corrió en modo determinista; con un LLM real hay que repetir `inyeccion` y `guardas` | HU-35 y `eval gate --models` |
| Set de evaluación de 89 preguntas (58 de BancosSQL y 31 de VBank) y 25 de reporte, todas escritas por el equipo | Sesgo de ajuste: los porcentajes no predicen el uso real. Los cambios de orden del 2026-11-17 se ajustaron y midieron con esas mismas preguntas; en las de reporte, también el glosario es del equipo | 50–80 preguntas de usuarios del piloto (HU-33) y documentos reales (HU-26) |
| Dos preguntas del set quedan sin candidatos: B14 ("¿Dónde están los dispositivos Android bloqueados?") y eng-06 ("¿Dónde están los dispositivos iOS de clientes premium?") | Una entidad con un calificativo que sí conoce otra tabla: el calificativo no se descuenta. El usuario recibe una brecha (puede preguntar al responsable), no una respuesta equivocada | Solo si el set real lo pide ([plan §3](PLAN-desarrollo.md#3-próximos-pasos-en-orden)) |
| La cola de revisión (`/curation/review`) y la edición de descripciones no aplican `visible_ids` al responsable dentro de sus dominios | F14 dice que no hay modo de catálogo abierto. Ya resuelto: fuera de sus dominios responde igual que a lo inexistente (404) salvo que ya vea el activo, y el historial exige visibilidad | Decidir si el responsable está exento en sus dominios y documentarlo, o filtrar (PRD §13, pregunta abierta 7) |
| Lecturas sin auditar: `/catalog/*`, `/assets` y herramientas MCP distintas de `discover` | Trazabilidad de quién consultó qué | Decidir el nivel de detalle y su volumen |
| Cada escritura de curación vuelve a cargar el catálogo de la BD y reconstruye todo el índice (síncrono tras una edición o el voto de un responsable; en segundo plano tras el voto de un usuario) | Coste en catálogos grandes; lo acota el límite de ritmo. El voto ya escribe solo su fila | Actualizar solo la colección `golden` o lo que cambió |
| La imagen de la API no se construyó con los bloqueos el 2026-11-17 (Docker no estaba en marcha) | Los pasos de instalación de `api/Dockerfile` se simularon en un entorno limpio, pero la imagen real no se ha construido ni arrancado; la CI tampoco la construye | Construirla y arrancarla; añadir el build a la CI |
| Los paquetes del sistema de la imagen (`msodbcsql18`, `unixodbc`) no van fijados por versión | `apt-get install` toma la versión del día: es lo único de la imagen sin fijar. Sí está fijada la huella de la clave con la que Microsoft firma su repositorio | Fijar la versión, o aceptar el riesgo con el escaneo de la imagen |
| Sin firma de imágenes ni escaneo de la imagen construida | `pip-audit` y `npm audit` miran las dependencias declaradas, no la imagen base ni sus paquetes del sistema; el SBOM es de dependencias, no de la imagen | Escáner de imágenes y firma en la CI |
| Las dependencias de desarrollo de la web siguen con avisos de `npm audit` | No se despliegan (`--omit=dev` queda en 0), pero corren en el equipo del desarrollador y en la CI | Actualizarlas cuando haya versión corregida (Dependabot) |
| Los bloqueos de Python se regeneran a mano | Dependabot cubre imágenes, acciones y npm, no `requirements/*.lock` | Seguir [`requirements/README.md`](../requirements/README.md) al cambiar una dependencia; `pip-audit` avisa en cada PR y cada lunes |
| El token de sesión también viaja en el cuerpo del login | Lo necesita el cliente MCP; debilita `HttpOnly` si la web lo guarda | Emitirlo solo a petición |
| Sesiones, bloqueos, topes, trazas de respuestas, inventario y confirmaciones recientes en memoria de un proceso | Un solo worker; un reinicio cierra las sesiones y borra los contadores; el inventario se lee al arrancar; los responsables se cachean 5 s | Aceptado en OP-03; revisar si se pide alta disponibilidad |
| Detector de datos personales de seis tipos (DUI, NIT, correo, teléfono, IBAN, tarjeta; `api/converdata_api/pii.py`) | No cubre nombres ni direcciones | Presidio (HU-26) |
| Batería de inyección sin revisar por Seguridad del banco | ⚠️ S7 | Ampliarla con ellos |
| Prueba de penetración, revisión de IIS/TLS, cuentas gMSA, SSO | Fuera del código | Con el banco |
