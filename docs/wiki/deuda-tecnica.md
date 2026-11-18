# Deuda técnica

Actualizado el 2026-11-17.

Este registro tiene **66 deudas abiertas**: 8 de gravedad alta, 30 media y 28 baja. Las 13 de la §3.9 salieron al escribir las páginas de componentes de la wiki (DT-57 y DT-67 ya están cerradas) y DT-71 salió al cerrar DT-03. Cada una se comprobó en el código de la
rama `feat/congruencia-y-persistencia` (árbol de trabajo del 2026-11-17, con cambios sin commit en `route.ts`, `next.config.ts`, `session-provider.tsx` y `visibility.py`: sus números de línea pueden moverse). Lo ya resuelto está en la §4 y no debe reabrirse.

Las 5 que más importan:

1. **DT-39 · 83 de las 458 pruebas (las de SQL Server) no corren en la CI.** Con 5 personas tocando a la vez `storage/`,
   `audit/` y `db/`, una regresión de esquema o de permisos entra sin que nadie la vea.
2. **DT-04 · La fecha de un registro de auditoría la pone quien lo inserta.** Una cuenta de la API comprometida puede
   antedatar filas para que la purga las borre. Ataca la regla "auditoría antes de responder".
3. **DT-30 · Nada se ha medido con el LLM real.** Las suites `inyeccion` y `guardas` solo corrieron en modo determinista y
   Bedrock no se ha probado de punta a punta. Bloquea el piloto.
4. **DT-44 · No hay instalación para Windows Server.** Sin los scripts de `deploy/windows/` no hay piloto.
5. **DT-02 · El bloqueo de login por origen sigue sin activarse detrás de IIS.** El código ya reenvía la dirección del
   cliente, pero con `TRUST_FORWARDED_FOR` y `CONVERDATA_TRUST_PROXY` apagadas un solo atacante puede bloquear el login de todos.
   Está mitigada (Media): falta activarla y probarla en la instalación del bloque F.

El 2026-11-17 se cerraron DT-01, DT-03, DT-08, DT-57 y DT-67 (§4). DT-02 bajó de Alta a Media.

## 2. Cómo leer el registro

| Campo | Valores |
|---|---|
| **Gravedad** | **Alta**: bloquea el piloto o afecta seguridad o datos. **Media**: frena al equipo o arriesga la calidad. **Baja**: limpieza |
| **Esfuerzo** | **S**: hasta 1 día. **M**: hasta 1 semana. **L**: más de 1 semana |
| **Evidencia** | `ruta:línea` comprobada el 2026-11-17. "Sin verificar" dice qué faltó |
| **Plan / HU** | Bloque de `docs/PLAN-desarrollo.md` §3 o historia de `docs/backlog/on-premise.md`, si la hay |

Una deuda marcada **(nueva)** no estaba en ningún documento del repositorio.

## 3. Deudas abiertas

