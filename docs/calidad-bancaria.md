# Calidad para un despliegue bancario: controles y cómo se verifican

> Creado: 2026-11-15. Actualizado: 2026-11-16 (auditoría y catálogo en la BD `ConverData`). Diagrama: [controles de una petición y compuerta de calidad](architecture/controles-calidad-bancaria.html).
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
corre los dos primeros en cada push y PR, y guarda la evidencia de la compuerta como artefacto.

Para un catálogo real: `converdata eval gate --root <directorio del catálogo> --cases <preguntas.yaml> --out reports`.
Con `--models config/models.yaml` corre con el gateway de LLM (el determinismo pasa a ser informativo).

## 2. La compuerta de calidad (`converdata eval gate`)
Código: [`src/converdata/evaluation/gate.py`](../src/converdata/evaluation/gate.py). Siete suites; todas deben aprobar.

| Suite | Qué comprueba | Criterio |
|---|---|---|
| `calidad` | Hit@1 ≥ 65 %, Hit@3 ≥ 85 %, calibración ≥ 85 %, brechas ≥ 90 %, p50 < 5 s, p95 < 10 s, y que ningún indicador ni tipo de pregunta (A–G) baje de `eval/baseline.yaml` | OP-01 D1, D2, D5 |
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

Resultado al 2026-11-16 (modo determinista): aprobado en `tests/fixtures/vbank` (25 casos, Hit@1 100 %) y
`tests/fixtures/bancos` (31 casos, Hit@1 93,1 %, Hit@3 93,1 %), con 0 fugas en 714 preguntas × usuario y 4 862 llamadas a
herramientas. Con el catálogo de BancosSQL cargado desde la BD `ConverData` (`eval gate --db --root tests/fixtures/bancos`) el
resultado es el mismo. Los dos catálogos son de prueba y sus preguntas las escribió el equipo de desarrollo (ver §5).

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
| Cabeceras de seguridad, `Cache-Control: no-store`, HSTS con HTTPS; CSRF por `Origin`; tope de 4 MB | `security.SecurityMiddleware` | `test_cabeceras_…`, `test_cambio_de_estado_con_cookie_desde_otro_origen_…`, `test_cuerpo_demasiado_grande_…` |
| Ritmo por usuario (no por sesión) y tope diario de tokens, también por `/mcp` | `main.py: check_rate, mcp_guard` | `test_el_limite_de_ritmo_es_por_usuario_…`, `test_mcp_respeta_el_tope_de_tokens_…` |
| Auditoría en la BD `ConverData`: una transacción por pregunta; la cuenta de la API inserta y lee, pero no modifica ni borra; la purga solo la ejecuta otro rol y nunca por debajo de 180 días | `converdata.audit.sqlserver`, `db/converdata/001_esquemas.sql` | `test_la_api_no_puede_modificar_ni_borrar_la_auditoria`, `test_la_purga_exige_180_dias_…`, `test_pregunta_voto_y_lecturas_quedan_en_el_esquema_audit` |
| Sin auditoría no hay respuesta ni cambio, tampoco con la BD caída | `flows/discover.py`, `main.py` | `test_si_la_bd_no_responde_no_hay_respuesta_ni_cambios`, `test_sin_auditoria_no_se_aplica_…` |
| Sin BD (desarrollo): auditoría en archivo con cadena de hashes y enlace entre días | `converdata.audit.chain`, `api/converdata_api/audit.py` | `test_la_auditoria_detecta_filas_…` |
| Catálogo en la BD con historial y autor de cada cambio; un refresco no pisa lo humano ni toca reglas, confirmaciones o responsables; dos procesos no se pisan (bloqueo y versión esperada) | `converdata.storage.catalog_repository`, `runtime.commit` | `test_una_edicion_humana_queda_en_el_historial_con_su_autor`, `test_un_refresco_del_builder_no_pisa_…`, `test_editar_sobre_un_catalogo_que_ya_cambio_da_409_y_no_aplica` |
| Roles de BD de mínimo privilegio: el Builder solo toca lo que deriva de los metadatos y no lee preguntas ni confirmaciones; el auditor solo lee `audit`; ni la API ni el Builder pueden apagar el historial ni bajar la versión | `db/converdata/001_esquemas.sql` | `test_el_builder_solo_toca_lo_que_deriva_de_los_metadatos`, `test_la_cuenta_del_builder_refresca_sin_leer_ni_tocar_lo_curado`, `test_la_api_no_puede_reescribir_el_historial_ni_la_version`, `test_el_auditor_solo_lee_la_auditoria` |
| La cuenta de la API, con su rol real, pasa `verify` (esquema y cada tabla de `audit`, la purga y el historial) | `audit.sqlserver.verify` | `test_la_cuenta_de_la_api_publica_carga_audita_y_pasa_verify` |
| Una edición de curación es atómica: comprobaciones, cambio y publicación bajo un solo candado y sobre el catálogo vigente; si la publicación falla, el cambio se descarta | `runtime.editing`, `runtime.commit` | `test_dos_ediciones_a_la_vez_…`, `test_si_la_publicacion_falla_…`, `test_si_otro_proceso_publica_durante_la_edicion_da_409_y_no_aplica` |
| Votos, solicitudes y ediciones se auditan antes de aplicarse; un voto escribe una sola fila | `runtime.record_feedback`, `main.py` | `test_pregunta_voto_y_lecturas_…`, `test_un_voto_escribe_una_sola_fila_y_sube_la_version` |
| Una pregunta que parece llevar datos personales no se guarda como confirmación; las confirmaciones no se exportan a git | `runtime.record_feedback`, `write_snapshot` | `test_una_pregunta_con_datos_personales_no_se_guarda_como_confirmacion`, `test_la_exportacion_para_git_no_lleva_preguntas` |
| Las pruebas nunca corren contra una BD existente | `conftest.py`, `storage.connection.names_database` | `test_las_pruebas_no_aceptan_una_cadena_que_nombre_una_bd` |
| Se auditan además: accesos denegados, bloqueos, lectura de la auditoría, cambios de inventario con host anterior y nuevo, revocaciones | `main.py` | `test_rutas_de_administracion_…`, `test_el_primer_arranque_…` |
| Un responsable solo documenta activos de sus dominios, y sin datos personales (DUI, NIT, correo, teléfono, tarjeta) | `main.py: curation_answer`, `pii.py` | `test_un_responsable_no_documenta_…`, `test_las_ediciones_de_curacion_no_aceptan_datos_personales` |
| Nombres de objetos con `.`, `/`, `\`, `:` no entran al catálogo ni escriben fuera de él | `builder.unsafe_name`, `object_path` | `test_el_build_omite_…`, `test_un_objeto_no_se_escribe_fuera_del_catalogo` |
| Texto del LLM con enlaces, HTML o correos se reemplaza por el determinista; el contenido del catálogo va delimitado en los prompts | `engine.unsafe_generated_text`, `llm/nodes.py` | `test_texto_generado_…`, suite `guardas` |
| Errores internos: al público solo un mensaje genérico; en los logs solo el tipo de excepción | `runtime.reload`, `/setup/status` | `test_el_error_de_carga_del_catalogo_no_se_publica` |

## 4. Configuración obligatoria en qa y prod
Con `CONVERDATA_ENV=qa` o `prod` la API **no arranca** si algo de esto falta (`security.production_violations`,
`test_la_api_no_arranca_en_produccion_con_ajustes_inseguros`):

| Variable | Valor |
|---|---|
| `CONVERDATA_DEMO` | sin definir |
| `CONVERDATA_COOKIE_SECURE` | `1` (HTTPS) |
| `CONVERDATA_CORS_ORIGINS`, `CONVERDATA_PUBLIC_URL` | la URL `https://` del sitio |
| `CONVERDATA_MCP_HOSTS` | nombre del servidor (o `CONVERDATA_MCP=0`) |
| `CONVERDATA_ALLOW_WINDOWS_AUTH` | sin definir |
| `CONVERDATA_ADMINS_ONLY=1`, `CONVERDATA_ADMINS` | logins de los administradores de datos |
| `CONVERDATA_SETUP_TOKEN` | secreto del instalador, mientras no exista inventario |
| `CONVERDATA_LOG_DIR` | directorio de logs |
| `CONVERDATA_DB` | cadena ODBC de la BD `ConverData`, sin contraseña (`Trusted_Connection=yes`), con `Encrypt=yes` y sin `TrustServerCertificate`, y con una cuenta que solo pertenezca a `converdata_app` (la API comprueba al arrancar que no puede modificar ni borrar la auditoría) |
| `config/models.yaml` | `data_mode: real`; sin rol `embed` |
| Inventario y `config/settings.yaml` | sin `trust_server_certificate`; sin `audit.fail_open` |

