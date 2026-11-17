# OP-07 — Instalación, entornos y operación · on-premise

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Completa [OP-01](OP-01-despliegue-local.md) con la instalación, los entornos y los requisitos no funcionales del despliegue
> on-premise. Specs relacionadas: [OP-04](OP-04-interfaces.md) IIS · [OP-05](OP-05-auditoria-observabilidad.md) alertas · [OP-06](OP-06-residencia-datos.md) residencia de datos · [calidad bancaria §4](../../calidad-bancaria.md) configuración obligatoria en qa y prod.
>
> Los valores marcados **⚠️ propuesto** salen de la revisión del 2026-10-27 y los tienen que confirmar Plataformas y el DBA antes del piloto.

## Objetivo
Que cualquier administrador de Plataformas pueda montar, actualizar, respaldar y recuperar un entorno de ConverData igual al del piloto
**solo con los scripts del repo y esta spec**, sin pasos manuales no documentados y sin secretos en archivos.

**Estado.** Los scripts de `deploy/windows/` **no existen todavía** (HU-37): esta spec es su especificación. Lo construido para ejecutar
la aplicación es `docker-compose.yml` (web y API, la API sin publicar), que se usa en desarrollo y demostraciones, y la CI
(`.github/workflows/calidad.yml`). La BD `ConverData` se crea y actualiza con `converdata db migrate` (§Migraciones) y la API la usa
cuando `CONVERDATA_DB` está definida (OP-02).

## Decisión (2026-11-16): modelo de procesos
Dos procesos detrás de IIS y un comando; **ningún servicio de Windows propio** (PRD §13, decisiones 11 y 12).

| Proceso | Cómo corre | Quién lo supervisa | Motivo |
|---|---|---|---|
| Web (Next.js, `web/`) | Aplicación de IIS en `/` con su grupo de aplicaciones; HttpPlatformHandler lanza el servidor Node (salida `standalone` de `next build`) | IIS (HttpPlatformHandler reinicia el proceso si cae) | Es un proceso porque su ruta `/api/[...path]` reenvía las llamadas a la API (`API_URL`) |
| `ConverData-API` (FastAPI + DiscoverFlow + `converdata-mcp` + SessionVault + índice léxico) | Aplicación de IIS en `/mcp` con su grupo de aplicaciones; HttpPlatformHandler lanza **un solo** proceso uvicorn en `127.0.0.1` | IIS | SessionVault exige un solo proceso (OP-03); la API no se publica salvo `/mcp` |
| Builder (`converdata catalog build`) | **Comando que corre y termina**, lanzado por el Programador de tareas de Windows con su gMSA; también bajo demanda desde Administración (`POST /admin/catalog/build`) | Programador de tareas (historial y código de salida) | La ingesta es un batch largo: no depende del ciclo de vida de IIS |

Configuración obligatoria de los grupos de aplicaciones de la web y de la API: identidad gMSA, `idleTimeout = 0`, reciclaje periódico
desactivado y **reciclaje superpuesto desactivado** en `ConverData-API` (`disallowOverlappingRotation = true`): con reciclaje superpuesto
habría dos procesos con dos SessionVault distintos durante unos segundos.

Tras un build hecho por la tarea programada (`converdata catalog build --db`), la API carga el catálogo nuevo sin reiniciar: comprueba
`catalog.catalog_version` como mucho cada 15 s y, si cambió, reconstruye su copia de trabajo y su índice en memoria.

## Entornos
| Entorno | Servidor de aplicación | BD `ConverData` | BDs de datos | LLM | Datos |
|---|---|---|---|---|---|
| **dev** | Estación del desarrollador, sin IIS: `converdata` CLI y uvicorn directo, o `docker compose up` (web en `:3000`) | No hace falta: archivos YAML/JSONL; o SQL Server 2016+ Developer local | BancosSQL, AdventureWorks, o `CONVERDATA_DEMO=1` (servidores simulados) | Sin LLM (determinista), Ollama (`environment: local`) o NIM con datos de prueba (F16) | Solo de prueba |
| **qa** | Windows Server de QA, instalado con los mismos scripts que el piloto; `CONVERDATA_ENV=qa` | Instancia SQL Server de QA (2016 o posterior) | Servidores de QA del dominio piloto | Bedrock | Metadatos reales de QA; consultas solo a QA |
| **piloto / prod** | Windows Server del piloto (OP-01 §Dimensionamiento); `CONVERDATA_ENV=prod` | Instancia SQL Server gestionada por el DBA (2016 o posterior) | Producción y QA del dominio piloto (réplica legible si existe) | Bedrock (cuenta del cliente, F17) | Reales |

