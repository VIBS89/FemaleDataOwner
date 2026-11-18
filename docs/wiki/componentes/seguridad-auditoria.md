# Seguridad y auditoría

Actualizado el 2026-11-17.

**Para qué sirve.** Reúne los controles que hacen que ConverData no amplíe permisos, no filtre lo que un usuario no ve, no guarde
secretos ni valores, y deje constancia de cada pregunta y cada cambio. No es un módulo único: son piezas repartidas entre la API
(`api/converdata_api/`) y el núcleo (`src/converdata/identity/`, `audit/`, `observability/`, `memory/text.py`, `curation.py`).

**Lo esencial**
- Cada usuario descubre solo lo que su login SQL puede leer: `visible_ids` se calcula con su propia conexión.
- La credencial vive cifrada en memoria del proceso, con una clave que muere al reiniciar.
- La auditoría es fail-closed: sin registro no hay respuesta ni cambio.
- En qa/prod la API no arranca con ajustes inseguros, y comprueba que su cuenta no puede alterar la auditoría.
- Logs con lista blanca: nunca preguntas, SQL, valores ni texto de excepciones.
- Literales y datos personales no entran al conocimiento reutilizable.

Diagramas: [permisos heredados](../../architecture/permisos-heredados.html) ·
[controles de calidad bancaria](../../architecture/controles-calidad-bancaria.html) ·
[componentes de la API](../../architecture/c4-componentes-api.html). Lista viva de controles: [calidad bancaria](../../calidad-bancaria.md).

## Responsabilidades
- Autenticar con el login SQL y custodiar la credencial.
- Calcular y aplicar la visibilidad en toda salida.
- Asignar roles y acotar la curación por dominio.
- Proteger la superficie HTTP (cabeceras, CSRF, cuerpo, ritmo, bloqueo de logins).
- Registrar y proteger la auditoría.
- Mantener los logs sin contenido.
- Impedir que literales y datos personales se conviertan en conocimiento.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| `VISIBILITY_SQL`, `PyodbcObjectLister` | `src/converdata/identity/visibility.py` | Lista lo que un login puede leer o ejecutar |
| `AgentRuntime.visible_ids` | `api/converdata_api/runtime.py:266` | Arma y cachea `visible_ids` por sesión |
| `SessionVault`, `Credential` | `api/converdata_api/vault.py` | Sesiones y contraseñas cifradas con Fernet |
| `SecurityMiddleware` | `api/converdata_api/security.py:138` | Cabeceras, CSRF por `Origin`, tope del cuerpo |
| `LoginThrottle` | `api/converdata_api/security.py:52` | Bloqueo por login y por origen |
| `valid_login`, `valid_host`, `valid_identifier`, `_braced` | `security.py:33`, `connector.py:48` | Nada entra a la cadena ODBC sin validar y entre llaves |
| `production_violations`, `inventory_violations` | `api/converdata_api/security.py:219` | Condiciones de arranque en qa/prod |
| Roles | `api/converdata_api/main.py:337-398` | `admin_session`, `steward_session`, `identity_trusted`, `require_curable`, `manages_rule` |
| `applying` | `api/converdata_api/main.py:400` | Audita antes de aplicar; `<evento>_failed` si falla |
| `TraceRecord`, `question_row` | `src/converdata/audit/recorder.py` | Forma de una pregunta auditada |
| `SqlServerAuditSink` | `src/converdata/audit/sqlserver.py` | Auditoría en el esquema `audit`, una transacción por pregunta |
| `FileAuditSink`, cadena | `api/converdata_api/audit.py`, `src/converdata/audit/chain.py` | JSONL diario con cadena de hashes (desarrollo) |
| Logs y métricas | `src/converdata/observability/logging.py`, `metrics.py` | Lista blanca D5; contadores sin contenido |
| Literales | `src/converdata/memory/text.py:65-87`, `src/converdata/curation.py:38` | `strip_literals`, `has_literals`, `question_template` |
| `find_pii` | `api/converdata_api/pii.py` | DUI, NIT, correo, teléfono, IBAN, tarjeta (Luhn) |

## Cómo funciona: cada control