Además `/docs` y `/openapi.json` dejan de publicarse. Opcionales: `CONVERDATA_SESSION_MAX_AGE_S`, `CONVERDATA_MAX_SESSIONS`,
`CONVERDATA_LOGIN_MAX_FAILURES`, `CONVERDATA_LOGIN_LOCKOUT_S`, `CONVERDATA_TRUST_PROXY` (detrás de un proxy propio),
`CONVERDATA_VISIBILITY_TTL_S`, `CONVERDATA_MAX_BODY_BYTES`, `CONVERDATA_SESSION_TTL_S`, `CONVERDATA_LOGIN_WINDOW_S`,
`CONVERDATA_LOGIN_IP_MAX_FAILURES`.

⚠️ Sin `CONVERDATA_ENV` el valor es `dev` y nada de esto se exige: el instalador debe fijarlo (HU-37).

La web se compiló el 2026-11-16 (`npm --prefix web ci && npm --prefix web run build`, sin errores de tipos); no se probó en un
navegador en esta sesión.

## 5. Lo que todavía no está resuelto
Nada de esta lista se cubre con el código actual. Cada punto necesita infraestructura, una decisión o trabajo aparte.

| Pendiente | Por qué importa | Qué hace falta |
|---|---|---|
| Parte de la curación sigue en archivos del servidor: responsables por login, solicitudes escaladas (contienen la pregunta), votos, registro de diccionarios e inventario de la API | No tienen historial ni el respaldo de la BD, y un disco nuevo los pierde (sin responsables nadie puede curar; sin votos, un par rechazado puede reactivarse) | Migración `002` y paso de `CurationStore` a la BD (plan §3, bloque C2) |
| La API trabaja sobre una copia del catálogo en disco, que incluye las preguntas confirmadas | OP-06 pide no escribir datos a disco; hoy la protege solo la ACL del directorio | Que la curación escriba filas en la BD y el índice se cargue directo de ella (bloque C2) |
| La confirmación guarda la pregunta normalizada, no anonimizada | Una pregunta con un nombre propio queda en `knowledge` y en el índice. Mitigado: no se guarda si coincide con los cinco patrones de datos personales; el Builder no la lee; no se exporta | Sustituir literales por marcadores y guardar el original en `golden` (bloque C2) |
| La fecha de un registro de auditoría la puede fijar quien lo inserta | Una cuenta comprometida podría antedatar sus filas para que caigan en la siguiente purga | Columna `recorded_at` con valor por defecto y purga por ella (migración `002`) |
| Los comandos de la CLI que escriben en la BD no tienen pruebas automáticas | `db migrate`, `catalog publish|export|build --db` y `audit purge` se probaron a mano | Pruebas de la CLI contra la BD desechable |
| La purga de 180 días existe (`audit.usp_purge`, `converdata audit purge`) pero no está programada | OP-05 | Tarea programada con una cuenta del rol `converdata_maintenance` (HU-37) |
| Las pruebas contra SQL Server no corren en la CI | Una regresión en el DDL o en los adaptadores no se vería en un PR | Servicio de SQL Server en el workflow, o ejecutarlas a mano antes de cada entrega |
| El DDL se probó en SQL Server 2022, no en 2016 | PRD §13, decisión 10 dice "2016 o posterior" | Probar en la versión de la instancia del piloto |
| El dueño de la BD (`dbo`, DBA) sí puede modificar la auditoría | Es inherente a SQL Server; el control cubre a la cuenta de la aplicación | SQL Server Audit sobre el esquema `audit`, o exportar a un SIEM, si Seguridad lo exige |
| Gateway de LLM sin probar con Bedrock ni NIM | La compuerta solo corrió en modo determinista; con un LLM real hay que repetir `inyeccion` y `guardas` | HU-35 y `eval gate --models` |
| Set de evaluación de 56 preguntas escritas por el equipo | Sesgo de ajuste: los porcentajes no predicen el uso real | 50–80 preguntas de usuarios del piloto (plan §3 paso 4) |
| La vista Curación no aplica `visible_ids` al responsable, y distingue "no existe" de "es de otro dominio" | F14 dice que no hay modo de catálogo abierto | Decidir si el responsable está exento y documentarlo, o filtrar |
| Lecturas sin auditar: `/catalog/*`, `/assets` y herramientas MCP distintas de `discover` | Trazabilidad de quién consultó qué | Decidir el nivel de detalle y su volumen |
| Un solo "✖" de un consumidor retira una confirmación de usuarios | Un usuario puede degradar respuestas de otros | Regla de votos |
| Cada voto vuelve a publicar la copia de trabajo completa y recarga todo el índice | Coste; hoy solo lo acota el límite de ritmo | Escribir solo la confirmación y actualizar solo la colección `golden` |
| Dependencias sin fijar (`>=`), imagen por etiqueta, sin SBOM | Cadena de suministro | Lock con hashes, digest, escaneo |
| El token de sesión también viaja en el cuerpo del login | Lo necesita el cliente MCP; debilita `HttpOnly` si la web lo guarda | Emitirlo solo a petición |
| Sesiones, bloqueos y topes en memoria de un proceso | Un solo worker; un reinicio cierra las sesiones y borra los contadores | Aceptado en OP-03; revisar si se pide alta disponibilidad |
| Detector de datos personales de cinco patrones | No cubre nombres ni direcciones | Presidio (HU-26) |
| Batería de inyección sin revisar por Seguridad del banco | ⚠️ S7 | Ampliarla con ellos |
| Prueba de penetración, revisión de IIS/TLS, cuentas gMSA, SSO | Fuera del código | Con el banco |
