# Hoja de ruta cloud (AWS)

Actualizado el 2026-11-17.

Hoy no hay nada desplegado en AWS. La infraestructura como código existe desde el 2026-11-22 en `deploy/aws/` (Terraform), sin aplicar en ninguna cuenta. Esta ruta es posterior al piloto on-premise y solo arranca si el informe de la semana 8 recomienda AWS (HU-41; PRD §10, fase 2). El destino es el despliegue mínimo de CN-01: las mismas dos imágenes que ya construye `docker compose` en una tarea de ECS Fargate detrás de un ALB interno, el Builder lanzado por EventBridge Scheduler, Bedrock por VPC endpoint y una VPN al SQL Server del banco. El banco conserva todo lo persistente: catálogo, conocimiento, curación y auditoría siguen en la BD `DiscoveryDataAgent` on-premise. AWS procesa y muestra.

Diagrama de referencia: [arquitectura cloud](../architecture/cloud-native-architecture.html). Camino previo: [hoja de ruta on-premise](hoja-de-ruta-on-premise.md).

Esta hoja no fija fechas ni plazos: las specs CN no los dan. Solo hay orden y dependencias.

## 1. Punto de partida

| Qué | Estado | Dónde |
|---|---|---|
| Specs CN-01 a CN-06 | Escritas y revisadas el 2026-11-16; nada de ellas está comprobado en AWS | `docs/specs/cloud-native/` |
| Imágenes `api/Dockerfile` y `web/Dockerfile` | Existen, con bloqueos con hash e imágenes base por digest; **la de la API no se ha construido con los bloqueos** y la CI no construye imágenes | `api/Dockerfile`, `web/Dockerfile` |
| `docker-compose.yml` con web y API | Existe; es lo que CN-01 toma como base | `docker-compose.yml` |
| Estado fuera del disco del servidor | Hecho: con `DISCOVERY_DATA_AGENT_DB` la API no guarda nada en disco (HU-04, HU-06, HU-09, HU-20). Falta probarlo en una tarea real | [plan](../PLAN-desarrollo.md) bloques A–C2 |
| Recarga del catálogo cuando el Builder corre en otra tarea | Hecho: la API comprueba la versión como mucho cada 15 s | CN-01 §Dependencias, punto 3 |
| Builder sin disco persistente | `catalog build --db` toma el inventario de la BD y trabaja en un directorio temporal; no probado en Fargate | CN-02 |
| Gateway de LLM con Bedrock | Sin probar de punta a punta (HU-35); `ChatBedrockConverse` no recibe claves, así que usa la cadena de credenciales por defecto | `src/discovery_data_agent/llm/factory.py` |
| Infraestructura como código | Terraform, una pila por entorno (`demo`, `qa`, `prod`) y el script `despliegue.sh`. Validado con `terraform validate` y planes de prueba; **sin aplicar en ninguna cuenta** | `deploy/aws/` ([guía](../../deploy/aws/README.md)) |
| Carpeta `deploy/` | Existe `deploy/aws/`; `deploy/windows/` para on-premise sigue prevista | `deploy/aws/` |

## 2. Qué se reutiliza y qué es trabajo nuevo