### 1. Herencia de permisos
- **Protege**: que nadie vea metadatos de objetos que su login no puede leer, ni siquiera que existen.
- **Dónde**: `VISIBILITY_SQL` (`identity/visibility.py:14`) lista `U`/`V` con `SELECT` y `P` con `EXECUTE` en cada BD del catálogo.
  `runtime.visible_ids` lo convierte en ids físicos, solo de servidores validados en la sesión; un servidor caído no aporta nada.
  Caché de 15 min por sesión y versión del catálogo. Se aplica en el índice (`memory_store.py:122`, `_require` obliga a pasarlo), en
  el motor (ubicaciones, reglas, linaje, FKs, grafo), en el explorador (`/catalog/*`, `/assets`), en la ficha (FKs a tablas ocultas
  se quitan, `main.py:929`) y en la curación (404 en vez de 403 si el responsable no ve el activo, `main.py:381`).
- **Pruebas**: `api/tests/test_api.py::test_permissions_are_inherited`,
  `api/tests/test_security.py::test_barrido_de_la_api_sin_fugas_para_un_usuario_restringido`,
  `::test_la_visibilidad_se_vuelve_a_leer_de_sql_server`, `::test_la_ficha_de_un_activo_no_revela_tablas_ocultas_por_sus_llaves_foraneas`,
  `::test_curar_no_revela_activos_que_el_login_no_puede_ver`, `tests/test_core.py::test_visible_ids_es_obligatorio`,
  `tests/test_discover_flow_e2e.py::test_usuario_sin_permiso_no_descubre_nada_de_vbank`,
  `tests/test_graph_rag.py::test_camino_de_union_respeta_permisos`, suite `permisos` de `converdata eval gate`.

### 2. SessionVault
- **Protege**: la contraseña SQL del usuario y el token de sesión.
- **Dónde**: `vault.py`. Clave Fernet generada al arrancar (`vault.py:46`); la contraseña se descifra solo al abrir la conexión.
  Token `secrets.token_urlsafe(32)`. 8 h de inactividad, 12 h de vida, 5 sesiones por usuario (la más antigua cede). `repr` sin
  token ni contraseña. Revocación por usuario.
- **Pruebas**: `api/tests/test_security.py::test_la_sesion_caduca_por_inactividad_y_por_vida_maxima`,
  `::test_tope_de_sesiones_por_usuario_y_revocacion`, `::test_el_token_y_la_contrasena_no_salen_en_repr`,
  `::test_el_admin_revoca_las_sesiones_de_un_usuario`, `::test_toda_ruta_no_publica_exige_sesion`,
  `::test_ninguna_ruta_acepta_identidad_en_argumentos`.

