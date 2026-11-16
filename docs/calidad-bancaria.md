# Calidad para un despliegue bancario: controles y cómo se verifican

> Creado: 2026-11-15. Diagrama: [controles de una petición y compuerta de calidad](architecture/controles-calidad-bancaria.html).
> Specs relacionadas: [OP-03 identidad](specs/on-premise/OP-03-identidad.md), [OP-04 interfaces](specs/on-premise/OP-04-interfaces.md),
> [OP-05 auditoría](specs/on-premise/OP-05-auditoria-observabilidad.md), [OP-06 residencia](specs/on-premise/OP-06-residencia-datos.md).

Este documento dice qué controla ConverData, dónde está cada control en el código, qué prueba lo fija y **qué falta** para
operar en un banco. Lo que falta está en [§5](#5-lo-que-todavía-no-está-resuelto): no se debe dar por cubierto.

## 1. Cómo verificar que todo funciona
```bash
.venv/Scripts/python -m pytest -q                                   # controles, capas y flujo de punta a punta
.venv/Scripts/python -m converdata.cli eval gate --out reports      # compuerta de calidad sobre los dos catálogos de prueba
.venv/Scripts/python -m converdata.cli audit verify --dir data/audit  # cadena de hashes de la auditoría en archivo
```
Los tres salen con código distinto de 0 si algo falla. La CI ([`.github/workflows/calidad.yml`](../.github/workflows/calidad.yml))
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

Resultado al 2026-11-15 (modo determinista): aprobado en `tests/fixtures/vbank` (25 casos, Hit@1 100 %) y
`tests/fixtures/bancos` (31 casos, Hit@1 93,1 %, Hit@3 93,1 %), con 0 fugas en 714 preguntas × usuario y 4 862 llamadas a
herramientas. Los dos catálogos son de prueba y sus preguntas las escribió el equipo de desarrollo (ver §5).

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
| Auditoría en archivo con cadena de hashes y enlace entre días; se escribe antes de aplicar un cambio | `converdata.audit.chain`, `api/converdata_api/audit.py` | `test_la_auditoria_detecta_filas_…`, `test_sin_auditoria_no_se_aplica_…` |
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
| `config/models.yaml` | `data_mode: real` |
| Inventario y `config/settings.yaml` | sin `trust_server_certificate`; sin `audit.fail_open` |

Además `/docs` y `/openapi.json` dejan de publicarse. Opcionales: `CONVERDATA_SESSION_MAX_AGE_S`, `CONVERDATA_MAX_SESSIONS`,
`CONVERDATA_LOGIN_MAX_FAILURES`, `CONVERDATA_LOGIN_LOCKOUT_S`, `CONVERDATA_TRUST_PROXY` (detrás de un proxy propio),
`CONVERDATA_VISIBILITY_TTL_S`, `CONVERDATA_MAX_BODY_BYTES`.

⚠️ Sin `CONVERDATA_ENV` el valor es `dev` y nada de esto se exige: el instalador debe fijarlo (HU-37).

## 5. Lo que todavía no está resuelto
Nada de esta lista se cubre con el código actual. Cada punto necesita infraestructura, una decisión o trabajo aparte.

| Pendiente | Por qué importa | Qué hace falta |
|---|---|---|
| La auditoría sigue en archivos JSONL | La cadena de hashes detecta manipulación, pero no la impide; quien pueda escribir el archivo puede truncar las últimas filas. `SqlServerAuditSink` (solo `INSERT`) existe y nadie lo instancia | HU-20 con SQL Server 2025. Mientras tanto, exportar a diario el hash de cabeza de `audit verify` a un SIEM o WORM |
| Sin retención de 180 días ni purga de la auditoría | OP-05 | Tarea programada |
| Catálogo y `SqlServerVectorStore` sin validar en SQL Server 2025 | Persistencia de producción | HU-04, HU-05 |
| Gateway de LLM sin probar con Bedrock ni NIM | La compuerta solo corrió en modo determinista; con un LLM real hay que repetir `inyeccion` y `guardas` | HU-35 y `eval gate --models` |
| Set de evaluación de 56 preguntas escritas por el equipo | Sesgo de ajuste: los porcentajes no predicen el uso real | 50–80 preguntas de usuarios del piloto (plan §3 paso 4) |
| La vista Curación no aplica `visible_ids` al responsable, y distingue "no existe" de "es de otro dominio" | F14 dice que no hay modo de catálogo abierto | Decidir si el responsable está exento y documentarlo, o filtrar |
| Lecturas sin auditar: `/catalog/*`, `/assets` y herramientas MCP distintas de `discover` | Trazabilidad de quién consultó qué | Decidir el nivel de detalle y su volumen |
| Un solo "✖" de un consumidor retira una confirmación de usuarios | Un usuario puede degradar respuestas de otros | Regla de votos |
| Cada voto recarga todo el índice | Coste; hoy solo lo acota el límite de ritmo | Actualizar solo la colección `golden` |
| Dependencias sin fijar (`>=`), imagen por etiqueta, sin SBOM | Cadena de suministro | Lock con hashes, digest, escaneo |
| El token de sesión también viaja en el cuerpo del login | Lo necesita el cliente MCP; debilita `HttpOnly` si la web lo guarda | Emitirlo solo a petición |
| Sesiones, bloqueos y topes en memoria de un proceso | Un solo worker; un reinicio cierra las sesiones y borra los contadores | Aceptado en OP-03; revisar si se pide alta disponibilidad |
| Detector de datos personales de cinco patrones | No cubre nombres ni direcciones | Presidio (HU-26) |
| Batería de inyección sin revisar por Seguridad del banco | ⚠️ S7 | Ampliarla con ellos |
| Prueba de penetración, revisión de IIS/TLS, cuentas gMSA, SSO | Fuera del código | Con el banco |
| La web no se compiló en esta rama | El campo "Código de instalación" del login no se verificó con `tsc` | `npm --prefix web ci && npm --prefix web run build` |