### 3.1 Seguridad y datos

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-02 | **(nueva, mitigada)** El bloqueo de 30 fallos "por origen" ve una sola IP, la del proxy, mientras `TRUST_FORWARDED_FOR` (web) y `CONVERDATA_TRUST_PROXY` (API) sigan apagadas. El proxy ya reenvía la dirección del cliente (último valor de `X-Forwarded-For`) y la API ya la usa, pero ninguna de las dos se ha activado ni probado detrás de un proxy inverso | `web/src/app/api/[...path]/route.ts:8-10`, `28-31`; `api/converdata_api/main.py:330-335`, `481-482`, `526` | Con las variables apagadas (el valor por defecto, porque sin un proxy propio delante el cliente escribe la cabecera), 30 contraseñas erróneas de cualquiera bloquean el login de todos durante 15 min (`login_lockout_s`) | Media | S | Activar las dos variables en la instalación detrás de IIS y probarlo de punta a punta con dos orígenes distintos | OP-03, OP-07, bloque F, HU-37 |
| DT-04 | La fecha (`ts`) de un registro de auditoría la puede fijar quien inserta | `src/converdata/audit/sqlserver.py:30`, `39`, `41` (`COALESCE(?, SYSUTCDATETIME())`); la purga borra por `ts` (`db/converdata/001_esquemas.sql:295-302`) | Una cuenta de la API comprometida antedata filas para que caigan en la purga | Alta | M | Migración `003`: columna `recorded_at` con valor por defecto y sin permiso de escritura; la purga usa esa columna | Sin bloque (reparto: Dev 2 con Dev 1) |
| DT-05 | El detector de datos personales solo reconoce DUI, NIT, correo, teléfono, IBAN y tarjeta. La plantilla de las confirmaciones quita palabras con dígitos o arroba, pero no nombres, texto entre comillas ni grupos de letras de un código partido | `api/converdata_api/pii.py:12-19`; `src/converdata/memory/text.py:78-90` | Una pregunta con un nombre propio llega a `knowledge.golden_discovery` y al índice. Lo que escribe un responsable puede llevar un nombre o una dirección | Alta | L | Presidio o equivalente para la redacción, revisión del responsable antes de reutilizar | Bloque E, HU-26 |
| DT-06 | **(nueva)** "`CONVERDATA_LOG_DIR` es obligatorio en qa y prod" no se exige nunca: `from_env` pone `data/logs` por defecto, así que `log_dir` nunca es `None` | `api/converdata_api/settings.py:80`; `security.py:263`; la prueba fija `log_dir=None` a mano (`api/tests/test_security.py:341`) | En producción los logs pueden acabar en un directorio relativo al proceso, fuera del monitoreo, sin que la API se niegue a arrancar | Media | S | Quitar el valor por defecto en qa y prod, o exigir una ruta absoluta; probar desde variables de entorno | OP-05 |
| DT-07 | **(nueva)** Si `CONVERDATA_MODELS` apunta a un archivo que no existe, se ignora sin avisar y el flujo pasa a modo determinista, también en qa y prod | `settings.py:82`; `security.py:231` solo revisa el archivo si existe | Un error de ruta en la instalación apaga el LLM sin que nadie lo note | Media | S | Si la variable está definida y el archivo no existe, error al arrancar (o violación en qa y prod) | HU-35, HU-37 |
| DT-09 | El token de sesión viaja también en el cuerpo del login. La web no lo usa (solo la cookie); lo necesita el cliente MCP | `main.py:560-561`; ninguna referencia a `.token` en `web/src` | Debilita la cookie `HttpOnly`: un script inyectado en la página podría leerlo de la respuesta | Media | S | Emitirlo solo si se pide (por ejemplo `?client=mcp`) | Reparto: Dev 5 |
| DT-10 | Lecturas sin auditar: `/catalog/*`, `/assets/*` y las herramientas MCP distintas de `discover` | `main.py:872-921`; `src/converdata/application/discovery.py:186-187` | No queda traza de quién consultó qué ficha | Media | S | Decidir el nivel de detalle (PRD §13, pregunta 8) y añadir el evento | Bloque D |
| DT-11 | Dentro de sus dominios, un responsable ve en la cola de revisión y edita descripciones de activos que su login no puede leer | `main.py:748-749` (solo `can_curate`); `main.py:385-387` | Contradice F14 ("no hay modo de catálogo abierto") salvo que el banco lo acepte | Media | S | Decisión del banco (PRD §13, pregunta 7); después filtrar por `visible_ids` o documentar la excepción | Reparto: Dev 5 |
| DT-12 | El dueño de la BD (`dbo`, DBA) sí puede modificar la auditoría | Inherente a SQL Server; el `DENY` de `db/converdata/001_esquemas.sql:322` cubre solo a `converdata_app` | La integridad depende de la confianza en el DBA | Media | M | SQL Server Audit sobre el esquema `audit` o envío a un SIEM, si Seguridad lo exige | HU-37 |
| DT-13 | `job.error` del build guarda el texto de la excepción y de los servidores que fallaron | `api/converdata_api/runtime.py:449`, `460` | Un mensaje de conexión puede traer host, instancia o login. Solo lo ve un `data_admin` en `GET /admin/catalog/build` | Baja | S | Guardar solo el tipo de error, o aceptarlo para el administrador | — |
| DT-14 | Las estadísticas BM25 (`df`, `avgdl`) se calculan sobre todo el catálogo, no sobre lo visible | `src/converdata/memory/memory_store.py:46-61` | La confianza de un usuario varía hasta ~0,006 según existan objetos que no ve. No aparece ningún nombre oculto | Baja | M | Estadísticas por conjunto visible, o aceptar el riesgo por escrito | — |
| DT-15 | Dos preguntas que solo difieren en un código que el glosario no conoce comparten plantilla y confirmación | `src/converdata/curation.py:38`; `memory/text.py:78` | Una confirmación hecha para una norma da el bonus a la pregunta por otra | Baja | S | Cargar los códigos en el glosario o en las reglas (`KnowledgeBase.codes`) | Bloque E |