| Pieza | Se reutiliza tal cual del on-premise | Trabajo nuevo en AWS |
|---|---|---|
| Imagen de la API (FastAPI, DiscoverFlow, MCP, SessionVault, índice léxico) | Sí, la misma imagen y los mismos bloqueos | Construirla, subirla a ECR y escanearla; logs a salida estándar (hoy van a archivo) |
| Imagen de la web (Next.js) | Sí; reenvía `/api/*` a la API con `API_URL` | Cambiar `API_URL` a `http://localhost:8000` (en compose es `http://api:8000`) |
| BD `DiscoveryDataAgent`, migraciones `001`, `002` y las que haya, roles, auditoría | Sí, sin moverla ni copiarla | Alcanzarla por la VPN; resolver con qué cuenta entra la tarea (§5) |
| Lógica, prompts, guardas, compuerta `eval gate`, set de evaluación | Sí | Correr la compuerta contra qa en AWS |
| Configuración obligatoria de qa y prod ([calidad bancaria §4](../calidad-bancaria.md#4-configuración-obligatoria-en-qa-y-prod)) | Sí, como variables de la tarea | Valores propios: URL del ALB, `DISCOVERY_DATA_AGENT_MCP_HOSTS` con el nombre del ALB |
| Entrada | — | ALB interno con certificado de ACM, en lugar de IIS con la PKI |
| Programación del Builder | El mismo comando `discovery-data-agent catalog build --db` | EventBridge Scheduler con `RunTask`, en lugar del Programador de tareas |
| Secretos | — | Secrets Manager, en lugar de DPAPI |
| Cuentas | — | Roles IAM de tarea, en lugar de gMSA |
| Bedrock | Mismo modelo y misma política mínima | VPC endpoint con el rol de la tarea, en lugar del proxy con IAM Roles Anywhere |
| Logs y alarmas | Mismo formato JSON sin contenido | CloudWatch Logs con KMS y alarmas, en lugar del Visor de eventos |
| Red | — | VPC con subredes privadas, Site-to-Site VPN, VPC endpoints, sin NAT |
| Respaldo y purga de la BD | Los del DBA, igual que on-premise | Nada |

## 3. Fases

Las fases 1–5 se pueden solapar dentro de lo que dicen sus dependencias; las 6–8 vienen después de tener qa funcionando. CN-01 no separa los secretos en una fase propia: aquí van dentro de la infraestructura (fase 2) porque la tarea no arranca sin ellos.

### Fase 1 · Prerrequisitos y decisiones
**Objetivo.** Tener la cuenta, la red y las decisiones que bloquean el diseño.

| Entregable | Fuente |
|---|---|
| Cuenta de AWS para qa y para prod, con Bedrock habilitado en un modelo y *invocation logging* desactivado | CN-01, F17 |
| Diseño de la VPC (subredes privadas, sin ruta a internet) y de la VPN al banco; reglas del firewall on-premise que abren 1433 solo a las subredes de la tarea | CN-01 §Topología, CN-06 |
| Decisión de Seguridad: ¿la VPN puede llevar también tráfico de usuarios hacia el ALB? | CN-01 §Por confirmar |
| Decisión de Seguridad: Guardrails de Bedrock | PRD §13, pregunta 6 |
| Decisión: con qué cuenta entra la tarea a la BD `DiscoveryDataAgent` y con qué identidad entra el Builder a los SQL Server (§5) | CN-01 punto 3, CN-03 |
| ~~Decisión: Terraform o CDK, un stack por entorno~~ Terraform (`deploy/aws/`, 2026-11-22) | CN-01 §IaC |
| Decisión: tamaño de la tarea (referencia on-premise: 4 vCPU y 16 GB) | CN-01 §RNF |

**Terminado cuando.** Las decisiones están registradas, la VPN sube y desde una subred privada de prueba se alcanza el 1433 del SQL Server de qa con TLS validado.

**Dependencias.** Del banco: Seguridad de la Información, Redes (VPN y firewall), DBA (cuentas de BD). Del equipo: ninguna. Se puede adelantar el diseño de red y la comparación Terraform/CDK.

**Riesgos.** La VPN y las reglas de firewall son lo que más tarda y no se automatizan (CN-01 CA1 las excluye).

### Fase 2 · Infraestructura como código
**Objetivo.** Un stack por entorno que cree todo lo de CN-01 §IaC sin pasos manuales, salvo la VPN y el firewall del banco.

| Recurso | Fuente |
|---|---|
| VPC, subredes privadas y VPC endpoints (Bedrock, Secrets Manager, CloudWatch Logs, ECR), sin NAT | CN-01 §Red |
| Site-to-Site VPN (lado AWS) | CN-01 |
| Repositorio ECR | CN-01 |
| Secretos de servicio y su KMS: login de metadatos del Builder, código de instalación, credencial de la BD si se decide así, webhook de Teams | CN-03 §Secretos |
| Roles IAM: tarea de la API (`bedrock:InvokeModel` sobre el modelo, lectura de sus secretos, sus logs), tarea del Builder (lectura del secreto de metadatos), EventBridge (`ecs:RunTask`) | CN-03 §Roles IAM |
| Grupos de logs con KMS y alarmas | CN-05 |
| Etiquetas `app=discovery-data-agent` y `env` | CN-01 §RNF |

**Terminado cuando.** CN-01 CA1 y CA2: el stack de qa se crea sin pasos manuales salvo la VPN y el firewall, y ningún recurso tiene IP pública ni ruta a internet. El rol de la tarea de la API recibe `AccessDenied` al leer el secreto del login de metadatos (CN-03 CA3).

**Dependencias.** Fase 1. **Riesgos.** El primer IaC del proyecto: sin plantilla previa que reutilizar. Un recurso fuera de la lista de CN-06 CA2 (bucket, base de datos, índice) incumple la residencia.

### Fase 3 · Imágenes y registro
**Objetivo.** Imágenes construidas, escaneadas y publicadas, que son las mismas del on-premise.

| Entregable | Fuente |
|---|---|
| Construir `api/Dockerfile` con `requirements/runtime.lock` y arrancarla (no se ha hecho) | [calidad bancaria §5](../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto) |
| Añadir el build de las imágenes a la CI | idem |
| Fijar la versión de `msodbcsql18` y `unixodbc`; firma y escaneo de la imagen; publicar en ECR por digest | idem |
| Logs JSON a la salida estándar (hoy a archivo con `DISCOVERY_DATA_AGENT_LOG_DIR`, que qa y prod exigen) | CN-01 §Dependencias, punto 2; CN-05 |

**Terminado cuando.** Las dos imágenes están en ECR por digest, escaneadas, y el contenedor de la API arranca con `DISCOVERY_DATA_AGENT_ENV=qa` y falla con un mensaje claro si falta una variable obligatoria (CN-01 CA4).

**Dependencias.** Fase 2 (ECR). Del equipo: un cambio de código para los logs. **Riesgos.** La imagen lleva metadatos de prueba para el modo demo (CN-06): no arranca en qa ni prod, pero hay que decidir si se quitan. El contenedor de la API escucha en `0.0.0.0` (on-premise, en `127.0.0.1`); en Fargate está bien porque el puerto 8000 no se publica, pero debe comprobarse el grupo de seguridad (CN-04 CA6).

### Fase 4 · Despliegue de la tarea (web + API)
**Objetivo.** Un usuario de la red corporativa inicia sesión con su login SQL y recibe candidatos filtrados por sus permisos.

| Entregable | Fuente |
|---|---|
| Definición de tarea Fargate con dos contenedores (web en 3000, API en 8000 con un worker) y servicio con una sola tarea | CN-01 |
| ALB interno, HTTPS 443 con certificado de ACM: `/` a la web, `/mcp` a la API; `/health` como comprobación | CN-04 |
| Variables de qa: `DISCOVERY_DATA_AGENT_COOKIE_SECURE=1`, `DISCOVERY_DATA_AGENT_CORS_ORIGINS` y `DISCOVERY_DATA_AGENT_PUBLIC_URL` con la URL del ALB, `DISCOVERY_DATA_AGENT_MCP_HOSTS`, `DISCOVERY_DATA_AGENT_ADMINS_ONLY=1` con `DISCOVERY_DATA_AGENT_ADMINS`, `DISCOVERY_DATA_AGENT_SETUP_TOKEN`, `DISCOVERY_DATA_AGENT_LOG_DIR`, `DISCOVERY_DATA_AGENT_ALLOW_WINDOWS_AUTH` sin definir | CN-01 §Entornos, CN-04 |
| `config/models.yaml` con `data_mode: real`, un modelo de Bedrock y su región por VPC endpoint | F16 |
| Migraciones al día antes de desplegar (`discovery-data-agent db migrate`) | OP-07 §Migraciones |

**Terminado cuando.** CN-01 CA3 y CA6, CN-04 CA1–CA6 y CN-03 CA1, CA4–CA6: login real, 401 sin sesión y 403 para un `consumer` en `/curation` y `/admin`; dos usuarios con permisos distintos ven cada uno solo lo suyo; la pregunta 31 en un minuto da 429; Bearer en `/mcp`; al reiniciar la tarea las sesiones anteriores devuelven 401; el ALB no responde desde fuera de la red corporativa; y `discovery-data-agent eval gate` da en qa los mismos resultados que on-premise.

**Dependencias.** Fases 2 y 3, y Bedrock operativo (HU-35 hecha en on-premise). **Riesgos.** Faltan por confirmar `DISCOVERY_DATA_AGENT_TRUST_PROXY` detrás del ALB (el bloqueo por origen necesita la IP real) y el tiempo de inactividad del ALB para `/mcp` y el streaming de `/api/discover/stream`. Un despliegue continuo de ECS puede levantar una segunda tarea mientras la primera sigue: dos procesos con dos SessionVault, que es lo que OP-07 evita en IIS con el reciclaje superpuesto desactivado. Las fuentes no definen la configuración del despliegue de ECS; hay que fijarla para que nunca haya dos tareas (deducción de CN-01 "una sola tarea").

### Fase 5 · Builder programado (EventBridge + RunTask)
**Objetivo.** El refresco nocturno corre en AWS sin nada encendido entre ejecuciones.

| Entregable | Fuente |
|---|---|
| Definición de tarea del Builder con la imagen de la API y el comando `discovery-data-agent catalog build --db` | CN-02 |
| EventBridge Scheduler con `RunTask`, cada noche | CN-02 |
| Login de metadatos en Secrets Manager, inyectado con las variables que nombra el inventario (`metadata_user_env`, `metadata_password_env`), solo en esta tarea | CN-02, CN-03 |
| `DISCOVERY_DATA_AGENT_BUILDER_HOSTS` con los hosts permitidos (obligatoria en qa y prod) | OP-07, PRD §13 notas |
| Evaluación de regresión tras el build | OP-07, F25 |
| Fuentes de conocimiento: acceso del Builder a diccionarios y documentos por la VPN | CN-02 |

**Terminado cuando.** CN-02 CA1–CA6: un cambio de esquema on-premise aparece tras el ciclo nocturno; la tarea termina sola y con código distinto de 0 si falla (y eso dispara la alarma); no queda archivo ni objeto en AWS con catálogo; el login de metadatos no está en la tarea de la API.

**Dependencias.** Fases 2 y 3. Del banco: el login de metadatos (`VIEW DEFINITION`, `VIEW DATABASE STATE`, lectura de `SSISDB` y `msdb`). **Riesgos.** Sin gMSA, el Builder no puede entrar con "la cuenta del proceso": por defecto usa autenticación de Windows, que no existe en el contenedor (§5). Cómo lee la tarea una carpeta compartida SMB está por confirmar (CN-02). Hay que apagar la tarea del Programador de Windows cuando se encienda EventBridge, para no tener dos Builders.

### Fase 6 · Observabilidad y alarmas
**Objetivo.** Ver y reaccionar sin ver contenido.

| Entregable | Fuente |
|---|---|
| CloudWatch Logs de la tarea y del Builder, JSON sin contenido, cifrados con KMS; `DISCOVERY_DATA_AGENT_EVENT_LOG=0` | CN-05 |
| Contadores de `/health/metrics` llevados a métricas (filtros de métricas sobre los logs: por confirmar) | CN-05 |
| Alarmas: fallo de escritura de auditoría (crítica), VPN caída (crítica), destino del ALB no saludable o tarea reiniciada (crítica), 5xx > 5 % en 5 min, p95 > 10 s en 15 min, throttling o errores de Bedrock > 5 % en 5 min, Builder con error o sin correr, certificado a menos de 30 días | CN-05 |

**Terminado cuando.** CN-05 CA1–CA5: cada pregunta deja un registro en `audit`; con la VPN cortada las preguntas no reciben respuesta y se disparan las alarmas de VPN y de auditoría (fail-closed); un fallo provocado del Builder dispara su alarma; ninguna alarma lleva contenido.

**Dependencias.** Fases 4 y 5. Del banco: umbrales y canal de aviso (correo o el monitoreo del banco), retención del grupo de logs. **Riesgos.** Un corte de la VPN bloquea las respuestas por diseño. Hoy la alerta de fallo de auditoría ni siquiera existe on-premise (HU-37).

### Fase 7 · Pruebas de residencia de datos
**Objetivo.** Demostrar que AWS no persiste catálogo, preguntas ni auditoría.

| Prueba | Fuente |
|---|---|
| Búsqueda del literal marcado en CloudWatch Logs, en los access logs del ALB y en Secrets Manager, incluidos literales sembrados en documentos de prueba | CN-06 CA1 |
| Inventario de recursos de la cuenta: ningún bucket de catálogo, ninguna base de datos, ningún índice de búsqueda | CN-06 CA2, CN-01 CA5 |
| Tras detener la tarea, no queda catálogo, pregunta ni registro de auditoría en AWS | CN-01 CA5, CN-05 CA5 |
| *Model invocation logging* de Bedrock desactivado, con comprobación automática que avise si se activa (mecanismo por confirmar) | CN-06 CA3 |
| Subredes de la tarea sin ruta a internet | CN-06 CA4 |
| `discovery-data-agent eval gate` (`permisos`, `inyeccion`, `guardas`) con 0 fugas en qa, con el modelo de Bedrock | CN-06 CA5 |
| Un documento con un DUI y una cuenta de prueba no deja esos literales en la BD ni en los logs | CN-02 CA4 |
| Ningún secreto contiene un login de usuario | CN-03 CA2 |

**Dependencias.** Fases 4 a 6. Debe aprobar Seguridad de la Información. **Riesgos.** La prueba del literal marcado de hoy (`api/tests/test_marked_literals.py`) no cubre el cliente MCP, `/discover/stream`, el Visor de eventos ni los volcados de memoria: en AWS hay que repetirla sobre esas rutas y sobre CloudWatch.

### Fase 8 · Migración y convivencia con el on-premise
**Objetivo.** Pasar a los usuarios del servidor Windows a la tarea de Fargate sin perder nada y con vuelta atrás.

La BD `DiscoveryDataAgent` no se mueve: es la misma. Por eso lo que cambia es dónde corren los procesos (PRD §8.1, principio 7). Las fuentes no describen la migración; lo que sigue es el orden que se deduce de ellas.

| Paso | Detalle |
|---|---|
| 1. qa en AWS contra la BD de qa | Misma BD que el servidor de qa on-premise; comparar `eval gate` (CN-01 CA6) |
| 2. Prod en AWS en paralelo, sin usuarios | Mismos resultados que el piloto con el set real |
| 3. Corte | Un solo Builder activo (EventBridge, no el Programador de tareas); aviso a los usuarios: el cambio de URL cierra las sesiones |
| 4. Vuelta atrás | Apuntar a los usuarios de nuevo al servidor Windows, que sigue instalado; la BD no necesita revertirse |

**Riesgos.** Dos procesos de API contra la misma BD (uno on-premise, otro en AWS) no está probado: las fuentes dicen que "más de un proceso exige rediseñar ese estado" (PRD §13) y la prueba de convivencia no existe. Lo prudente es no tenerlos activos a la vez con usuarios. La auditoría es una sola BD, así que no hay nada que fusionar.

### Fase 9 · Escalar a más de una tarea (solo si se pide alta disponibilidad)
CN-01 dimensiona para 10–15 usuarios y una sola tarea. Escalar "exigiría sesiones compartidas" (CN-01 §RNF) y es un rediseño, no una configuración.

| Qué vive hoy en la memoria de un proceso | Fuente |
|---|---|
| SessionVault (login SQL cifrado con una clave que se genera al arrancar) | OP-03, CN-03 |
| Bloqueo de login, ritmo por usuario y tope diario de tokens | CN-04, [calidad bancaria §5](../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto) |
| Trazas de respuestas mostradas, confirmaciones recientes, inventario leído al arrancar, responsables cacheados 5 s | calidad bancaria §5 |
| Índice léxico y grafo (se reconstruyen al cargar; no es problema de estado, sí de memoria por tarea) | OP-02 |

Restricción: los logins de usuario no pueden pasar a Secrets Manager, disco ni logs (CN-06). Las fuentes no eligen el mecanismo. Hay que decidirlo con Seguridad antes de empezar.

## 4. Dependencias externas

| Qué se necesita | De quién | Fase | Qué se puede adelantar sin ello |
|---|---|---|---|
| Informe de la semana 8 con recomendación AWS y decisión de invertir | Gerencia de Datos | Todas | Nada irreversible: solo diseño |
| Cuentas de AWS (qa y prod) con Bedrock habilitado | Nube | 1, 4 | Diseño de IaC; si la cuenta del piloto sirve, hay que confirmarlo |
| VPN Site-to-Site y reglas de firewall (1433 solo a las subredes de la tarea) | Redes y Seguridad | 1, 4 | Diseño de la VPC |
| Decisión sobre la cuenta de BD y la identidad del Builder (§5) | Seguridad y DBA | 1, 4, 5 | Escribir el IaC con ambas variantes |
| Decisión sobre Guardrails y sobre tráfico de usuarios por la VPN | Seguridad | 1 | Dejarlos detrás de configuración |
| Login de metadatos (`VIEW DEFINITION`, `VIEW DATABASE STATE`, `SSISDB`, `msdb`) | DBA | 5 | Construir la tarea con un login de prueba |
| Cuenta de BD de la API en el rol `discovery_data_agent_app` | DBA | 4 | — |
| Acceso a diccionarios y documentos desde la tarea del Builder (SMB, SharePoint) | Gerencia de Datos y Redes | 5 | Fuentes en CSV (ya implementado) |
| Certificado y nombre DNS interno para el ALB | Redes | 4 | Certificado de prueba en qa |
| Umbrales, canal de aviso y retención de logs | Seguridad y Operaciones | 6 | Alarmas con valores por defecto de CN-05 |
| Ruta de red para el webhook de Teams (la tarea no tiene salida a internet) | Redes | 4 | Dejar las notificaciones apagadas |
| Aprobación de la prueba de residencia | Seguridad | 7 | Ejecutar las pruebas |

## 5. Bloqueos que las fuentes dejan abiertos

1. **La cuenta con la que la tarea entra a la BD `DiscoveryDataAgent`.** Qa y prod obligan a que `DISCOVERY_DATA_AGENT_DB` no lleve contraseña (`Trusted_Connection=yes` con la gMSA; `api/discovery_data_agent_api/security.py`, [calidad bancaria §4](../calidad-bancaria.md#4-configuración-obligatoria-en-qa-y-prod)). En un contenedor Linux no hay gMSA ni autenticación de Windows (CN-03). CN-03 lista como secreto "el login con el que la API escribe en la BD", por confirmar. Las dos cosas chocan: hay que cambiar la regla de arranque (decisión de Seguridad y cambio de código) o habilitar otro mecanismo sin contraseña; las fuentes no eligen.
2. **La identidad del Builder.** Por defecto entra con la cuenta del proceso (autenticación de Windows); en AWS tiene que usar `metadata_user_env` y `metadata_password_env`, con el login en Secrets Manager (CN-01 punto 3, CN-02).
3. **Confianza TLS hacia el SQL Server.** `TrustServerCertificate` impide arrancar en qa y prod, así que el contenedor debe confiar en la CA que firma el certificado del SQL Server del banco. Las fuentes no lo tratan.
4. **Logs a la salida estándar** (código pendiente, fase 3).
5. **Certificado del ALB.** CN-01 dice "certificado de ACM" y no explica su origen ni el nombre interno.

## 6. Camino crítico a producción en AWS

1. Informe del piloto con recomendación AWS y decisión de la Gerencia de Datos.
2. Cuenta de AWS y VPN con firewall abierto (lo más lento, fuera del equipo).
3. Decisión de Seguridad sobre la cuenta de BD (§5, punto 1) y cambio de código si hace falta.
4. Logs a salida estándar y construcción de las imágenes con los bloqueos, escaneadas, en ECR.
5. IaC de qa y tarea Web + API funcionando; compuerta en qa igual que on-premise (CN-01 CA6).
6. Builder programado y alarma de fallo.
7. Pruebas de residencia aprobadas por Seguridad.
8. Prod, paralelo y corte (fase 8).

La observabilidad completa (fase 6) y la prueba de residencia (fase 7) entran antes del corte, no después. Las fases de Builder y alarmas se pueden hacer en paralelo con las de la tarea una vez existe el IaC.

## 7. Decisiones abiertas que mueven la ruta

| Decisión | Efecto |
|---|---|
| Si el piloto recomienda AWS, producción on-premise o ampliar el piloto | Sin ella esta ruta no arranca |
| Cuenta de BD y mecanismo de acceso sin contraseña (§5, punto 1) | Cambia código y reglas de arranque |
| Terraform o CDK | Herramienta del IaC |
| Tamaño de la tarea | Coste y latencia |
| Guardrails de Bedrock | Permiso `bedrock:ApplyGuardrail` y trabajo en el gateway |
| ¿La VPN lleva tráfico de usuarios hacia el ALB? | Si no, hay que dar otro camino a los usuarios |
| Mecanismo para detectar el *invocation logging* activado | Control de CN-06 CA3 |
| Cómo lee el Builder carpetas compartidas SMB | Fuentes de conocimiento en AWS |
| Retención del grupo de logs, umbrales y canal de alarmas | Operación |
| Configuración del despliegue de ECS para que nunca haya dos tareas | Integridad de sesiones |
| Hacia dónde crece: alta disponibilidad con sesiones compartidas o sigue una tarea | Fase 9 |

## 8. Qué queda fuera y por qué

| Fuera | Motivo |
|---|---|
| AgentCore (Runtime, Gateway, Code Interpreter) | El DiscoverFlow y el MCP ya viven en la API; el sandbox es de la fase 1b (decisiones 11 y 16) |
| OpenSearch Serverless, S3, Lambda indexador | Búsqueda léxica en memoria; el catálogo va a la BD (decisiones 9 y 10) |
| Cognito, WAF, Transit Gateway, Step Functions | El login es el SQL; el ALB es interno; una sola VPC; el Builder es un `RunTask` |
| BD de auditoría separada o copia en AWS | La auditoría es el esquema `audit` de la BD on-premise (decisión 10) |
| Migrar la BD `DiscoveryDataAgent` a AWS | Contradice la residencia: AWS no persiste nada |
| Fase 1b en AWS (consulta de datos, sandbox F20, capa semántica F21) | Sus controles se definen con la fase 1b (decisión 16, CN-06) |
| Más de una tarea | Fase 9; no se hace sin rediseñar el estado |
| Embeddings, juez, NIM de respaldo | Retirados en la fase 1a (decisiones 9 y 13) |

## Deuda técnica que condiciona esta ruta
El registro completo está en [deuda técnica](deuda-tecnica.md).

| Fase | Deudas | Efecto en AWS |
|---|---|---|
| 1 · Prerrequisitos | DT-46 (estado en memoria) | Obliga a una sola tarea y a un despliegue que nunca deje dos a la vez |
| 3 · Imágenes | DT-45, DT-47 y DT-50 | La imagen no se construye ni se analiza en la CI, lleva paquetes del sistema sin fijar y arrastra fixtures de prueba |
| 4 · Tarea web + API | DT-02 | El proxy de la web ya reenvía la dirección del cliente, pero solo con `TRUST_FORWARDED_FOR=1` (web) y `DISCOVERY_DATA_AGENT_TRUST_PROXY=1` (API). Detrás del ALB hay que activarlas y probarlas; el origen público va en `DISCOVERY_DATA_AGENT_CORS_ORIGINS` |
| 6 · Observabilidad | DT-58 y DT-37 | Los avisos de la API no llegan al log y no hay alerta si falla la auditoría: CloudWatch no los vería |
| 9 · Más de una tarea | DT-46 y DT-21 | Sesiones, topes y corte por fallos tendrían que compartirse entre tareas |

## Nota: contradicciones y vacíos entre las fuentes

- **Cuenta de BD sin contraseña frente al contenedor.** Explicado en §5, punto 1: la regla de arranque de qa y prod y CN-03 no pueden cumplirse a la vez.
- **Recarga tras el Builder.** CN-02 §Memoria dice "mecanismo por confirmar"; CN-01 §Dependencias, punto 3, dice que ya está hecho (la API comprueba la versión cada 15 s). Vale lo segundo, que coincide con el plan de desarrollo; CN-02 quedó sin actualizar.
- **Tamaño de la tarea.** CN-01 lo deja "por confirmar" y da como referencia 4 vCPU y 16 GB, que son los del servidor on-premise para 3–20 usuarios; CN-01 dimensiona para 10–15. No es un conflicto, pero la referencia no está medida para Fargate.
- **Webhook de Teams.** CN-04 reconoce que la tarea no tiene salida a internet y no da la ruta; OP-04 lo envía por el proxy corporativo, que en AWS no existe.
- **Entornos.** CN-01 llama "dev" a `docker compose` local u on-premise; OP-07 define el entorno dev como estación del desarrollador sin IIS. No es un conflicto, pero AWS no tiene entorno dev propio.
- **Vacíos.** No hay IaC, ni nombre DNS, ni origen del certificado del ALB, ni tamaño de la tarea, ni retención de logs, ni umbrales de alarma, ni mecanismo para la comprobación del *invocation logging*. Las fuentes tampoco describen la migración on-premise a AWS ni la convivencia: la fase 8 es una deducción.