### 3. SecurityMiddleware
- **Protege**: el navegador (clickjacking, sniffing, cachés), los cambios de estado frente a CSRF y el proceso frente a cuerpos enormes.
- **Dónde**: `security.py:119-212`. Cabeceras en toda respuesta, también errores: `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, CSP `default-src 'none'`, `Cache-Control: no-store`, `Permissions-Policy`, HSTS con cookie segura.
  En `POST/PUT/DELETE` con cookie y sin `Bearer`, rechaza (403) un `Origin` que no sea el propio, el de `X-Forwarded-Host`, el de CORS o
  el de `CONVERDATA_PUBLIC_URL`; sin `Origin`, rechaza `Sec-Fetch-Site: cross-site`. Cuerpo > `CONVERDATA_MAX_BODY_BYTES` → 413,
  también en transferencia por trozos. Es el middleware más externo (`main.py:311`).
- **Pruebas**: `api/tests/test_security.py::test_cabeceras_de_seguridad_en_todas_las_respuestas`,
  `::test_cambio_de_estado_con_cookie_desde_otro_origen_se_rechaza`, `::test_cuerpo_demasiado_grande_se_rechaza`.

### 4. Cadena de conexión
- **Protege**: que un login o un host añadan atributos ODBC (p. ej. `Trusted_Connection=yes`).
- **Dónde**: regex en `security.py:33-35`; `UID`/`PWD` entre llaves con `}` duplicada (`connector.py:48`); `Encrypt=yes` siempre;
  `APP=ConverData`; `readonly=True`.
- **Pruebas**: `api/tests/test_security.py::test_un_login_con_caracteres_de_cadena_odbc_se_rechaza`,
  `::test_la_cadena_de_conexion_escapa_usuario_y_contrasena`, `::test_formatos_de_host_y_base_de_datos`,
  `::test_el_inventario_rechaza_hosts_y_bases_no_validos`.

### 5. Bloqueo de logins
- **Protege**: frente a fuerza bruta y relleno de credenciales.
- **Dónde**: `LoginThrottle` con dos instancias (`main.py:263`): 5 fallos por login y 30 por origen en 10 min, bloqueo de 15 min.
  Bloqueado, ni se prueba la credencial contra SQL Server. Un servidor caído no cuenta. Un acierto limpia el login, no el origen.
  Eventos `login_failed` y `login_locked`.
- **Pruebas**: `api/tests/test_security.py::test_el_login_se_bloquea_tras_cinco_fallos`,
  `::test_el_bloqueo_expira_y_el_exito_limpia_los_fallos`, `::test_un_servidor_caido_no_cuenta_para_el_bloqueo`.

### 6. Roles
- **Protege**: administración y curación frente a usuarios sin rol, y la lectura frente a responsables.
- **Dónde** (`main.py`):
  - `data_admin`: se fija al iniciar sesión (`main.py:533-536`). Con `CONVERDATA_ADMINS_ONLY=1`, solo logins de `CONVERDATA_ADMINS`.
    Sin él, también sysadmin o `VIEW ANY DEFINITION` en algún servidor validado.
  - Responsable: por petición, de la lista de responsables por login y dominio (caché de 5 s, `api/converdata_api/curation.py:26`).
  - **Regla del servidor de producción** (`identity_trusted`, `main.py:343`): un rol dado por nombre de login (lista de admins o de
    responsables) solo cuenta si la sesión validó el login en un servidor `produccion`, cuando el inventario tiene alguno.
  - Ser responsable no da lectura: 403 solo si ya ve el activo, 404 si no; la bandeja filtra `shown` a sus dominios; una regla de otro
    dominio responde como inexistente.
  - Intentos sobre rutas de otro rol: evento `access_denied` con la plantilla de la ruta.
- **Pruebas**: `api/tests/test_security.py::test_rutas_de_administracion_y_curacion_rechazan_al_consumidor`,
  `::test_con_admins_only_ser_sysadmin_de_un_servidor_no_da_el_rol`,
  `::test_un_login_validado_solo_en_desarrollo_no_hereda_roles_por_su_nombre`,
  `::test_un_responsable_no_documenta_activos_de_otro_dominio_al_responder`,
  `::test_la_bandeja_y_la_respuesta_de_una_duda_no_filtran_otros_dominios`, `::test_una_regla_sin_activos_vigentes_solo_la_gestiona_su_dominio`.

### 7. Condiciones de arranque en qa/prod
- **Protege**: frente a un despliegue con ajustes de desarrollo.
- **Dónde**: `production_violations` (`security.py:219`) e `inventory_violations` (`security.py:272`), llamados en `create_app`. Con
  `CONVERDATA_ENV=qa|prod` exige: Windows auth apagada; `CONVERDATA_ADMINS_ONLY=1` y `CONVERDATA_ADMINS`; `audit.fail_open` falso;
  `models.yaml` con `data_mode: real` y sin rol `embed`; `CONVERDATA_DB` sin contraseña, sin `TrustServerCertificate` y sin
  `Encrypt=no`; sin demo; cookie segura; CORS solo `https://`; `CONVERDATA_MCP_HOSTS` si `/mcp` está activo; bloqueo de logins activo;
  `CONVERDATA_LOG_DIR`; sesión ≤ 8 h/12 h; webhook `https`; código de instalación si el inventario está vacío; ningún servidor con
  `trust_server_certificate`. Además `audit.verify()` debe aprobar (`main.py:250`) y `/docs`, `/redoc`, `/openapi.json` no existen.
- **Pruebas**: `api/tests/test_security.py::test_la_configuracion_de_produccion_valida_arranca`,
  `::test_la_api_no_arranca_en_produccion_con_ajustes_inseguros`, `::test_produccion_revisa_inventario_modelos_y_auditoria_del_catalogo`,
  `::test_produccion_no_arranca_si_la_cuenta_puede_modificar_la_auditoria`, `::test_el_primer_arranque_exige_el_codigo_de_instalacion`,
  `::test_autenticacion_de_windows_apagada_por_defecto`, `::test_sin_ambiente_de_produccion_no_se_exige_nada`.