Reglas:
- Un cambio llega a piloto solo después de pasar en qa los tests y **`converdata eval gate`** (7 suites, [calidad bancaria §2](../../calidad-bancaria.md)) sin regresión frente a la línea base (F25 CA3).
- qa y piloto no comparten BD `ConverData`, gMSA ni certificado.
- NIM alojado y Ollama están bloqueados por configuración fuera de dev (`data_mode: real`, guarda de residencia de F16).
- El instalador **debe fijar `CONVERDATA_ENV`**: sin ella vale `dev` y no se exige ninguno de los ajustes de [calidad bancaria §4](../../calidad-bancaria.md). Con `qa` o `prod` la API no arranca si falta alguno (cookie segura, orígenes `https`, `CONVERDATA_MCP_HOSTS`, lista de administradores, código de instalación mientras no haya inventario, directorio de logs, `CONVERDATA_DB` sin contraseña y con TLS validado, `data_mode: real` y sin rol `embed`, sin `trust_server_certificate` ni `audit.fail_open`), ni si su cuenta en la BD `ConverData` puede modificar o borrar la auditoría.

## Requisitos no funcionales
| Área | Requisito | Origen |
|---|---|---|
| Latencia | Descubrimiento p50 < 5 s y p95 < 10 s; consulta de datos (fase 1b) p50 < 15 s y p95 < 40 s en el MVP | OP-01, F22 |
| Disponibilidad del piloto | **99 % en horario laboral** (lunes a viernes, 7:00–19:00); fuera de ese horario, sin compromiso. Un solo servidor de aplicación (sin alta disponibilidad, OP-01 §Fuera del alcance) | ⚠️ propuesto |
| Recuperación de la BD `ConverData` | **RPO 15 min** (modelo de recuperación completo y respaldo de log cada 15 min) y **RTO 4 h** | ⚠️ propuesto |
| Recuperación del servidor de aplicación | Reinstalación con los scripts en ≤ 1 día laboral. Con la BD en uso no guarda estado propio (las sesiones se pierden por diseño, OP-03); mientras catálogo, curación y auditoría sigan en archivos, `%ProgramData%\ConverData\data\` **sí es estado** y hay que respaldarlo | ⚠️ propuesto |
| Capacidad | 3–20 usuarios simultáneos en el piloto; 30 preguntas por minuto y usuario; tope diario de tokens por usuario (OP-04) | OP-01, OP-04 |
| Coste | Coste de Bedrock por pregunta medido y reportado cada semana (tokens en `/admin/metrics`, F25) | OP-01 criterio 6 |
| Seguridad | TLS con la PKI corporativa en IIS y `Encrypt=yes` en SQL Server; sin secretos en archivos; gMSA para todos los procesos; ajustes de [calidad bancaria §4](../../calidad-bancaria.md) | OP-03, OP-04 |

## Instalación reproducible
Scripts PowerShell idempotentes en `deploy/windows/` (se pueden volver a ejecutar sin cambiar nada si el servidor ya está bien), con un
archivo de parámetros por entorno `deploy/windows/entorno.<env>.psd1` que **no contiene secretos** (solo nombres de servidor, rutas,
huellas de certificado y nombres de gMSA). Pendientes de escribir (HU-37).

| Paso | Script | Qué hace |
|---|---|---|
| 1 | `01-prerrequisitos.ps1` | Roles de IIS, HttpPlatformHandler, ODBC Driver 18 for SQL Server, Python 3.12 y uv, Node.js LTS |
| 2 | `02-cuentas.ps1` | Instala y prueba las gMSA (`Install-ADServiceAccount`, `Test-ADServiceAccount`) |
| 3 | `03-bd.ps1` | Con la cuenta del DBA: crea la BD `ConverData` si no existe, ejecuta `converdata db migrate` (que aplica los scripts de `db/converdata/` y registra versión y SHA-256 en `dbo.schema_version`, ver §Migraciones) y agrega cada gMSA a su rol: la de la API a `converdata_app`, la del Builder a `converdata_builder` y la de mantenimiento a `converdata_maintenance` |
| 4 | `04-aplicacion.ps1` | Despliega la versión en `%ProgramFiles%\ConverData\releases\<versión>` (API con `uv sync --frozen`; web con `npm ci` y `npm run build`, o el paquete ya compilado) y apunta el enlace `current` a ella |
| 5 | `05-iis.ps1` | Sitio HTTPS, grupos de aplicaciones (§Decisión), `web.config` de la web (`/`) y de la API (`/mcp`) con sus variables de entorno (`CONVERDATA_ENV` y las de calidad bancaria §4; `API_URL` en la web), enlace del certificado, HSTS, Request Filtering, logs W3C sin cuerpos |
| 6 | `06-tareas.ps1` | Tareas del Programador de tareas de Windows. Con la gMSA del Builder: build nocturno (`converdata catalog build --db`) seguido de la evaluación de regresión (`converdata eval gate --db --root <casos>`, que sale con código distinto de 0 si algo baja de la línea base). Con la gMSA de mantenimiento: purga de la auditoría (`converdata audit purge`, 180 días). La integridad de la auditoría la comprueba la API al arrancar y `GET /admin/audit/verify` |
| 7 | `07-firewall.ps1` | Reglas de entrada y salida de OP-04 §IIS |
| 8 | `08-secretos.ps1` | Script interactivo que carga una vez los secretos que no son gMSA y los cifra con DPAPI (ver abajo) |
| 9 | `09-endurecimiento.ps1` | Controles de memoria de OP-06: sin volcados de los procesos de ConverData en WER, `SeDebugPrivilege` solo para administradores |
| 10 | `10-verificar.ps1` | Smoke test: `/health`, `/setup/status`, login con un login de prueba, `/api/discover` de una pregunta conocida, registro en la auditoría y `converdata eval gate` |

Los secretos que no son gMSA se cargan **a mano una vez** con el script interactivo, que los cifra con DPAPI en el ámbito de la cuenta
de servicio: login de metadatos si no es gMSA, código de instalación (`CONVERDATA_SETUP_TOKEN`, que deja de hacer falta cuando existe
inventario), URL del webhook de Teams y sal de MinHash. El certificado de IAM Roles Anywhere se emite en el servidor con clave no
exportable.

Rutas en el servidor:
| Ruta | Contenido |
|---|---|
| `%ProgramFiles%\ConverData\releases\<versión>\` y `current` | Código de la API y de la web, con sus entornos, de cada versión |
| `%ProgramData%\ConverData\config\` | `models.yaml` y los parámetros del entorno (sin secretos) |
| `%ProgramData%\ConverData\data\` | Mientras no se migre a la BD: inventario de servidores, catálogo (`config/`, `catalog/`, `knowledge/`), curación y auditoría JSONL (`CONVERDATA_INVENTORY`, `CONVERDATA_DATA_ROOT`, `CONVERDATA_CURATION_DIR`, `CONVERDATA_AUDIT_DIR`); ACL solo para las gMSA y los administradores |
| `%ProgramData%\ConverData\secrets\` | Blobs cifrados con DPAPI; ACL solo para las gMSA y los administradores |
| `%ProgramData%\ConverData\logs\` | Logs JSON rotados (`CONVERDATA_LOG_DIR`, OP-05) |

## Migraciones de la BD `ConverData`
- Scripts numerados `db/converdata/NNN_<descripcion>.sql`, aplicados en orden; `dbo.schema_version` guarda número, fecha y quién los aplicó.
- **Solo hacia adelante y compatibles con la versión anterior de la aplicación** (expandir y después contraer): una columna nueva se agrega
  nullable o con valor por defecto, y se elimina lo viejo en una versión posterior. Así el rollback de la aplicación no exige revertir la BD.
- Las tablas temporales se alteran con `SYSTEM_VERSIONING = OFF` y `ON` dentro de la misma transacción del script.
- **`converdata db migrate`** (lee `CONVERDATA_DB`) aplica lo pendiente: cada script corre entero en una transacción junto con su fila de
  `dbo.schema_version` (o queda aplicado y registrado, o no cambia nada); `--status` solo lista lo pendiente. Un script ya aplicado no se
  puede editar (se compara su SHA-256): los cambios van en un script nuevo. La BD vacía la crea el DBA.
- Estado: existe `001_esquemas.sql`, aplicado y probado contra SQL Server 2022 (`tests/test_storage_migrations.py`); usa solo lo que
  admite SQL Server 2016 (tablas temporales, `ISJSON`), pero no se ha probado en una instancia 2016.

## Actualización y rollback
1. Aplicar en qa y pasar los tests, `10-verificar.ps1` y `converdata eval gate` sin regresión.
2. En piloto: aplicar migraciones (`03-bd.ps1`), desplegar la versión nueva (`04-aplicacion.ps1`) y cambiar el enlace `current`.
3. Reciclar la web y la API **fuera de un build en curso** (el script comprueba que la tarea programada no esté corriendo y que `GET /admin/catalog/build` no devuelva `running`).
4. Avisar a los usuarios: las sesiones se pierden al reiniciar la API (OP-03) y hay que volver a iniciar sesión.
5. Rollback: apuntar `current` a la versión anterior y reciclar; las migraciones no se revierten (por la regla de compatibilidad).

## Respaldo y recuperación
- BD `ConverData`: completo diario, diferencial cada 6 h y log cada 15 min, con **`BACKUP ... WITH ENCRYPTION`** (contiene preguntas,
  D2) y acceso solo para el DBA. La retención de los respaldos no puede superar la de la auditoría (180 días, OP-05).
- Mientras catálogo, curación y auditoría sigan en archivos: copia diaria cifrada de `%ProgramData%\ConverData\data\`, con el mismo
  acceso y la misma retención, y el hash de cabeza de la auditoría exportado a diario (OP-05).
- Configuración (`%ProgramData%\ConverData\config\`): versionada en un repositorio interno; los secretos no se respaldan, se vuelven a cargar.
- No se respalda: SessionVault (por diseño), índice léxico (se reconstruye al arrancar), logs (se rotan), sketches de F19 (no existen fuera de memoria).
- **Prueba de restauración** antes del piloto y cada trimestre: restaurar en otra instancia, apuntar un servidor de qa a ella y repetir el
  smoke test y el set de evaluación.

## Operación
| Tarea | Frecuencia | Cómo |
|---|---|---|
| Revisar el historial de las tareas programadas (build, evaluación, purga, verificación de auditoría) | Diaria | Un fallo deja un error en el Visor de eventos, que el monitoreo convierte en alerta (OP-02 CA6, OP-05 §Alertas) |
| Revisar alertas y `/health/metrics` | Continua | Monitoreo existente (OP-05 §Alertas) |
| Renovar el certificado TLS y el de IAM Roles Anywhere | Antes de que expiren (alerta a 30 días, OP-05) | Script de renovación + `05-iis.ps1` |
| Rotar el login de metadatos (si es login SQL) y la URL del webhook | Según la política de Seguridad de la Información | `08-secretos.ps1`; el siguiente build usa el secreto nuevo |
| Revocar las sesiones de un usuario (baja o incidente) | Cuando ocurra | Administración → Sesiones (`DELETE /admin/sessions/{user_id}`) |
| Refrescar el catálogo fuera del horario nocturno | Bajo demanda | Administración → `POST /admin/catalog/build`, o ejecutar la tarea programada a mano |
| Prueba de restauración | Trimestral | §Respaldo y recuperación |

No hay reindexación de vectores: no se usan embeddings (PRD §13, decisión 9).

## Criterios de aceptación
1. En un Windows Server limpio, los scripts 01–10 dejan un entorno funcionando en ≤ 1 día laboral, y una segunda ejecución no cambia nada.
2. Ningún archivo de `deploy/windows/`, de `%ProgramData%\ConverData\config\` ni del repo contiene contraseñas, tokens ni claves (test con búsqueda de patrones).
3. Un build de más de 2 h lanzado por la tarea programada termina aunque IIS recicle la web o la API durante ese tiempo.
4. Con `ConverData-API` reciclada, nunca hay dos procesos de la API activos a la vez (comprobado con el Administrador de IIS durante el reciclaje).
5. Una actualización y su rollback se completan en ≤ 30 min sin perder registros de auditoría.
6. La prueba de restauración cumple el RPO y el RTO de §Requisitos no funcionales.
7. Si cae el proceso de la web o de la API, IIS lo reinicia (OP-04 CA5); si el build nocturno falla, la tarea queda en error, el monitoreo avisa y la ejecución de la noche siguiente lo reintenta.
8. Con `CONVERDATA_ENV=prod` y cualquiera de los ajustes de [calidad bancaria §4](../../calidad-bancaria.md) sin cumplir, la API no arranca y `10-verificar.ps1` lo informa.

Estado de los criterios: ninguno se ha comprobado en un Windows Server (HU-37); el comportamiento del criterio 8 ya tiene test
(`test_la_api_no_arranca_en_produccion_con_ajustes_inseguros`).