### 3.2 Arquitectura y código

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-16 | `create_app` es una sola función de ~840 líneas: 46 rutas, dependencias, reglas de rol, curación, métricas y administración como funciones anidadas | `api/converdata_api/main.py:236-1075` | Es el archivo donde chocan los carriles 2, 3, 4 y 5. Las reglas de rol (`domains_of`, `require_curable`, `manages_rule`) no se pueden probar ni reutilizar fuera de la app | Media | M | `routers/` por área con `APIRouter` y dependencias en un módulo propio. Primer encargo del Dev 5 | Reparto: Dev 5 |
| DT-17 | **(nueva)** `app = create_app()` corre al importar el módulo | `main.py:1078`; lo importan 5 archivos de `api/tests` (p. ej. `api/tests/test_api.py:16`) | Importar `main` en una prueba lee `.env`, crea `data/audit` y `data/logs` en el directorio actual y, con `CONVERDATA_DB` definida, se conecta a esa BD | Media | S | Arrancar con `uvicorn --factory converdata_api.main:create_app` (`api/Dockerfile:52`) y quitar la línea | — |
| DT-18 | La API no pasa por `DiscoveryTools`: `/discover` llama al `DiscoverService` y la ficha del activo reimplementa el filtrado de permisos. **(nueva: la duplicación)** | `main.py:598`, `615`; `main.py:923-949` frente a `application/discovery.py:113-148` y `discovery/engine.py:725-731` | Dos copias de la regla F14 (llaves foráneas, reglas, copias): un arreglo en una no llega a la otra | Media | M | Que la API use `DiscoveryTools` para descubrir y para la ficha | HU-14, HU-16 |
| DT-19 | La política de sincronización con la BD y la orquestación de votos son lógica de aplicación que vive en la API | `runtime.py:135-210` (`_pull`, `refresh`, `editing`, `_written`); `runtime.py:321-383` (`record_feedback`, `steward_golden`) | La CLI y el MCP no pueden reutilizarla; la regla de capas no la protege | Media | M | Caso de uso en `converdata.application` | Reparto: Dev 5 |
| DT-20 | `tests/test_architecture.py` solo analiza `src/converdata` | `tests/test_architecture.py:16`, `65` | La API puede importar lo que quiera sin que falle una prueba | Media | S | Extender la prueba a `api/converdata_api` con su capa (integración) | Reparto: Dev 5 |
| DT-21 | **(nueva)** Cada recarga del catálogo crea un `LLMGateway` nuevo y con él un circuit breaker vacío | `runtime.py:239-243`; `src/converdata/llm/gateway.py:66`, `156` | Tras cada edición de curación o voto, un proveedor caído vuelve a recibir peticiones: el corte de 5 min deja de valer | Media | S | Crear el gateway una vez por proceso y pasarlo a cada `build_service` | HU-35 |
| DT-22 | **(nueva)** `discovery/engine.py` tiene 1 052 líneas: recuperación, puntuación, roles de columna, caminos de unión, alternativas, guardas de texto y armado del candidato | `src/converdata/discovery/engine.py:116`, `381-441`, `822`, `886`, `988-1025` | Todo cambio de descubrimiento toca el mismo archivo; las guardas de seguridad del texto quedan mezcladas con el orden | Baja | M | Partir en módulos (`retrieval`, `scoring`, `paths`, `guards`) sin cambiar lógica y con la compuerta igual | Reparto: Dev 4 |
| DT-23 | **(nueva como deuda)** Nombres históricos: el puerto `VectorStore` y su adaptador `InMemoryVectorStore` son un índice léxico BM25; `memory` se presenta como "Memoria semántica"; `search_catalog` se llama "búsqueda híbrida"; la spec es `F02-semantic-memory` | `src/converdata/memory/base.py:1-2`, `48`; `memory/memory_store.py:65`; `memory/__init__.py:1`; `application/discovery.py:187` | Un desarrollador nuevo busca vectores o embeddings que no existen | Baja | S | Renombrar a `SearchIndex` / `LexicalIndex` con un alias temporal | — |
| DT-24 | Capas residuales: `catalog.store` mezcla el modelo con la carga de YAML; `write_snapshot` escribe YAML desde el dominio; `PyodbcObjectLister` vive en el dominio; `flows.catalog_build` lee el linaje anterior del directorio de salida | `src/converdata/catalog/store.py:171`, `202`; `builder/catalog_builder.py:270`; `identity/visibility.py:36`; `flows/catalog_build.py:178-181` | Ninguna rompe hoy; crecen si se añaden formatos | Baja | M | Mover a un adaptador de archivos en infraestructura cuando se toquen | — |
| DT-25 | La CLI no usa `open_stores`: construye los adaptadores de SQL Server por su cuenta | `src/converdata/cli.py:227-229`, `234-237`, `255-257`, `303-307`, `429-431` | Dos formas de abrir los mismos almacenes; un cambio de conexión hay que hacerlo dos veces | Baja | S | Usar `bootstrap.open_stores` en la CLI | Reparto: Dev 5 |
| DT-26 | **(nueva)** No hay linter ni verificador de tipos para Python (ni configuración ni paso en la CI). Hay imports sin uso | `pyproject.toml` (sin `ruff`/`mypy`); `.github/workflows/calidad.yml:33-36`; `src/converdata/curation.py:18` (`re`); `memory/memory_store.py:24` (`KnowledgeKind`) | Estilo e imports muertos dependen de la revisión manual. La web sí tiene `tsc` y `eslint` | Baja | S | `ruff` (y luego `mypy`) en `dev.lock` y en el trabajo `backend` | — |
| DT-27 | **(nueva)** `api/converdata_api/curation.py` mezcla la curación (responsables, dudas) con el tablero de métricas | `api/converdata_api/curation.py:104-127` (`demand_by_asset`, `percentile`, `metrics_report`) | El bloque D va a crecer dentro de un módulo de curación | Baja | S | Mover las métricas a su propio módulo al empezar el bloque D | Bloque D |
| DT-28 | **(nueva)** `demo_history` vale `False` en la clase y `True` al leerse del entorno | `settings.py:39` frente a `settings.py:92` | Una prueba y la API arrancada se comportan distinto con la misma configuración | Baja | S | Un solo valor por defecto | — |

### 3.3 Descubrimiento y calidad medida

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-29 | Los sets de evaluación (89 casos de descubrimiento y 25 de reporte) los escribió el equipo, y los cambios del 2026-11-17 se ajustaron con ellos | `tests/fixtures/bancos/eval/discovery.yaml`, `tests/fixtures/vbank/eval/discovery.yaml`, `tests/fixtures/bancos/eval/reportes.yaml` | Los porcentajes (98,0 % y 96,2 %) no predicen el uso real | Alta | L | 50–80 preguntas de usuarios validadas por un experto (⛔ steward) | Bloque G, HU-33 |
| DT-30 | Todo se midió sin LLM. Bedrock sin probar de punta a punta; `inyeccion` y `guardas` sin modelo real; la batería de inyección sin revisar por Seguridad | `src/converdata/evaluation/gate.py` (modo determinista por defecto); `config/models.example.yaml` | Sin esto no se puede abrir el piloto con datos reales | Alta | L | `eval gate --models` con Bedrock y revisión de la batería con Seguridad (⛔ cuenta AWS, S7) | Bloque G, HU-35, HU-36 |
| DT-31 | Dos casos sin candidatos: B14 (BancosSQL) y eng-06 (VBank). Una entidad con un calificativo que otra tabla sí conoce | Ejecución de `eval discovery` el 2026-11-17: `ERR B14` y `ERR eng-06`; `tests/fixtures/bancos/eval/discovery.yaml:35`, `tests/fixtures/vbank/eval/discovery.yaml:31` | El usuario recibe una brecha cuando la tabla existe | Media | M | Solo si el set real lo pide; medir con preguntas que no se usaron para ajustar | Reparto: Dev 4 |
| DT-32 | **(nueva)** La calibración (D2: ≥ 85 % de las respuestas con confianza ≥ 0,8 son correctas) no se mide en BancosSQL: ninguna respuesta llega a 0,8 (n = 0) y la suite la marca como informativa | `src/converdata/evaluation/gate.py:52`, `233-234`; salida de `eval discovery --root tests/fixtures/bancos`: "Calibración≥0.8 0.0 % (n=0)" | El criterio D2 descansa en 6 respuestas de VBank. `calidad-bancaria.md` §2 lo presenta como exigido | Media | M | Casos con respuesta segura en BancosSQL, o revisar el umbral 0,8 con la escala real de confianza | OP-01 D2 |