### 8. Auditoría
- **Protege**: la trazabilidad de quién preguntó qué, qué vio y qué cambió.
- **Dónde**:
  - Preguntas: `finalize` del DiscoverFlow escribe un `TraceRecord`; si falla y no hay `fail_open`, la respuesta es
    `status: error` sin contenido (`src/converdata/flows/discover.py:363`).
  - SQL Server (`audit/sqlserver.py`): `audit_question`, `audit_step` y `audit_discovery` en una transacción; rollback y relanzar si
    falla. Eventos en `audit_event`; un voto además en `audit_discovery_feedback`. `verify()` falla si la cuenta puede `UPDATE`,
    `DELETE` o `ALTER` en `audit`, ejecutar `audit.usp_purge` o alterar `catalog`, `knowledge` o `curation`.
  - Archivos (`api/converdata_api/audit.py`, `audit/chain.py`): una fila JSON por línea con `prev` y `hash` = SHA-256; la primera fila
    del día enlaza con el archivo anterior; `fsync` antes de devolver. Detecta, no impide.
  - Cambios: `applying` (`main.py:400`) audita antes y deja `<evento>_failed` si falla. El login borra la sesión si su evento no se escribe.
- **Eventos que existen** (de `audit.event` y `applying` en el código): `question` (pregunta), `login`, `login_failed`,
  `login_locked`, `logout`, `setup_denied`, `access_denied`, `audit_read`, `manual_read`, `sessions_revoked`, `inventory_updated`,
  `stewards_updated`, `curation_request`, `curation_answer`, `curation_description`, `curation_dictionary_started`,
  `curation_dictionary`, `curation_rule`, `curation_rule_deleted`, `feedback`, `catalog_build_started`, `catalog_build_finished`,
  `demo_history_seeded` y los `<evento>_failed` (p. ej. `feedback_failed`). En SQL Server, los campos extra de una pregunta van a
  `question_note`. `audit_purged` lo deja `audit.usp_purge` según OP-05 (sin verificar en este repaso).
- **Pruebas**: `tests/test_discover_flow_e2e.py::test_auditoria_fail_closed`, `::test_auditoria_un_registro_por_pregunta`,
  `tests/test_audit_sqlserver.py` (transacción, rollback, sin contraseñas, permisos), `api/tests/test_audit_db.py::test_si_la_bd_no_responde_no_hay_respuesta_ni_cambios`,
  `api/tests/test_security.py::test_sin_auditoria_no_se_aplica_un_cambio_de_curacion`,
  `::test_la_auditoria_detecta_filas_modificadas_borradas_o_insertadas`, `::test_la_cadena_enlaza_un_dia_con_el_anterior`,
  `api/tests/test_api.py::test_manual_no_se_entrega_sin_auditoria`, `api/tests/test_catalog_db.py::test_un_cambio_que_falla_deja_constancia_de_que_no_se_aplico`,
  `tests/test_storage_migrations.py::test_la_api_no_puede_modificar_ni_borrar_la_auditoria`, suite `auditoria` del gate.

### 9. Logs con lista blanca
- **Protege**: que preguntas, SQL, valores o mensajes de error con datos terminen en logs o en el Visor de eventos.
- **Dónde**: `observability/logging.py`. `JsonFormatter` solo copia campos de `D5_FIELDS`, no interpola argumentos y de una excepción
  deja solo el tipo. `log_event` descarta lo demás antes de llegar al handler. Errores al Visor de eventos (origen `ConverData`).
  `MetricsMiddleware` registra plantilla de ruta, método, código y duración. `/health/metrics` solo números.
- **Pruebas**: `tests/test_observability.py` (10 pruebas), `api/tests/test_api.py::test_logs_json_sin_contenido`,
  `::test_health_metrics_cuenta_sin_contenido_y_solo_para_admin`.

### 10. Regla de literales
- **Protege**: que un documento, cuenta, fecha o correo escrito en una pregunta se guarde fuera de la auditoría.
- **Dónde**: `strip_literals` (`memory/text.py:78`): tras NFKC, toda palabra con un dígito o una arroba es literal, salvo vocabulario
  conocido (nombres del catálogo con dígitos y códigos del glosario y las reglas). `question_template` (`curation.py:38`) es lo único
  que entra a `golden_discovery` y al índice. El texto original solo se guarda si no tenía literales ni PII
  (`runtime._store_golden`). Con PII tras quitar literales, el voto cuenta pero no se aprende.
