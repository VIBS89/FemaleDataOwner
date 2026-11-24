# Hoja de ruta on-premise

Actualizado el 2026-11-23 (chat de negocio, cifras agregadas y tareas programadas de Windows); el resto, el 2026-11-17.

DiscoveryDataAgent ya funciona de punta a punta en desarrollo: agente, API, web, MCP, BD `DiscoveryDataAgent` en SQL Server y compuerta de calidad. Lo que falta para el piloto no es la lógica del descubrimiento. Falta medirla con un LLM real y con preguntas reales, instalarla en un Windows Server del banco, cargar el conocimiento del dominio piloto y firmar la línea base. El destino es el piloto de 8 semanas con 10–15 usuarios en el dominio clientes / onboarding digital, evaluado contra los criterios D1–D7 de OP-01. Después del piloto vienen los roles desde Active Directory y la fase 1b (consulta de datos).

Diagrama de referencia: [arquitectura on-premise](../architecture/onpremise-architecture.html). Despliegue posterior en AWS: [hoja de ruta cloud](hoja-de-ruta-cloud.md).

Esta hoja no fija fechas. El calendario del backlog (seis sprints, piloto y decisión con fecha) es el supuesto S2 y hay que volver a confirmarlo: se hizo antes de la arquitectura simplificada. Solo se usan las semanas relativas del plan del piloto de F25.

## 1. Punto de partida

Verificado al 2026-11-17 (fuente: [plan de desarrollo](../PLAN-desarrollo.md) §1–§3 y [backlog](../backlog/on-premise.md) §1).