### 3.4 Persistencia y BD

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-33 | La purga de 180 días existe pero nada la programa | `db/converdata/001_esquemas.sql:280-308`; `cli.py:268`; no existe `deploy/` | La retención de OP-05 no se cumple sola; las dudas escaladas con texto se acumulan | Alta | S | Tarea programada con una cuenta de `converdata_maintenance` | Bloque F, HU-24, HU-37 |
| DT-34 | Cada escritura de curación vuelve a cargar el catálogo entero de la BD y reconstruye el índice (síncrono tras una edición o el voto de un responsable; en segundo plano tras un voto de usuario) | `runtime.py:173-186`, `188-210`, `350-353` | Coste en catálogos grandes; con varios responsables editando, recargas en serie bajo el mismo candado | Media | M | Actualizar solo lo que cambió (colección `golden`, objeto editado) | Reparto: Dev 4 |
| DT-35 | **(nueva)** Las métricas y la cola de revisión leen la auditoría en memoria con topes fijos: 20 000 filas de todos los tipos para `/admin/metrics` y 5 000 preguntas para la demanda | `main.py:745`, `865` | Con 15 usuarios durante 30 días el tope se puede alcanzar y el tablero queda truncado sin aviso | Media | M | Vistas SQL del scorecard y agregados en la BD | Bloque D, HU-23 |
| DT-36 | El DDL se probó en SQL Server 2022, no en 2016. Un barrido de `db/converdata/*.sql` no encontró funciones posteriores a 2016; `ISJSON` exige nivel de compatibilidad 130 | `db/converdata/001_esquemas.sql`, `002_curacion.sql` | La decisión 10 del PRD promete 2016 o posterior | Media | S | Ejecutar las pruebas `sqlserver` en la versión de la instancia del piloto | Bloque F |
| DT-37 | Un fallo de escritura de la auditoría deja `audit.write_failed` en el log, pero no hay alerta | `src/converdata/flows/discover.py:367` | Fail-closed sin alerta: los usuarios dejan de recibir respuestas y nadie se entera | Media | S | Regla de alerta en el monitoreo del banco y prueba en el Visor de eventos | HU-37 |
| DT-38 | En modo demo con BD queda un marcador `.demo_history.json` en `curation_dir` | `runtime.py:453-454` | Es el único archivo que la API escribe con BD; la demo no se admite en qa ni prod | Baja | S | Llevarlo a la BD si la demo debe correr sin disco | — |

### 3.5 Pruebas y CI

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-39 | Las pruebas marcadas `sqlserver` (83 de 458, comprobado con `pytest --collect-only`) se omiten en la CI | `.github/workflows/calidad.yml:16-43` (sin servicio de SQL Server); `conftest.py:41-45` | Migraciones, roles, auditoría, catálogo, curación y la prueba de literales en BD solo se prueban a mano | Alta | M | Servicio de SQL Server en el trabajo `backend` con `CONVERDATA_TEST_DB` | Bloque F, reparto: Dev 1 |
| DT-40 | **(nueva)** La web no tiene ninguna prueba (ni unitaria ni de punta a punta) | Ningún archivo de prueba en `web/`; `web/package.json:5-10` sin script `test` | Regresiones de pantallas y del proxy solo se ven a mano; DT-01 a DT-03 pasaron sin que nada fallara | Media | M | Playwright contra la API en modo demo para login, chat, curación y cabeceras del proxy | Reparto: Dev 5 |
| DT-41 | La prueba de literales marcados no cubre el cliente MCP, `/discover/stream`, el Visor de eventos, `TEMP` de las gMSA, IIS, volcados de memoria **ni el navegador** | `api/tests/test_marked_literals.py`; `event_log` apagado en la prueba (`test_marked_literals.py:75`) | OP-06 CA4 queda cerrado solo en parte | Media | M | Repetir la búsqueda del literal en el servidor instalado y añadir MCP y streaming a la prueba | HU-37 |
| DT-42 | **(nueva)** Solo `CurationRepository` tiene un contrato común que corre contra archivos y contra la BD. `KnowledgeWriter` e `InventoryStore` se prueban por separado | `tests/test_curation.py:182-186` (fixture parametrizado); `tests/test_curation.py:167`, `238` (solo archivos) | Los adaptadores de archivos y de BD pueden divergir sin que una prueba lo note | Baja | S | Fixture parametrizado `archivos`/`sqlserver` para los otros dos puertos | — |
| DT-43 | `converdata audit purge` y `eval gate --db` no tienen prueba del comando (sí las funciones que llaman) | `cli.py:268-280`, `389-422`; ninguna referencia en `tests/` ni `api/tests/` | Un error de argumentos o de conexión del comando no se ve | Baja | S | Añadirlos a `tests/test_catalog_refresh.py` contra la BD desechable | — |

