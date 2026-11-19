# OP-07 — Instalación, entornos y operación · on-premise

> Completa [OP-01](OP-01-despliegue-local.md) con lo que en cloud native cubren la IaC, los entornos y los requisitos no funcionales de
> [CN-01](../cloud-native/CN-01-despliegue-aws.md). Specs relacionadas: [OP-04](OP-04-interfaces.md) IIS · [OP-05](OP-05-auditoria-observabilidad.md) alertas · [OP-06](OP-06-residencia-datos.md) residencia de datos.
>
> Los valores marcados **⚠️ propuesto** salen de la revisión del 2026-10-27 y los tienen que confirmar Plataformas y el DBA antes del piloto.

## Objetivo
Que cualquier administrador de Plataformas pueda montar, actualizar, respaldar y recuperar un entorno de ConverData igual al del piloto
**solo con los scripts del repo y esta spec**, sin pasos manuales no documentados y sin secretos en archivos.

## Decisión (2026-10-27, ⚠️ propuesto): modelo de procesos
OP-01 hablaba a la vez de "servicios de Windows" y de procesos que lanza HttpPlatformHandler. Queda así:

> **Revisión 2026-10-27:** [OP-08](OP-08-interfaz-web.md) propone que `ConverData-UI` sea la salida standalone de Next.js (`node server.js`,
> Node.js 20 LTS en `01-prerrequisitos.ps1`) y que `ConverData-API` corra como servicio de Windows en `127.0.0.1:8000`. El entorno **dev** se
> detalla por situaciones (sin infraestructura, LLM local, SQL Server local, Bedrock, servidor de QA) en [OP-09](OP-09-situaciones-desarrollo.md).

| Proceso | Cómo corre | Quién lo supervisa | Motivo |
|---|---|---|---|
| `ConverData-UI` (Chainlit) | Aplicación de IIS con su grupo de aplicaciones; HttpPlatformHandler lanza uvicorn | IIS (HttpPlatformHandler reinicia el proceso si cae) | Recomendado por Microsoft frente a WFastCGI; WebSockets por IIS |
| `ConverData-API` (FastAPI + DiscoverFlow + `converdata-mcp` + SessionVault) | Aplicación de IIS con su grupo de aplicaciones; HttpPlatformHandler lanza **un solo** proceso uvicorn | IIS | SessionVault exige un solo proceso (OP-03) |
| `ConverData-Builder` (Catalog Builder + `converdata-discovery` + conectores F23 + Presidio) | **Servicio de Windows**, escuchando solo en `127.0.0.1:8100`; IIS le reenvía `/api/admin/*` con URL Rewrite + ARR | Administrador de servicios de Windows (acciones de recuperación: reiniciar a los 1, 5 y 15 min) | La ingesta es un batch largo: no debe depender del ciclo de vida de IIS |

Configuración obligatoria de los grupos de aplicaciones de UI y API: identidad gMSA, `idleTimeout = 0`, reciclaje periódico desactivado y
**reciclaje superpuesto desactivado** en `ConverData-API` (`disallowOverlappingRotation = true`): con reciclaje superpuesto habría dos procesos
con dos SessionVault distintos durante unos segundos.

## Entornos
| Entorno | Servidor de aplicación | BD `ConverData` | BDs de datos | LLM | Datos |
|---|---|---|---|---|---|
| **dev** | Estación del desarrollador, sin IIS (`converdata` CLI y uvicorn directo) | SQL Server 2025 Developer local, o YAML con `InMemoryVectorStore` | BancosSQL, AdventureWorks | Ollama (`environment: local`) o NIM con datos de prueba (F16) | Solo de prueba |
| **qa** | Windows Server de QA, instalado con los mismos scripts que el piloto | Instancia SQL Server 2025 de QA | Servidores de QA del dominio piloto | Bedrock | Metadatos reales de QA; consultas solo a QA |
| **piloto / prod** | Windows Server del piloto (OP-01 §Dimensionamiento) | Instancia SQL Server 2025 gestionada por el DBA | Producción y QA del dominio piloto (réplica legible si existe) | Bedrock (cuenta del cliente, F17) | Reales |

Reglas: un cambio llega a piloto solo después de pasar en qa los tests y `converdata eval discovery` sin regresión (F25 CA3); qa y piloto no
comparten BD `ConverData`, gMSA ni certificado; NIM y Ollama están bloqueados por configuración fuera de dev (guarda de residencia de F16).