- **Pruebas**: `tests/test_curation.py::test_la_plantilla_no_conserva_literales`, `::test_el_vocabulario_del_banco_no_es_un_literal`,
  `api/tests/test_catalog_db.py::test_la_confirmacion_guarda_una_plantilla_sin_literales`,
  `::test_un_identificador_alfanumerico_tampoco_llega_a_la_plantilla`, `api/tests/test_marked_literals.py`,
  `api/tests/test_api.py::test_una_pregunta_que_es_solo_literales_no_se_aprende`.

### 11. Detector de PII
- **Protege**: que un responsable escriba datos personales en descripciones, sinónimos, reglas, notas o diccionarios (se indexan,
  los ven todos y viajan al LLM).
- **Dónde**: `find_pii` (`api/converdata_api/pii.py`), llamado por `reject_pii` en cada ruta de curación → 422 y contador `pii_rejected`.
- **Pruebas**: `api/tests/test_security.py::test_las_ediciones_de_curacion_no_aceptan_datos_personales`,
  `::test_textos_normales_de_curacion_no_se_confunden_con_datos_personales`.

### 12. Ritmo y tope de tokens
- **Protege**: el proceso y el coste de LLM frente a abuso.
- **Dónde**: `RateLimiter` por usuario (`main.py:216`), 30/min; ×4 para herramientas MCP de detalle. `TokenLedger` diario por usuario.
- **Pruebas**: `api/tests/test_security.py::test_el_limite_de_ritmo_es_por_usuario_no_por_sesion`,
  `api/tests/test_api.py::test_tope_diario_de_tokens_por_usuario`, `::test_tope_agotado_en_modo_determinista_responde_sin_ia`.

Las guardas sobre lo que genera el modelo están en [LLM](llm.md).

## Contratos y datos
- `UserContext` (`src/converdata/models/identity.py`): `user_id`, `groups`, `visible_ids`, `roles`; nunca credenciales.
- Fila de pregunta (`question_row`): `ts`, `trace_id`, `user_id`, `client`, `question`, `intent`, `status`, `confidence`,
  `databases`, `duration_ms`, `steps[]`, `discovery[]` (candidato, alternativa o relación).
- Clases de dato (F17): la pregunta completa (D2) solo vive en la auditoría; los logs solo llevan D5.

## Configuración
Las variables de seguridad están en la tabla de [ConverData-API](api.md#configuración). Las que bloquean el arranque en qa/prod son
las de la sección 7. En `config/settings.yaml`, `audit.fail_open` debe ser `false` fuera de desarrollo.

## Pruebas que lo cubren
Resumen: `api/tests/test_security.py` (42 pruebas), `tests/test_audit_sqlserver.py`, `api/tests/test_audit_db.py`,
`tests/test_observability.py`, `tests/test_curation.py`, `tests/test_storage_migrations.py`, `tests/test_gate.py`
(suites `permisos`, `inyeccion`, `guardas`, `auditoria`). Las de SQL Server real necesitan `CONVERDATA_TEST_DB`.

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md) y [calidad bancaria §5](../../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto).
- La cadena de hashes en archivos no impide truncar las últimas filas del último día; el control fuerte es SQL Server.
- `groups` siempre vacío (sin LDAP, HU-13): fragmentos con ACL de origen invisibles para todos.
- Visibilidad por objeto, sin `DENY` por columna.
- La regla del servidor de producción es una política por confirmar con el banco.
- `/health/metrics` exige sesión `data_admin`; la credencial del monitoreo está por definir.
- El detector de PII es una lista corta de patrones; no detecta nombres de personas.
- El volcado de memoria del proceso (que contiene el SessionVault) se desactiva en la instalación (HU-37), no en el código.