### 3.6 Cadena de suministro y despliegue

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-44 | No hay instalación para Windows Server: no existe `deploy/` (IIS, tareas programadas, firewall, respaldo) | Carpeta ausente; OP-07 describe los scripts | Sin esto no hay piloto. Hoy solo `docker compose` | Alta | L | Scripts de `deploy/windows/` validados en el servidor del piloto (⛔ Windows Server y gMSA) | Bloque F, HU-37, HU-38, HU-39 |
| DT-45 | La CI no construye la imagen de la API ni la analiza ni la firma. **Sin verificar** si la imagen se ha construido después del 2026-11-17 (no se construyó para este registro) | `calidad.yml` (sin `docker build`); `api/Dockerfile` | Un fallo de la imagen o una vulnerabilidad de la imagen base solo se ve al desplegar | Alta | M | `docker build` en la CI, escáner de imágenes y firma | Bloque F |
| DT-46 | Estado en memoria de un solo proceso: sesiones, bloqueos de login, ritmo, tope diario de tokens y trazas mostradas. **(nueva: la consecuencia del tope)** | `api/converdata_api/vault.py:46`; `tokens.py:17`; `main.py:262-266`; `runtime.py:103`; `api/Dockerfile:51-52` | Cada despliegue cierra todas las sesiones y pone a cero el tope diario de tokens y los bloqueos | Baja | S | Avisar en la ventana de despliegue; persistir el tope de tokens si el banco lo exige | Decisión: §6 |
| DT-47 | Los paquetes del sistema de la imagen y de la CI se instalan sin versión | `api/Dockerfile:13`, `21`; `calidad.yml:27` | Es lo único de la imagen sin fijar | Baja | S | Fijar versión de `msodbcsql18` y `unixodbc`, o aceptar con escaneo de la imagen | Bloque F |
| DT-48 | Las dependencias de desarrollo de la web tienen 19 avisos de `npm audit` (17 altos y 2 moderados, sobre todo ReDoS de `picomatch` y `minimatch` vía `eslint-config-next` y `shadcn`). Las de producción, 0 | `npm audit` en `web/` el 2026-11-17; `web/package.json:24-35` | No se despliegan, pero corren en los equipos y en la CI | Baja | S | Actualizar cuando Dependabot proponga la versión corregida | — |
| DT-49 | Los bloqueos de Python se regeneran a mano | `.github/dependabot.yml` (sin ecosistema `pip`); `requirements/README.md:16-30` | Las actualizaciones de seguridad de Python dependen de que alguien lea el aviso de `pip-audit` | Baja | S | Tarea periódica con `uv pip compile --upgrade` o Dependabot para `pip` | — |
| DT-50 | **(nueva)** La imagen de la API lleva los fixtures de prueba y la carpeta `config/`, que incluye el inventario de desarrollo versionado (con `trust_server_certificate: true`) | `api/Dockerfile:38`, `44`; `config/databases.local.yaml` (en git) | Material de prueba en la imagen de producción. No es un secreto, pero un error de configuración lo puede cargar | Baja | S | Copiar solo los ejemplos necesarios; fixtures solo en una imagen de demo | Bloque F |
| DT-51 | `BancosSQL.zip` (13 MB) está versionado | `git ls-files` | Cada clon descarga 13 MB que pocos usan | Baja | S | Git LFS o fuera del repositorio | — |

### 3.7 Web

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-52 | Páginas muy grandes y archivos compartidos por todos los carriles | `web/src/app/(app)/admin/page.tsx` (872 líneas), `curacion/page.tsx` (573); `web/src/lib/api.ts`, `types.ts` | Conflictos entre carriles; el reparto pide separarlos antes de que dos personas toquen la web | Media | M | Un componente por pestaña y `api`/`types` por área | Reparto: Dev 5 |
| DT-53 | **(nueva)** Los tipos de la web se escriben a mano (308 líneas) en vez de generarse desde el OpenAPI de la API | `web/src/lib/types.ts` | La deriva del contrato solo la detecta el subagente `verificador-contrato-web-api`, no una compilación | Media | M | Generar los tipos desde `/openapi.json` en desarrollo y comprobarlo en la CI | — |
| DT-54 | Accesibilidad **sin verificar**: no hay comprobación automática. En una muestra, los botones de solo icono revisados sí llevan `aria-label` | `admin/page.tsx:407`, `744`; `curacion/page.tsx:478`; `chat/composer.tsx:63` | Desconocido; el banco puede exigir un nivel de accesibilidad | Baja | S | Auditoría con Lighthouse o axe en las pantallas principales | — |

### 3.8 Documentación y specs

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-55 | **(nueva)** Variables de entorno que el código lee y ninguna documentación nombra: `CONVERDATA_MODELS` (solo en `docker-compose.yml:24`), `CONVERDATA_MCP_ORIGINS`, `CONVERDATA_DEMO_FIXTURE`, `CONVERDATA_DEMO_PRELOAD`, `CONVERDATA_DEMO_HISTORY` | `settings.py:73`, `89`, `91-92`, `102`; búsqueda en `README.md`, `docs/` y `.env.example` | Quien instala no sabe que existen | Baja | S | Tabla única de variables (en `.env.example` o en la wiki) | — |
| DT-56 | **(nueva)** Afirmaciones de la documentación que ya no coinciden con el código. Lista en la respuesta al equipo y en la §4.1 | Ver §4.1 | Un desarrollador nuevo actúa sobre información vieja | Baja | S | Corregir cada una en su documento | — |