## Requisitos no funcionales
| Área | Requisito | Origen |
|---|---|---|
| Latencia | Descubrimiento p50 < 5 s y p95 < 10 s; consulta de datos (fase 1b) p50 < 15 s y p95 < 40 s en el MVP | OP-01, F22 |
| Disponibilidad del piloto | **99 % en horario laboral** (lunes a viernes, 7:00–19:00); fuera de ese horario, sin compromiso. Un solo servidor de aplicación (sin alta disponibilidad, OP-01 §Fuera del alcance) | ⚠️ propuesto |
| Recuperación de la BD `ConverData` | **RPO 15 min** (modelo de recuperación completo y respaldo de log cada 15 min) y **RTO 4 h** | ⚠️ propuesto |
| Recuperación del servidor de aplicación | Reinstalación con los scripts en ≤ 1 día laboral; no guarda estado propio (las sesiones se pierden por diseño, OP-03) | ⚠️ propuesto |
| Capacidad | 3–20 usuarios simultáneos en el piloto; 30 preguntas por minuto y sesión; tope diario de tokens por usuario (OP-04) | OP-01, OP-04 |
| Coste | Coste de Bedrock por pregunta medido y reportado cada semana en `converdata metrics report` (F25) | OP-01 criterio 6 |
| Seguridad | TLS con la PKI corporativa en IIS y `Encrypt=yes` en SQL Server; sin secretos en archivos; gMSA para todos los procesos | OP-03, OP-04 |

## Instalación reproducible
Scripts PowerShell idempotentes en `deploy/windows/` (se pueden volver a ejecutar sin cambiar nada si el servidor ya está bien), con un
archivo de parámetros por entorno `deploy/windows/entorno.<env>.psd1` que **no contiene secretos** (solo nombres de servidor, rutas,
huellas de certificado y nombres de gMSA).

| Paso | Script | Qué hace |
|---|---|---|
| 1 | `01-prerrequisitos.ps1` | Roles de IIS (con WebSockets), URL Rewrite, ARR, HttpPlatformHandler, ODBC Driver 18 for SQL Server, Python 3.12 y uv |
| 2 | `02-cuentas.ps1` | Instala y prueba las gMSA (`Install-ADServiceAccount`, `Test-ADServiceAccount`) |
| 3 | `03-bd.ps1` | Aplica los scripts numerados de `db/converdata/` con `sqlcmd` y registra la versión en `dbo.schema_version` (ver §Migraciones) |
| 4 | `04-aplicacion.ps1` | Despliega la versión en `%ProgramFiles%\ConverData\releases\<versión>` con `uv sync --frozen` y apunta el enlace `current` a ella |
| 5 | `05-iis.ps1` | Sitio HTTPS, grupos de aplicaciones (§Decisión), `web.config` de UI y API, enlace del certificado, HSTS, Request Filtering, logs W3C sin cuerpos, restricción de IP de `/api/admin/*` |
| 6 | `06-builder.ps1` | Registra el servicio `ConverData-Builder` con su gMSA y sus acciones de recuperación |
| 7 | `07-firewall.ps1` | Reglas de entrada y salida de OP-04 §IIS |
| 8 | `08-sqlagent.ps1` | Jobs de SQL Server Agent: refresco nocturno e ingesta (OP-02), purga de 180 días y evaluación semanal (OP-05) |
| 9 | `09-endurecimiento.ps1` | Controles de memoria de OP-06: sin volcados de los procesos de ConverData en WER, `SeDebugPrivilege` solo para administradores |
| 10 | `10-verificar.ps1` | Smoke test: `/health`, login con un login de prueba, `/api/discover` de una pregunta conocida y escritura en `audit` |

Los secretos que no son gMSA se cargan **a mano una vez** con un script interactivo que los cifra con DPAPI en el ámbito de la cuenta de
servicio (login de metadatos si no es gMSA, token de servicio de `/api/admin`, sal de MinHash). El certificado de IAM Roles Anywhere se
emite en el servidor con clave no exportable.