### Fallos encontrados al revisar el código
1. **Visibilidad que puede perder BDs enteras** (sin verificar contra SQL Server real). `PyodbcObjectLister.visible_objects`
   (`identity/visibility.py:44`) abre la conexión con `DATABASE=<bd>` y **después** consulta `HAS_DBACCESS`. Si el login no tiene
   usuario en esa BD, lo esperable es que la conexión falle; la excepción sale del generador y `runtime.visible_ids`
   (`runtime.py:284-288`) deja sin visibilidad el resto de BDs de ese servidor (se recorren en orden alfabético). Es fail-closed, pero
   un usuario podría no ver lo que sí puede leer. Ninguna prueba ejercita `PyodbcObjectLister`. El Builder hace la comprobación desde
   `master` (`src/converdata/metadata/sqlserver.py:24`).
2. **Logs de la API fuera del archivo JSON y del Visor de eventos.** `configure_logging` configura el logger `converdata`
   (`observability/logging.py:54`), pero `runtime.py` y `curation.py` de la API usan `converdata_api.*`, que no cuelga de él.
   `catalog.load_failed`, `catalog.refresh_failed`, `catalog.build_failed`, `catalog.reload_failed`, la visibilidad no disponible y el
   aviso fallido no llegan al log del monitoreo.
3. **Aclaración del modelo sin guarda.** Con ruta `clarify`, `finalize` muestra `intent.clarification.question` tal como la devolvió
   el LLM (`flows/discover.py:341`), sin `unsafe_generated_text`.
4. **Revocación auditada después de aplicarse.** `DELETE /admin/sessions/{user_id}` (`main.py:1059-1063`) y `/auth/logout` escriben
   el evento después de cerrar las sesiones; contradice "cada cambio se audita antes de aplicarse" (OP-04). No abre un acceso, pero si
   la auditoría falla la revocación queda sin registro.
5. **Descripciones sugeridas por IA sin guarda.** El enriquecimiento del build (`src/converdata/flows/catalog_build.py:162-170`) guarda
   el texto del modelo sin `unsafe_generated_text` ni `find_pii`. Se muestra como "sugerida por IA" en fichas y tarjetas.

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Cambiar la consulta de visibilidad | `VISIBILITY_SQL` y `PyodbcObjectLister` en `src/converdata/identity/visibility.py` |
| Cambiar caducidad o tope de sesiones | `SessionVault` y las variables `CONVERDATA_SESSION_*`, `CONVERDATA_MAX_SESSIONS` |
| Añadir una cabecera o regla CSRF | `security_headers` y `SecurityMiddleware._cross_site` en `security.py` |
| Añadir una condición de arranque en qa/prod | `production_violations` en `security.py` y su prueba en `test_security.py` |
| Cambiar cómo se asignan roles | `identity_trusted`, `domains_of`, bloque de roles de `login` en `main.py` |
| Añadir un evento auditado | Usar `applying(...)` en la ruta (antes de aplicar) |
| Añadir un campo permitido en logs | `D5_FIELDS` en `observability/logging.py` (revisar F17 antes) |
| Ampliar el detector de PII | `_PATTERNS` en `api/converdata_api/pii.py` |
| Cambiar qué es un literal | `_is_literal` en `src/converdata/memory/text.py` |
| Cambiar permisos exigidos a la cuenta | `VERIFY_PERMISSIONS` en `src/converdata/audit/sqlserver.py` y `db/converdata/` |

## Specs y contradicciones
Specs: [F14](../../specs/comun/F14-identity.md), [F11](../../specs/comun/F11-audit.md), [F17](../../specs/comun/F17-data-residency.md),
[OP-03](../../specs/on-premise/OP-03-identidad.md), [OP-05](../../specs/on-premise/OP-05-auditoria-observabilidad.md),
[OP-06](../../specs/on-premise/OP-06-residencia-datos.md).

La spec contradice al código en:
- F14 paso 1: credencial "por servidor" y prueba con `ORIGINAL_LOGIN()`; el código usa una sola credencial para todos los servidores
  elegidos y otra consulta. F14 paso 3: visibilidad en paralelo y `DENY` por columna; el código es secuencial y por objeto.
- OP-04 y OP-05: "cada cambio se audita antes de aplicarse"; la revocación de sesiones y el logout se auditan después.
- OP-05 §Correlación: "cada línea de log lleva el `trace_id`"; las líneas `http.request` no lo llevan, y los logs de `converdata_api.*`
  no llegan al archivo (fallo 2).
- OP-05 §Auditoría y F11: las dudas escaladas "todavía en un archivo"; con BD viven en `curation.request`.