### 3.9 Hallazgos al documentar los componentes

Salieron al leer el código para escribir las páginas de `docs/wiki/componentes/`. Los marcados "sin verificar" necesitan una prueba antes de darlos por ciertos.

| ID | Deuda | Evidencia | Consecuencia | Grav. | Esf. | Cómo se cierra | Plan / HU |
|---|---|---|---|---|---|---|---|
| DT-58 | **(nueva)** Los avisos de la API no llegan al log JSON ni al Visor de eventos: `configure_logging` configura el logger `converdata` sin propagación, y la API escribe con `converdata_api.*` | `src/converdata/observability/logging.py:54-56`; `api/converdata_api/runtime.py:45`; `api/converdata_api/curation.py:25` | Un fallo al cargar, recargar o construir el catálogo, o al leer la visibilidad, no aparece en el monitoreo | Media | S | Configurar también `converdata_api` o usar un nombre bajo `converdata` | HU-21 |
| DT-59 | **(nueva)** Los puertos `QueryExpander` y `Reviewer` no tienen implementación con LLM ni se conectan en `bootstrap.py`. Los patrones C y B corren solo en su parte determinista, aunque el docstring del flujo los da por activos | `src/converdata/discovery/ports.py`; `src/converdata/bootstrap.py`; `src/converdata/flows/discover.py:1-16` | Lo que se espera ganar con el modelo en reformulación y revisión no existe todavía; `config/models` declara un rol `judge` sin uso | Media | M | Implementarlos al probar Bedrock, o quitar el rol y corregir el docstring | HU-35 |
| DT-60 | **(nueva)** La pregunta de aclaración que redacta el modelo se muestra sin pasar por la guarda de texto | `src/converdata/flows/discover.py:341` | Es el único texto del modelo que llega al usuario sin comprobar que no nombra objetos ajenos | Media | S | Pasarla por la misma guarda que la narrativa, con respaldo determinista | HU-36 |
| DT-61 | **(nueva)** Las descripciones que sugiere el LLM al construir el catálogo no pasan por la guarda de texto ni por el detector de datos personales | `src/converdata/flows/catalog_build.py:162-170` | Una descripción generada se indexa y la ven todos los usuarios con acceso al activo | Media | S | Aplicar `pii.py` y la guarda antes de escribir; marcar la fuente como sugerida | HU-26 |
| DT-62 | **(nueva)** Cerrar sesión y revocar las sesiones de un usuario se auditan después de aplicar el cambio | `api/converdata_api/main.py` (`/auth/logout`, `DELETE /admin/sessions/{user_id}`) | Si la auditoría falla, la revocación ya ocurrió sin registro. Contradice "auditar antes de aplicar" | Baja | S | Usar `applying(...)` como en el resto de cambios | — |
| DT-63 | **(nueva)** El cliente de Bedrock no recibe `timeout_s` (sí el de NIM) y su única prueba usa un constructor falso | `src/converdata/llm/factory.py:118` | Una llamada colgada retiene la petición del usuario; nada lo ha ejercitado | Media | S | Pasar el tiempo límite y cubrirlo en la prueba de punta a punta | HU-35 |
| DT-64 | **(nueva)** Con el tope diario de tokens agotado, `/mcp` siempre rechaza aunque `CONVERDATA_TOKEN_LIMIT_MODE=deterministic` | `api/converdata_api/mcp_mount.py`; `api/converdata_api/tokens.py` | La web responde sin modelo y el cliente MCP no: comportamiento distinto para el mismo usuario | Baja | S | Aplicar el mismo modo en el montaje MCP | HU-19 |
| DT-65 | **(nueva)** La cookie de sesión no se renueva aunque la sesión del servidor sí se extiende | `api/converdata_api/main.py` (`set_cookie` solo en el login); `api/converdata_api/vault.py` | En el navegador la sesión dura como máximo 8 h aunque el usuario siga activo; el tope real de 12 h no se alcanza | Baja | S | Renovar la cookie al extender la sesión, o documentar 8 h como tope | — |
| DT-66 | **(nueva)** Ningún `GRANT` cubre `dbo.schema_version`, que la API lee al arrancar para comprobar las migraciones | `db/converdata/001_esquemas.sql`; `src/converdata/storage/migrations.py` (`require_current`). **Sin verificar** con una cuenta que solo pertenezca a `converdata_app` | En qa y prod la API podría no arrancar con la cuenta de mínimo privilegio | Media | S | Prueba `sqlserver` con ese rol; si falla, `GRANT SELECT` en una migración `003` | HU-37 |
| DT-68 | **(nueva)** La suite `auditoria` de la compuerta usa sumideros en memoria | `src/converdata/evaluation/gate.py` | La compuerta no prueba el comportamiento fail-closed del sumidero de SQL Server; eso lo cubren solo las pruebas `sqlserver`, que no corren en la CI (DT-39) | Baja | M | Variante de la suite con `--db` | HU-36 |
| DT-69 | **(nueva)** `CONVERDATA_BUILDER_HOSTS` solo se aplica a `catalog build --db`. No se aplica con `--config` ni a la construcción lanzada desde Administración | `src/converdata/cli.py:318`, `345-363`; `api/converdata_api/runtime.py` (`_run_build`) | Desde Administración se usa la credencial del administrador, no la cuenta de servicio, así que el riesgo es menor; pero el inventario puede apuntar a cualquier host | Baja | S | Aplicar la misma lista en la API, o documentar la diferencia en OP-07 | HU-37 |
| DT-70 | **(nueva)** Nada escribe `knowledge.item` ni `curation.owners` salvo la importación con `catalog publish` | `src/converdata/storage/catalog_repository.py`; `db/converdata/001_esquemas.sql:108`, `189` | Diccionarios, documentos y dueños de dominio no tienen camino de entrada en producción hasta el bloque E | Media | M | Ingesta de fuentes de conocimiento y edición de dueños | HU-25, HU-26 |
| DT-71 | **(nueva)** La CSP de la web usa `'unsafe-inline'` en `script-src` y `style-src`: Next.js inyecta scripts y estilos en línea y no se usan nonces | `web/next.config.ts:9-10` | Si una página llegara a reflejar contenido sin escapar, la CSP no frenaría el script en línea. El resto de la política (`frame-ancestors 'none'`, `object-src 'none'`, `form-action 'self'`) sí vale | Baja | M | Pasar a CSP con nonces (middleware de Next.js) y quitar `'unsafe-inline'` de `script-src` | OP-04 |