Rutas en el servidor:
| Ruta | Contenido |
|---|---|
| `%ProgramFiles%\ConverData\releases\<versión>\` y `current` | Código y entorno de Python de cada versión |
| `%ProgramData%\ConverData\config\` | `databases.yaml`, `models.yaml`, `settings.yaml` y `owners.yaml` del entorno (sin secretos) |
| `%ProgramData%\ConverData\secrets\` | Blobs cifrados con DPAPI; ACL solo para las gMSA y los administradores |
| `%ProgramData%\ConverData\logs\` | Logs JSON rotados (OP-05) |

## Migraciones de la BD `ConverData`
- Scripts numerados `db/converdata/NNN_<descripcion>.sql`, aplicados en orden; `dbo.schema_version` guarda número, fecha y quién los aplicó.
- **Solo hacia adelante y compatibles con la versión anterior de la aplicación** (expandir y después contraer): una columna nueva se agrega
  nullable o con valor por defecto, y se elimina lo viejo en una versión posterior. Así el rollback de la aplicación no exige revertir la BD.
- Las tablas temporales se alteran con `SYSTEM_VERSIONING = OFF` y `ON` dentro de la misma transacción del script.

## Actualización y rollback
1. Aplicar en qa y pasar los tests, `10-verificar.ps1` y `converdata eval discovery` sin regresión.
2. En piloto: aplicar migraciones (`03-bd.ps1`), desplegar la versión nueva (`04-aplicacion.ps1`) y cambiar el enlace `current`.
3. Reciclar UI y API y reiniciar `ConverData-Builder` **fuera de una ingesta en curso** (el script lo comprueba).
4. Avisar a los usuarios: las sesiones se pierden al reiniciar la API (OP-03) y hay que volver a iniciar sesión.
5. Rollback: apuntar `current` a la versión anterior y reciclar; las migraciones no se revierten (por la regla de compatibilidad).

## Respaldo y recuperación
- BD `ConverData`: completo diario, diferencial cada 6 h y log cada 15 min, con **`BACKUP ... WITH ENCRYPTION`** (contiene preguntas y SQL,
  D2) y acceso solo para el DBA. La retención de los respaldos no puede superar la de la auditoría (180 días, OP-05).
- Configuración (`%ProgramData%\ConverData\config\`): versionada en un repositorio interno; los secretos no se respaldan, se vuelven a cargar.
- No se respalda: SessionVault (por diseño), logs (se rotan), sketches de F19 (no existen fuera de memoria).
- **Prueba de restauración** antes del piloto y cada trimestre: restaurar en otra instancia, apuntar un servidor de qa a ella y repetir el
  smoke test y el set de evaluación.

## Operación
| Tarea | Frecuencia | Cómo |
|---|---|---|
| Revisar el historial de los jobs de SQL Server Agent | Diaria | Database Mail avisa de fallos (OP-02 CA6) |
| Revisar alertas y `/health/metrics` | Continua | Monitoreo existente (OP-05 §Alertas) |
| Renovar el certificado TLS y el de IAM Roles Anywhere | Antes de que expiren (alerta a 30 días, OP-05) | Script de renovación + `05-iis.ps1` |
| Rotar el login de metadatos (si es login SQL) y el token de `/api/admin` | Según la política de Seguridad de la Información | Script de carga de secretos + reinicio de `ConverData-Builder` |
| Reindexar vectores tras cambiar el modelo `embed` | Al cambiar de modelo | `POST /api/admin/catalog/refresh?reindex=true` y evaluación posterior |
| Prueba de restauración | Trimestral | §Respaldo y recuperación |

## Criterios de aceptación
1. En un Windows Server limpio, los scripts 01–10 dejan un entorno funcionando en ≤ 1 día laboral, y una segunda ejecución no cambia nada.
2. Ningún archivo de `deploy/windows/`, de `%ProgramData%\ConverData\config\` ni del repo contiene contraseñas, tokens ni claves (test con búsqueda de patrones).
3. Una ingesta de más de 2 h en `ConverData-Builder` termina aunque IIS recicle UI o API durante ese tiempo.
4. Con `ConverData-API` reciclada, nunca hay dos procesos de la API activos a la vez (comprobado con el Administrador de IIS durante el reciclaje).
5. Una actualización y su rollback se completan en ≤ 30 min sin perder registros de auditoría.
6. La prueba de restauración cumple el RPO y el RTO de §Requisitos no funcionales.
7. Si cae el proceso de UI o de API, IIS lo reinicia; si cae `ConverData-Builder`, el servicio se recupera solo (OP-04 CA5).