| Qué | Estado | Dónde |
|---|---|---|
| DiscoverFlow, lógica determinista, grafo del patrimonio, MCP | Hecho y medido, sin LLM | `src/discovery_data_agent/flows/`, `discovery/`, `graph/` |
| `DiscoveryDataAgent-API` y web Next.js (chat, Catálogo, Curación, Solicitudes, Métricas, Administración) | Hecho; web compilada el 2026-11-17 | `api/discovery_data_agent_api/`, `web/` |
| BD `DiscoveryDataAgent` (migraciones `001` y `002`, cuatro roles, historial temporal) | Hecho; probada en SQL Server 2022, no en 2016 | `db/discovery_data_agent/` |
| Auditoría fail-closed, catálogo, curación e inventario en la BD (bloques A, B, C1, C2) | Hecho; con `DISCOVERY_DATA_AGENT_DB` la API no guarda estado en disco | `storage/`, `audit/` |
| Compuerta `discovery-data-agent eval gate` (7 suites) y CI (`backend`, `web`, `cadena-de-suministro`) | Hecho; aprobada en los dos catálogos de prueba | `evaluation/gate.py`, `.github/workflows/calidad.yml` |
| Cadena de suministro: bloqueos con hash, imágenes base por digest, `pip-audit`, `npm audit`, SBOM | Hecho; la imagen no se ha construido con los bloqueos | `requirements/`, `api/Dockerfile`, `web/Dockerfile` |
| Chat de negocio y cifras agregadas (2026-11-23) | Chat hecho (asistente, seguimientos, aclaración por áreas, LLM `fast` en tres pasos, enriquecimiento con IA por defecto). Cifras: primer corte apagado por defecto (PRD §13, decisión 17); su revisión de seguridad independiente terminó el 2026-11-23 y sus bloqueantes están corregidos (quedan DT-78 a DT-80) | `discovery/assistant.py`, `discovery/figures.py`, `llm/nodes.py` |
| Calidad medida | Hit@1 y Hit@3 98,0 % (58 casos, BancosSQL) y 96,2 % (31 casos, VBank); 0 fugas. Set de chat de negocio (67 casos, 2026-11-23): Hit@1 97,8 % y Hit@3 100 %, con un fallo abierto (L09) | [plan §2](../PLAN-desarrollo.md#2-resultados-medidos) |

Lo que no existe, comprobado en el repo:
- No hay instalación para Windows Server: hoy solo hay `docker-compose.yml` (web y API) y los dos Dockerfile. De `deploy/windows/` existe solo `registrar-tareas.ps1` (tareas programadas); faltan IIS, `web.config`, certificado, firewall y respaldo.
- No hay comando `discovery-data-agent metrics report`: el CLI tiene `discover`, `llm smoke`, `eval`, `audit`, `db migrate`, `catalog` y `mcp serve`.
- No hay AskFlow completo (SQL generado, filtros, cruces, capa semántica ni `/ask`) ni lectura de grupos de AD. Existe un primer corte apagado por defecto: cifras agregadas (`COUNT`, `COUNT DISTINCT`, `SUM`, `AVG`) sobre una tabla (o con una unión a una tabla relacionada para desglosar), con plantilla de SQL fija (`src/discovery_data_agent/discovery/figures.py`; PRD §13, decisión 17). La revisión de seguridad independiente ya terminó y sus bloqueantes están corregidos; antes de activarlo en el piloto hay que resolver DT-78 a DT-80, aceptarlo con Seguridad de la Información y revisar D1–D7 de OP-01.
- Ninguna tarea está programada en un servidor: el script `deploy/windows/registrar-tareas.ps1` (refresco nocturno, purga semanal y, opcional, regresión semanal) está escrito y solo se verificó con análisis de sintaxis y `-WhatIf` en un equipo de desarrollo; no se ha registrado ni ejecutado en un Windows Server.

Límites de lo medido: los 89 casos de descubrimiento, las 25 preguntas de reporte y los 67 casos de chat los escribió el equipo, y todo se midió sin LLM. Los porcentajes no predicen el uso real.

## 2. Fases

El orden sigue lo que desbloquea cada cosa. Los carriles del [reparto](../backlog/reparto-5-devs.md) permiten avanzar D, F (scripts), E (conector) y la preparación de G en paralelo. Lo que sí es secuencial: no se puede validar F sin servidor, ni G sin cuenta de AWS, ni H sin F y G.

### Fase D · Métricas y brechas (bloque D)
**Objetivo.** Que cada semana del piloto se pueda reportar el scorecard sin leer preguntas.

| Entregable | HU / spec |
|---|---|
| `discovery-data-agent metrics report --from --to` con CSV y HTML, calculado desde vistas SQL del esquema `audit` | HU-23, OP-05 CA2, F25 CA2 |
| Reporte de brechas abiertas y cerradas por dominio | HU-32, F24 CA5 |
| Columna `recorded_at` en la auditoría y purga por ella (migración `003`, la añade el único dueño de migraciones) | Deuda de [calidad bancaria §5](../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto) |

**Terminado cuando.** Con auditoría de al menos una semana, el comando entrega tiempo hasta "✔", escalamientos, usuarios activos, % resueltas sin escalar y Hit@k del último set de evaluación, y los números salen de vistas del esquema `audit` sin leer el texto de las preguntas. Las 3 preguntas sin respuesta sembradas en el set aparecen en el reporte de brechas.

**Dependencias.** Del equipo: ninguna. Del banco: ninguna para construirlo. La decisión de qué lecturas se auditan además de las preguntas (PRD §13, pregunta 8) debe tomarla Seguridad antes de cerrar la auditoría para el piloto.

**Riesgos.** La línea base (HU-40) necesita el mismo vocabulario de métricas: conviene fijarlo con la Gerencia de Datos antes de firmarla.

### Fase E · Fuentes de conocimiento (bloque E)
**Objetivo.** Que el conocimiento del dominio piloto esté ingerido con datos personales redactados antes de que los usuarios lo prueben. Es lo que más mueve las preguntas de reporte: 28 % de Hit@1 solo con catálogo y 64 % con un glosario de prueba, sin LLM (16 % y 60 % el 2026-11-17; medición del equipo, [plan §2](../PLAN-desarrollo.md#2-resultados-medidos)).

| Entregable | HU / spec |
|---|---|
| Diccionario en Excel (el CSV ya funciona y escribe en la BD) | HU-25, F23 CA1 y CA5 |
| Ingesta de documentos con redacción de datos personales (Presidio; el detector actual reconoce seis formatos y no reconoce nombres ni direcciones) | HU-26, F23 CA3, OP-02 CA7, OP-06 CA3 |
| Linaje desde SSIS y SQL Server Agent | HU-27, F23 CA2 |

**Terminado cuando.** Un diccionario de 200 columnas reales queda como `data_dictionary` sin pisar lo `human` y una segunda carga no cambia nada. Un documento con un DUI y una cuenta de prueba no deja esos literales en `knowledge`. La pregunta "¿qué proceso llena X?" muestra el paquete o el job. Se repite la medición de las preguntas de reporte con los documentos reales.

**Dependencias.** Del equipo: la BD (hecha). Del banco (S6): ubicación y acceso de solo lectura a diccionarios y documentos, y acceso a `SSISDB` y `msdb` con un login técnico. Se puede adelantar el conector de carpeta y la redacción con documentos sembrados.

**Riesgos.** Los documentos pueden no estar donde se supone (pregunta 1 del PRD). El detector de datos personales no cubre nombres: la plantilla de las confirmaciones tampoco. Sin HU-26, el texto generado por IA se queda con confianza máxima 0,6.

### Fase F · Instalación y operación en Windows Server (bloque F)
**Objetivo.** Un entorno reproducible con scripts, en menos de un día laboral, con respaldo restaurable.

| Entregable | HU / spec |
|---|---|
| Scripts `deploy/windows/01…10` y `entorno.<env>.psd1` sin secretos: IIS con HttpPlatformHandler para la web (`/`) y la API (`/mcp`), cuentas gMSA, BD, aplicación, tareas, firewall, secretos con DPAPI, endurecimiento y verificación | HU-37, OP-07 |
| Tareas programadas: build nocturno (`catalog build --db` con `DISCOVERY_DATA_AGENT_BUILDER_HOSTS`), evaluación de regresión, purga de 180 días con la cuenta de mantenimiento; aviso por webhook de Teams. **Script escrito** (`deploy/windows/registrar-tareas.ps1`, con `-WhatIf` y `-Remove`; sin el aviso por Teams) y **sin probar en un servidor**: falta registrarlo con la gMSA, comprobar que cada tarea corre sin sesión iniciada y decidir si la purga usa la cuenta de mantenimiento (el script ejecuta las tres con la misma cuenta) | HU-18, HU-24 |
| Respaldo cifrado y prueba de restauración en otra instancia | HU-39 |
| Login de metadatos con DPAPI y Bedrock con IAM Roles Anywhere, sin claves de larga duración | HU-38 |
| SQL Server en la CI y DDL probado en la versión de la instancia del piloto | Deudas |
| Construir la imagen con los bloqueos, fijar `msodbcsql18` y `unixodbc`, firmar y escanear | Deudas |

**Terminado cuando.** Los criterios 1–8 de OP-07: los scripts 01–10 dejan el entorno funcionando y una segunda ejecución no cambia nada; ningún archivo lleva secretos; un build largo termina aunque IIS recicle; nunca hay dos procesos de la API; actualización y rollback en ≤ 30 min; la restauración cumple el RPO y el RTO; un proceso caído se reinicia; con `DISCOVERY_DATA_AGENT_ENV=prod` y un ajuste inseguro la API no arranca. Hoy ninguno se ha comprobado en un Windows Server. Además: la búsqueda del literal marcado en `TEMP` de las gMSA, carpetas de IIS y Visor de eventos (OP-06 CA4), y el streaming de `/api/discover/stream` sin búfer a través de IIS.

**Dependencias.** Del equipo: los scripts se pueden escribir ya. Del banco (S10): Windows Server de qa y del piloto, gMSA, certificado de la PKI, instancia SQL Server para la BD `DiscoveryDataAgent`, permisos del DBA. Los scripts solo se validan con el servidor.

**Riesgos.**
- El DDL se probó en SQL Server 2022: puede fallar en 2016.
- El instalador debe fijar `DISCOVERY_DATA_AGENT_ENV`: sin ella vale `dev` y no se exige ningún ajuste seguro.
- Los valores "⚠️ propuesto" de OP-07 (99 % de disponibilidad en horario laboral, RPO 15 min, RTO 4 h, reinstalación en ≤ 1 día) los tienen que confirmar Plataformas y el DBA.
- Un reinicio de la API cierra las sesiones por diseño: hay que avisar a los usuarios en cada actualización.

### Fase G · Bedrock y preguntas reales (bloque G)
**Objetivo.** Saber si el agente cumple D1, D2 y D5 con el modelo real y con preguntas de usuarios.

| Entregable | HU / spec |
|---|---|
| Bedrock de punta a punta: `discovery-data-agent llm smoke`, `eval gate --models`, p50/p95 y coste por pregunta; invocation logging desactivado | HU-35, F16 |
| Batería de inyección y guardas repetida con el modelo real y revisada con Seguridad | HU-36 |
| Set de 50–80 preguntas reales con los activos validados por un experto y 5 sin respuesta | HU-33, F25 |
| Decisión sobre Guardrails de Bedrock | PRD §13, pregunta 6 |

**Terminado cuando.** Sobre el set real y con Bedrock: Hit@3 ≥ 85 %, Hit@1 ≥ 65 %, MRR ≥ 0,75, calibración ≥ 85 %, 0 inventados, 0 fugas, p50 < 5 s y p95 < 10 s; `eval gate --models` aprueba `inyeccion` y `guardas`.

**Dependencias.** Del banco: cuenta de AWS con Bedrock e IAM Roles Anywhere (S4), steward funcional y técnico asignados con tiempo (S9), preguntas reales de los usuarios, revisión de la batería por Seguridad (S7). Se puede adelantar: corregir B14 y eng-06 si el set real lo pide, y la recarga parcial del índice.

**Riesgos.** Si el set real baja el acierto, hay que ajustar con preguntas que no se usaron para ajustar (regla del plan). Las preguntas de estudio apenas se mueven con conocimiento (25 % → 37,5 % en la medición de prueba). La ruta de salida a Bedrock depende del proxy corporativo.

### Fase H · Piloto de 8 semanas (bloque H)
**Objetivo.** Probar la hipótesis central de OP-01 y decidir cómo seguir.

| Semana (F25) | Actividad | Entregable |
|---|---|---|
| 0–1 | Estudio de tiempos (15–20 búsquedas por perfil), encuesta de 2 semanas a expertos, etiquetas `usa-discovery-agent` y `reproceso-fuente` | Línea base firmada (HU-40) |
| 1–3 | Ingesta del dominio piloto con steward asignado | Catálogo y set validado |
| 2–3 | El steward revisa los 100 activos más relevantes | % de descripciones revisadas |
| 4–7 | Uso real de 10–15 colaboradores de varios perfiles | `discovery-data-agent metrics report` semanal |
| 8 | Evaluación contra la línea base | Informe con D1–D7 y las 4 métricas de negocio (HU-41) |

**Terminado cuando.** Existe el informe de la semana 8 que compara D1–D7 con sus umbrales (D1 Hit@3 ≥ 85 % y Hit@1 ≥ 65 %, D2 calibración ≥ 85 %, D3 −50 % de tiempo de localización, D4 −30 % de consultas a expertos, D5 p50/p95 < 5 s / < 10 s, D6 0 fugas, D7 ≥ 70 % de usuarios activos 2 de 4 semanas) y termina en una recomendación: fase 1b, más dominios, AWS o producción on-premise.

**Dependencias.** Todas las historias *Must* de E1–E8 (HU-41), la línea base (HU-40) y el gestor de requerimientos y canal de consultas identificados (S13). Soporte de pantallas: el carril de API y web.

**Riesgos.** Baja adopción, stewards sin tiempo y permisos heredados que limitan la "democratización" (PRD §12). Un reinicio de la API durante el piloto cierra sesiones.

### Fase R · Roles desde Active Directory (después del piloto)
**Objetivo.** Sustituir la lista de responsables por login por grupos de AD (HU-13, *Should*).

**Entregables.** Asociación login–cuenta de AD (`curation.user_directory`) y lectura de grupos por LDAP de solo lectura con la gMSA. Con ella queda superada la política de roles por nombre de login (`identity_trusted`, pregunta 9 del PRD). En el piloto los roles se asignan por login SQL (`DISCOVERY_DATA_AGENT_ADMINS` y la tabla `curation.steward`), que OP-04 admite "en su defecto".

**Terminado cuando.** Un login asociado inicia sesión con los grupos de su cuenta; uno sin asociación tiene `groups = []` y solo el rol `consumer`.

**Dependencias.** LDAP de solo lectura (S10). Del equipo: ninguna.

### Fase 1b · Consulta de datos (después del piloto, si 1a cumple)
**Objetivo.** Responder preguntas de cifras: AskFlow, métricas certificadas y análisis (RF-40 a RF-42).

**Ya adelantado (2026-11-23).** Un subconjunto acotado de F3, F6 y F8: cifras agregadas sobre una tabla con plantilla fija y la credencial del usuario, apagadas por defecto. Sigue aquí todo lo que ese corte no hace: SQL generado por un LLM, filtros de fecha y de valor, condiciones que combinan tablas, cruces entre bases o sistemas, uniones de más de un salto, capa semántica, `/ask` y `sqlglot` (PRD §13, decisión 17).

**Alcance (OP-01).** F3 a F10 completos (intención, enlace a esquema, valores en vivo, planner, validator, executor, verifier con juez y analyst), F20 con biblioteca de análisis determinista sin código libre, F21 capa semántica (esquema `semantic` de la BD, una migración nueva) y `/ask` en la API, la web y `/mcp`. Consulta sobre 1 o 2 BDs del dominio, en réplica o copia de solo lectura.

**Terminado cuando.** Los 7 criterios de OP-01 §fase 1b: precisión de ejecución ≥ 80 % en 30–50 preguntas con SQL de referencia, calibración (≥ 70 % de las incorrectas con confianza < 0,6), 0 ejecuciones indebidas, permisos por usuario con error 229 manejado, latencia p50/p95 < 15 s / < 40 s en el MVP, coste Bedrock por pregunta medido y ≥ 70 % de 👍.

**Riesgos.** La infraestructura que citan las specs de 1b (juez, sandbox) se revisa contra PRD §13 antes de implementarla: las decisiones 9–16 retiraron piezas que esas specs todavía nombran. Ejecutar SQL sobre datos de clientes cambia el perfil de residencia: el diseño de 1a lee solo metadatos, y el primer corte de cifras ya lee agregados con el login del usuario cuando se activa (sin persistir valores).

## 3. Requisitos de infraestructura

Fuentes: [OP-01](../specs/on-premise/OP-01-despliegue-local.md) y [OP-07](../specs/on-premise/OP-07-instalacion-operacion.md). Los valores marcados "propuesto" los confirman Plataformas y el DBA.

| Recurso | Requisito | Origen |
|---|---|---|
| Servidor de aplicación (piloto) | Windows Server 2022 o 2025; 4 vCPU, 16 GB de RAM, 100 GB de disco para 3–20 usuarios; el catálogo y el conocimiento del dominio piloto deben caber en RAM | OP-01 §Dimensionamiento |
| Servidor de qa | Otro Windows Server instalado con los mismos scripts; no comparte BD, gMSA ni certificado con el piloto | OP-07 §Entornos |
| Software en el servidor | Roles de IIS, HttpPlatformHandler, ODBC Driver 18 for SQL Server, Python 3.12, Node.js LTS | OP-07 script 01 |
| Cuentas | gMSA para la web, la API, el Builder y mantenimiento; la de la API en `discovery_data_agent_app`, la del Builder en `discovery_data_agent_builder`, la de mantenimiento en `discovery_data_agent_maintenance` | OP-03, OP-07 scripts 02–03 |
| Certificados | TLS de la PKI corporativa en IIS (443, HTTP redirige, HSTS); certificado de clave no exportable para IAM Roles Anywhere | OP-04, OP-01 |
| Firewall | Entrada solo en 443 desde las redes de usuarios; salida a SQL Server (1433), al proxy (Bedrock, webhook de Teams, SharePoint Online si se usa), a AD (LDAP y Kerberos) y al servidor de archivos (SMB 445) | OP-04 §IIS |
| BD `DiscoveryDataAgent` | Instancia SQL Server 2016 o posterior gestionada por el DBA; la BD vacía la crea el DBA; modelo de recuperación completo; TLS validado (`Encrypt=yes`, sin `TrustServerCertificate`) | OP-02, OP-07 |
| Respaldo | Completo diario, diferencial cada 6 h, log cada 15 min, con `WITH ENCRYPTION`; retención no mayor que la de la auditoría (180 días) | OP-07 |
| Recuperación | RPO 15 min y RTO 4 h (propuesto); reinstalación del servidor en ≤ 1 día laboral | OP-07 |
| Disponibilidad | 99 % en horario laboral, lunes a viernes de 7:00 a 19:00 (propuesto); un solo servidor, sin alta disponibilidad | OP-07 |
| Login de metadatos | `VIEW DEFINITION`, `VIEW DATABASE STATE`, `SELECT` solo en la réplica, lectura de `SSISDB` y `msdb`; gMSA o login SQL cifrado con DPAPI | OP-03, F18 |
| AWS (solo Bedrock) | IAM Roles Anywhere; política de mínimo privilegio con `bedrock:InvokeModel` y `bedrock:InvokeModelWithResponseStream` sobre un modelo; invocation logging desactivado | OP-01 §Configuración AWS |
| Monitoreo | El existente del banco (SCOM o Zabbix, supuesto S11) con alertas desde el Visor de eventos y `/health/metrics` | OP-05 |

Para confirmar con el banco: ningún documento dimensiona la instancia SQL Server de la BD `DiscoveryDataAgent` (CPU, memoria, disco). Como vive en una instancia gestionada por el DBA, hay que pedirle el tamaño.

Configuración obligatoria en qa y prod: la API no arranca sin los ajustes de [calidad bancaria §4](../calidad-bancaria.md#4-configuración-obligatoria-en-qa-y-prod), entre ellos `DISCOVERY_DATA_AGENT_ENV`, cookie segura, `DISCOVERY_DATA_AGENT_MCP_HOSTS`, `DISCOVERY_DATA_AGENT_ADMINS_ONLY` con `DISCOVERY_DATA_AGENT_ADMINS`, `DISCOVERY_DATA_AGENT_LOG_DIR` y `DISCOVERY_DATA_AGENT_DB` sin contraseña.

## 4. Dependencias externas

| Qué se necesita | De quién | Fase | Qué se adelanta sin ello |
|---|---|---|---|
| Cuenta de AWS con Bedrock e IAM Roles Anywhere (S4) | Nube | G, F (HU-38) | Batería en modo determinista, corrección de B14 y eng-06 |
| Steward funcional y técnico con tiempo (S9) | Gerencia de Datos | G, H | Herramienta de captura del set |
| 50–80 preguntas reales validadas (HU-33) | Gerencia de Datos y usuarios | G | Nada que sustituya el set; el del equipo sigue como regresión |
| Ubicación y acceso a diccionarios y documentos; acceso a `SSISDB` y `msdb` (S6) | Gerencia de Datos | E | Excel, conector de carpeta, redacción con documentos sembrados |
| Windows Server de qa y del piloto, gMSA, certificado PKI (S10) | Plataformas y Seguridad | F | Escribir los scripts; SQL Server en la CI |
| Instancia SQL Server 2016+ para la BD `DiscoveryDataAgent`, DBA | Plataformas | F | Probar el DDL en una 2016 de desarrollo si se consigue |
| LDAP de solo lectura (S10) | Plataformas y Seguridad | R | Diseño de la asociación login–AD |
| Gestor de requerimientos y canal de consultas (S13) | Gerencia de Datos | H (línea base) | Plantilla del estudio de tiempos y de la encuesta |
| Decisiones de Seguridad: Guardrails, lecturas auditadas, batería de inyección (S7, preguntas 6 y 8) | Seguridad | G, D | Implementar ambas variantes detrás de configuración |
| Revisión de Plataformas y Seguridad de las specs OP; valores "propuesto" de OP-07 | Plataformas y DBA | F | Trabajar con los valores propuestos |
| Canal de notificación a stewards (S12, pregunta 4) | Gerencia de Datos | F | Webhook de Teams, que es lo construido |

## 5. Camino crítico al piloto

La secuencia mínima, en orden de dependencia:

1. **Pedir ya al banco** lo que más tarda: cuenta AWS (S4), steward y preguntas (S9), servidores, gMSA y certificado (S10), documentos y `SSISDB` (S6), gestor de requerimientos (S13).
2. **Mientras llega:** bloque D (`metrics report`), scripts de F, conector y redacción de E, SQL Server en la CI.
3. **Servidor del banco disponible** → validar los scripts 01–10, crear la BD, `discovery-data-agent db migrate`, probar el DDL en la versión real → prueba de restauración (HU-39, OP-07 la exige antes del piloto) → tareas programadas.
4. **Cuenta AWS disponible** → `llm smoke` → `eval gate --models` → set real con el steward → Hit@k, calibración y latencia con Bedrock (O8).
5. **Línea base firmada** (semanas 0–1 de F25) → ingesta del dominio piloto (E) y curación de los 100 activos → arranca el uso real.

Formalmente HU-41 pide todas las historias *Must* de E1–E8. Hoy faltan por cerrar entre ellas HU-18, HU-23, HU-25 (Excel), HU-26, HU-33, HU-35, HU-37 y HU-38. HU-27, HU-32, HU-24, HU-36 y HU-39 son *Should*, pero OP-07 exige la prueba de restauración y OP-01 la regresión antes del despliegue.

## 6. Decisiones abiertas que mueven la ruta

| Decisión | Quién | Efecto |
|---|---|---|
| Calendario y capacidad del equipo (S2, S3) | Líder técnico y Gerencia de Datos | Sin él no hay fechas |
| Política de roles por nombre de login (pregunta 9) | Banco | Se supera con HU-13 |
| Si un responsable ve en Curación activos que su login no lee (pregunta 7) | Seguridad y Gerencia de Datos | Cambia la cola de revisión |
| Qué lecturas se auditan además de las preguntas (pregunta 8) | Seguridad | Cambia el esquema de auditoría y su volumen |
| Guardrails de Bedrock en 1a (pregunta 6) | Seguridad | Puede añadir `bedrock:ApplyGuardrail` y trabajo en el gateway |
| ¿Se mantienen los permisos heredados para metadatos después del piloto? (pregunta 5) | Gerencia de Datos | Alcance de la fase 2 |
| Servidores y ambientes del piloto y logins comunes (pregunta 3) | Gerencia de Datos | Alcance de HU-10 y del inventario |
| Sacar `BancosSQL.zip` (13 MB) del repo o pasarlo a Git LFS | Líder técnico | Higiene del repo |
| Integrar `feat/congruencia-y-persistencia` en `main`: no está publicada | Líder técnico | Hasta entonces los carriles no tienen base común |
| Si el SQL Server de producción on-premise será el destino final o se pasa a AWS | Gerencia de Datos | Ver [hoja de ruta cloud](hoja-de-ruta-cloud.md) |

## 7. Qué queda fuera y por qué

| Fuera | Motivo |
|---|---|
| Fase 1b dentro del piloto | OP-01 la condiciona a que 1a cumpla D1–D7 |
| Alta disponibilidad del servidor de aplicación | Fuera del alcance de OP-01; exigiría sacar el SessionVault de la memoria y un grupo de disponibilidad de SQL Server |
| SSO con Kerberos | Evolución de OP-03, sujeta a prueba de concepto |
| Código Python libre (F20), `candidates: 2`, fallback automático a NIM con datos reales | Won't de esta versión (backlog §4) |
| Embeddings, Full-Text, tablas de grafo, Chainlit, servicio Builder, jobs de SQL Server Agent | Retirados por PRD §13, decisiones 9–12 |
| Despliegue en AWS | Posterior al piloto: [hoja de ruta cloud](hoja-de-ruta-cloud.md) |
| Prueba de penetración, revisión de IIS y TLS, SIEM | Se hacen con el banco, fuera del código ([calidad bancaria §5](../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto)) |

## Deuda técnica que entra en cada fase
El registro completo, con evidencia y esfuerzo, está en [deuda técnica](deuda-tecnica.md). Aquí solo se reparte por fase
lo que conviene cerrar junto con sus entregables.

| Cuándo | Deudas | Por qué entonces |
|---|---|---|
| Antes de repartir el trabajo | DT-39 (SQL Server en la CI), DT-17 y DT-16 (partir `main.py`) | Son baratas o evitan que cinco personas choquen |
| Fase D | DT-04 (fecha de la auditoría, migración `003`), DT-35 y DT-27 (métricas desde la BD), DT-32 (calibración) | El informe del piloto sale de la auditoría |
| Fase E | DT-05 y DT-61 (datos personales en textos), DT-70 (entrada de diccionarios y dueños) | Es el mismo código que la ingesta de documentos |
| Fase F | DT-44 y DT-33 (instalación y purga programada), DT-02 (activar `TRUST_FORWARDED_FOR` en la web y `DISCOVERY_DATA_AGENT_TRUST_PROXY` en la API detrás de IIS y probar el bloqueo de login por origen), DT-45 y DT-47 (imagen), DT-06, DT-07 y DT-58 (configuración y logs que fallan en silencio), DT-66 y DT-69 (cuenta de mínimo privilegio y hosts del Builder), DT-36 (SQL Server 2016) | Solo se ven al instalar en un servidor real |
| Fase G | DT-30 y DT-29 (modelo y preguntas reales), DT-59, DT-60 y DT-63 (lo que falta del camino con modelo), DT-21 (corte por fallos) | Se cierran al probar Bedrock de punta a punta |
| Fase H | DT-10 y DT-11 (decisiones del banco sobre lecturas auditadas y alcance del responsable), DT-37 (alerta si falla la auditoría) | Deben estar resueltas antes de abrir el piloto a usuarios |
| Después del piloto | DT-46 (estado en memoria de un solo proceso), DT-09 (token en el cuerpo del login) | Solo pesan con más usuarios o con más de un proceso |

## Nota: contradicciones y vacíos entre las fuentes

- **Dónde va HU-24.** El plan y el reparto la ponen en el bloque F; el backlog §3 pone HU-24 en el bloque D (depende de B). Aquí va en F, porque lo que falta son las tareas programadas.
- **Frecuencia de la evaluación.** HU-24 y el reparto dicen "evaluación semanal"; OP-01 y OP-07 la ponen tras cada build nocturno.
- **HU-13 antes o después del piloto.** El reparto la sitúa en la etapa 2 (antes del piloto); PRD §11 la llama "mejora posterior" y el backlog la deja en H "si hay LDAP". Aquí va después, salvo que llegue LDAP antes.
- **Cuándo se necesita al steward.** PRD §11 lo pide para las semanas 2–3 del piloto; S9 lo pide antes (sprint 5), porque el set de evaluación hace falta antes de empezar.
- **Duración del piloto.** PRD §10 dice fase 1a en las semanas 1–8, tras la preparación de las semanas 0–1; el plan de F25 numera de 0 a 8, nueve semanas. Aquí "8 semanas" es la ventana 1–8 y la línea base va en 0–1.
- **Calendario.** El del backlog (S2) es anterior a la simplificación y no se usa.
- **Texto antiguo.** El estado de HU-33 del 2026-11-16 aún cita 56 casos y la cifra "4 % → 40 %"; lo vigente es 89 casos y 16 % → 60 % (el propio bloque lo corrige después).
- **Vacíos.** No hay tamaño de la instancia SQL Server de `DiscoveryDataAgent`; el servidor de qa no figura en la lista de necesidades al banco del plan §7 aunque OP-07 lo exige; los puntos de las historias no se han reestimado tras los cambios de contenido de HU-04, HU-05 y HU-07.