## 4. Deudas cerradas recientemente

No reabrir. Si alguna vuelve, es una regresión.

| Cerrada | Cómo se comprueba |
|---|---|
| DT-01 · El proxy de la web no reenviaba `Origin` y la API no comprobaba el origen de lo que llegaba por la web | `web/src/app/api/[...path]/route.ts:7`, `26-27` (reenvía `origin` y envía `X-Forwarded-Host`). Comprobado en el navegador el 2026-11-17: un cambio de estado con cookie desde otro origen da 403 "Origen no permitido"; desde el mismo origen, 200. Si delante hay un proxy que cambia `Host`, el origen público va en `CONVERDATA_CORS_ORIGINS` |
| DT-03 · Las páginas de la web no llevaban cabeceras de seguridad | `web/next.config.ts` (`headers()`): CSP con `frame-ancestors 'none'`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y, en producción, HSTS. Comprobado en el navegador. Queda el límite de `'unsafe-inline'` (DT-71) |
| DT-08 · Las conversaciones seguían en `localStorage` tras cerrar sesión | `web/src/components/session-provider.tsx:75-80` borra las claves `converdata:conversations:*` al cerrar sesión. Matiz: si la sesión caduca sin pulsar "Cerrar sesión", las conversaciones siguen en el navegador hasta el siguiente cierre de sesión |
| DT-57 · La visibilidad perdía las bases siguientes de un servidor si una era inaccesible | `src/converdata/identity/visibility.py` (`PyodbcObjectLister.visible_objects`: pregunta `HAS_DBACCESS` desde `master` y solo abre las bases con acceso); `tests/test_visibility.py` (tres pruebas sin SQL Server y una `sqlserver`). Confirmado contra SQL Server real. La reproducción usó una base fuera de línea porque el SQL Server local solo admite autenticación de Windows: falta repetirla con un login SQL de acceso parcial en el servidor del banco |
| DT-67 · El proxy de la web reenviaba cualquier ruta | `route.ts:12`, `16-18`: solo `auth`, `login`, `setup`, `me`, `discover`, `catalog`, `assets`, `curation` y `admin`; `/api/mcp`, `/api/health/metrics` y `/api/docs` responden 404 |
| Fallos de orden B4 y C2 del descubrimiento | Commit `615d9c3`. `eval discovery` del 2026-11-17 solo falla B14 y eng-06 |
| Dependencias de Python sin versión ni hash; imágenes por etiqueta; acciones por etiqueta | Commit `615d9c3`; `requirements/*.lock`; `tests/test_supply_chain.py` |
| Sin análisis de vulnerabilidades ni SBOM en la CI | `calidad.yml:64-91` (`pip-audit`, `npm audit --omit=dev`, CycloneDX); corre también cada lunes (`calidad.yml:9-10`) |
| Next.js 15.5.4 vulnerable y `postcss` transitivo | `web/package.json:16`, `37-41`. `npm audit --omit=dev` da 0 el 2026-11-17 |
| La web no se compilaba en la CI | Trabajo `web`: `calidad.yml:45-62` (tipos, lint y build) |
| Sin prueba de punta a punta de literales marcados | `api/tests/test_marked_literals.py` (con los límites de DT-41) |
| El nombre de una tabla oculta, referenciada por llave foránea, movía la confianza | `engine._asset_terms_split`; `tests/test_graph_rag.py::test_el_nombre_de_una_tabla_que_no_se_ve_no_mueve_la_confianza` |
| Canal de embeddings, `VisibilityResolver`, `SqlServerVectorStore` y código muerto (`physical_ids`, `mentioned_assets`, `QueryVariants`, `EstateGraph.neighbors`, `set_golden_state`, `GoldenAction`) | Commit `916731a`. Ninguno aparece ya en `src/`, `api/` ni `tests/`. Un barrido de definiciones sin referencias no encontró código muerto nuevo |
| Copia de trabajo del catálogo en disco y publicación completa tras cada edición; curación e inventario en archivos con `CONVERDATA_DB` | Commit `916731a`; `db/converdata/002_curacion.sql`; `test_el_servidor_no_guarda_estado_en_disco` |
| Un voto publicaba el catálogo entero; un solo "✖" retiraba lo que confirmaron varios | Commit `916731a`; `curation.resolve_golden`; `test_un_voto_escribe_una_sola_fila_y_sube_la_version` |
| 409 por catálogo desactualizado (`catalog_conflict`) | Commit `916731a`; no aparece en el código |

### 4.1 Afirmaciones de la documentación que ya no valen (DT-56)

| Documento | Dice | El código |
|---|---|---|
| `docs/backlog/on-premise.md:397` | La API "arranca desde archivos hasta HU-09" | HU-09 está hecha: con `CONVERDATA_DB` arranca desde la BD (`runtime.py:135-146`) |
| `docs/backlog/on-premise.md:453-454` | "Falta recompilar la web tras el endurecimiento" | La CI la compila en cada PR (`calidad.yml:45-62`) |
| `docs/manual-desarrollo.md:52` | Las herramientas de descubrimiento son "las mismas para la API y el MCP" | Solo el MCP las usa; la API llama al `DiscoverService` (`main.py:598`) y tiene su propia ficha (`main.py:923-949`). `capas-backend.md:54` sí lo dice bien |
| `docs/calidad-bancaria.md:110`, `docs/manual-desarrollo.md:155`, `docs/backlog/reparto-5-devs.md:63` | Detector de "cinco patrones (DUI, NIT, correo, teléfono, tarjeta)" | Reconoce seis tipos: también IBAN (`pii.py:12-19`) |
| `docs/calidad-bancaria.md:76` | CSRF por `Origin` y cabeceras de seguridad como controles implementados | Corregido el 2026-11-17: el proxy reenvía `Origin` y la web envía las cabeceras (DT-01, DT-03 cerradas); la nota ya no aplica |
| `docs/calidad-bancaria.md:129` (§4) | `CONVERDATA_LOG_DIR` obligatorio en qa y prod | Nunca falta: `settings.py:80` pone un valor por defecto (DT-06) |
| `docs/calidad-bancaria.md:39` | La calibración ≥ 85 % es un criterio de la suite `calidad` | En BancosSQL no es medible (n = 0) y queda informativa (DT-32) |
| `docs/PLAN-desarrollo.md:253` | `pip install --no-deps -e .` | El manual y `requirements/README.md:39` usan `--no-deps --no-build-isolation --no-index -e .` |
| `docs/backlog/reparto-5-devs.md:95` | "Cada puerto tiene… pruebas de contrato que corren contra los dos" | Solo `CurationRepository` (DT-42) |
| `api/Dockerfile:2` | "Se construye desde la raíz de DataAgent" | El repositorio es ConverData |

## 5. Orden recomendado de pago

1. **DT-39** (M). SQL Server en la CI antes de que cinco personas cambien `storage/`, `audit/` y `db/` a la vez. Con DT-40 (una prueba que pase por el proxy) para que las cabeceras y el control de origen no vuelvan a perderse.
2. **DT-17 y luego DT-16** (S + M). La fábrica primero quita efectos al importar; partir `main.py` después reduce los conflictos entre carriles.
3. **DT-04 y DT-33** (M + S). La migración `003` con `recorded_at` y la tarea de purga van juntas: la purga debe borrar por la fecha nueva.
4. **DT-06, DT-07 y DT-21** (S). Configuración que falla en silencio y un circuit breaker que se reinicia: baratos y evitan sorpresas en la instalación.
5. **DT-35 y DT-27** (M + S). Antes de construir el bloque D, para que las métricas salgan de la BD y no de un tope en memoria.
6. **DT-45, DT-44 y DT-02** (M + L + S). La imagen en la CI y los scripts de Windows son el bloque F; DT-02 (activar `TRUST_FORWARDED_FOR` y `CONVERDATA_TRUST_PROXY` detrás de IIS) entra con ellos. Empezar ya lo que no necesita el servidor.
7. **DT-29, DT-30 y DT-05** (L). Dependen del banco (steward, cuenta AWS, documentos); pedirlos el primer día.

## 6. Lo que no es deuda sino decisión

No abrir tareas para "corregir" esto sin cambiar antes la decisión en `docs/PRD.md` §13.

| Decisión | Dónde |
|---|---|
| Búsqueda léxica en memoria, sin embeddings ni índice en SQL Server. Medido: los embeddings no mejoraron ningún caso y subieron el p95 de 73 ms a 4,6 s | PRD §13, decisión 9 |
| Un solo proceso de API para 10–15 usuarios: sesiones, trazas, inventario y confirmaciones recientes en memoria; más de un proceso exige rediseñar ese estado | PRD §13, nota "Un solo proceso de API"; OP-03; `api/Dockerfile:51-52` |
| BD `ConverData` en tablas normales; el grafo del patrimonio se arma en memoria | PRD §13, decisión 10 |
| Web Next.js como único punto de entrada del navegador; la API no se publica | PRD §13, decisión 11 |
| Builder como comando programado, que entra con la cuenta del proceso salvo `metadata_user_env` | PRD §13, decisión 12 y nota del 2026-11-17 |
| Un solo modelo de Bedrock en el piloto, sin juez; Guardrails a decisión de Seguridad | PRD §13, decisión 13 |
| Roles por nombre de login hasta tener grupos de AD | PRD §13, decisión 7; pregunta abierta 9; HU-13 |
| El MCP publicado solo tiene herramientas de lectura; toda escritura pasa por la API | PRD §13, decisión 8 |
| Alias `/login` y `/auth/login`, `/logout` y `/auth/logout` | PRD §13, decisión 15 |
| La plantilla de las confirmaciones pierde también los umbrales de negocio ("a 90 días" y "a 30 días" son la misma confirmación) | PRD §13, nota sobre la decisión 8 |

Las preguntas abiertas 7, 8 y 9 del PRD (qué ve un responsable, qué lecturas se auditan, cómo se valida un login para dar
un rol) son decisiones pendientes del banco: DT-10 y DT-11 se cierran cuando se tomen.
