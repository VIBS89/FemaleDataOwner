# Arquitectura de ConverData

Actualizado el 2026-11-17. Este documento explica el enfoque de la solución y su arquitectura siguiendo el modelo C4:
primero el sistema en su entorno, después los procesos que se despliegan y por último los componentes de cada proceso.
El detalle interno de cada componente está en la [wiki](../wiki/README.md).

Los diagramas son páginas HTML interactivas. Ábrelos en el navegador desde el repositorio: cada caja tiene una
descripción al pasar el cursor y las tarjetas de abajo resumen lo importante.

| Nivel | Qué muestra | Diagrama |
|---|---|---|
| C4 1 · Contexto | Quién usa ConverData y con qué sistemas habla | [c4-contexto.html](c4-contexto.html) |
| C4 2 · Contenedores | Los procesos y almacenes que se despliegan on-premise | [onpremise-architecture.html](onpremise-architecture.html) |
| C4 2 · Contenedores | Los mismos procesos en AWS, después del piloto | [cloud-native-architecture.html](cloud-native-architecture.html) |
| C4 3 · Componentes | Las piezas internas de ConverData-API | [c4-componentes-api.html](c4-componentes-api.html) |
| Detalle | Cómo se responde una pregunta, paso a paso | [flujo-descubrimiento.html](flujo-descubrimiento.html) |
| Detalle | Tablas de la BD `ConverData` | [modelo-datos-converdata.html](modelo-datos-converdata.html) |
| Detalle | Cómo se heredan los permisos de SQL Server | [permisos-heredados.html](permisos-heredados.html) |
| Detalle | Controles de una petición y compuerta de calidad | [controles-calidad-bancaria.html](controles-calidad-bancaria.html) |

**Para desarrolladores.** Por dónde empezar a leer el código y cómo se mueven las piezas que tocás a diario.

| Qué muestra | Diagrama |
|---|---|
| Paquetes del repositorio agrupados por capa y por dónde empezar a leer | [mapa-codigo.html](mapa-codigo.html) |
| Cómo corre todo en tu máquina: `docker compose`, modo demo, modelo y pruebas | [entorno-desarrollo.html](entorno-desarrollo.html) |
| Cómo se construye el catálogo: `extract → enrich → relate → write` | [flujo-construccion-catalogo.html](flujo-construccion-catalogo.html) |
| Login, sesión cifrada en memoria, petición autenticada y cierre | [secuencia-login-sesion.html](secuencia-login-sesion.html) |
| El puerto del gateway de LLM, sus proveedores y quién lo usa | [gateway-llm.html](gateway-llm.html) |
| Estados de una duda escalada y de una confirmación «Es este» | [ciclo-curacion.html](ciclo-curacion.html) |

## 1. Enfoque

### 1.1 El problema
En el banco, encontrar dónde vive un dato lleva días. Quien prepara un reporte normativo, un tablero o un estudio
pregunta a varios equipos qué tabla usar, en qué servidor está y qué significa cada columna. El conocimiento existe,
pero está repartido entre personas, diccionarios y manuales.

### 1.2 Lo que hace ConverData
Una persona pregunta en español, por ejemplo "¿de dónde saco los días de atraso de cada crédito?". ConverData responde
con las tablas y columnas candidatas: base de datos, ambiente, servidor, descripción con su fuente, reglas de negocio,
responsables, relaciones y un nivel de confianza. Si no encuentra nada fiable lo dice y ofrece escalar la duda al
responsable del dominio. Lo que el responsable contesta queda guardado y mejora las respuestas siguientes.

Esta es la fase 1a, descubrimiento. La fase 1b, que genera y ejecuta consultas sobre los datos, no está construida.

### 1.3 Principios de diseño

| Principio | Qué significa en la práctica |
|---|---|
| Permisos heredados | Cada persona entra con su login de SQL Server. ConverData pregunta a SQL Server qué puede leer ese login y busca solo ahí. Lo que no ve responde igual que lo que no existe |
| Solo metadatos | Se leen estructura y descripciones con consultas fijas a `sys.*`. Nunca valores de datos de clientes |
| Auditoría antes de responder | Cada pregunta y cada cambio se registran antes de entregarse o aplicarse. Si no se puede registrar, no ocurre |
| El grafo manda, no el modelo | El flujo tiene pasos fijos y dos ciclos acotados. El modelo de lenguaje ayuda en pasos concretos y su salida pasa por guardas |
| Funciona sin modelo | Cada paso con modelo tiene una versión determinista. Así se desarrolla, se prueba y se mide sin depender de un proveedor |
| Lo más simple que cumple | Búsqueda léxica en memoria, tablas normales de SQL Server, dos procesos. Cada pieza retirada se retiró con una medición |
| Medir antes de aceptar | Un cambio en la lógica entra solo si la compuerta de calidad no baja |

### 1.4 Decisiones que dan forma a la arquitectura
La lista completa y sus fechas están en [PRD §13](../PRD.md#13-decisiones-y-preguntas-abiertas).

| Decisión | Motivo |
|---|---|
| Búsqueda léxica BM25 en memoria, sin embeddings | En la medición del equipo los embeddings no cambiaron ningún caso y subieron la latencia de 73 ms a 4,6 s |
| BD `ConverData` en tablas normales, SQL Server 2016 o posterior | Sin tipo `VECTOR`, Full-Text ni tablas de grafo: no exige SQL Server 2025. El grafo de relaciones se arma en memoria |
| Web en Next.js y API en FastAPI con LangGraph | El flujo es de pasos fijos con ciclos, que es el modelo de LangGraph. La web reenvía `/api/*` y la API no se publica |
| Builder como comando que corre y termina | Menos piezas que instalar y vigilar que un servicio propio |
| Un solo modelo en el piloto, para intención y orden | Sin embeddings ni juez en la fase 1a |
| Un solo proceso de API | Sesiones, visibilidad e índice viven en memoria. Basta para 10–15 usuarios |
| AWS después del piloto, con lo persistente en el banco | Migrar es cambiar dónde corren los contenedores, no dónde viven los datos |

### 1.5 Qué se ha medido
Sin modelo de lenguaje y con preguntas escritas por el equipo:

- Preguntas del tipo "¿dónde está X?": 98,0 % de acierto en el primer candidato sobre 58 casos y 96,2 % sobre 31, con 0 fugas de permisos y 0 objetos inventados.
- Preguntas de reporte, tablero o estudio: 16 % solo con el catálogo y 60 % al añadir un glosario de prueba. Por eso las fuentes de conocimiento son la palanca principal.
- Respuesta en decenas de milisegundos en modo determinista.

Falta medir con el modelo real y con preguntas de usuarios del banco. Las cifras y cómo reproducirlas están en el
[plan de desarrollo §2](../PLAN-desarrollo.md#2-resultados-medidos).

## 2. C4 nivel 1: contexto
Diagrama: [c4-contexto.html](c4-contexto.html).

**Personas**

| Quién | Qué hace con ConverData |
|---|---|
| Analista, ingeniero de datos o Product Owner | Pregunta dónde está un dato y confirma o rechaza los candidatos |
| Responsable de datos | Responde dudas escaladas, corrige descripciones, mantiene reglas y carga diccionarios de sus dominios |
| Administrador de datos | Registra servidores, lanza la construcción del catálogo, nombra responsables y consulta auditoría y métricas |
| DBA y operaciones | Crea la BD, aplica migraciones, asigna roles y programa el refresco, la purga y los respaldos |

**Sistemas externos**

| Sistema | Relación |
|---|---|
| SQL Server de datos | Fuente de verdad de los permisos y de la estructura. Solo se leen metadatos |
| Amazon Bedrock | Modelo de lenguaje. Único servicio fuera de la red del banco. Pendiente de probar de punta a punta |
| Fuentes de conocimiento | Diccionarios, manuales, glosarios, reglas y paquetes SSIS que el Builder ingiere |
| Cliente MCP | Agentes como Claude Code que usan ConverData como herramienta, con la sesión del usuario |
| Microsoft Teams | Aviso opcional de una duda escalada: solo el dominio y un enlace |

**Límites del sistema.** ConverData no concede permisos, no consulta datos y no guarda valores. Fuera de la red del
banco solo sale el contexto que se envía al modelo: la pregunta y metadatos que el usuario ya puede ver.

## 3. C4 nivel 2: contenedores

### 3.1 On-premise (piloto)
Diagrama: [onpremise-architecture.html](onpremise-architecture.html).

| Contenedor | Tecnología | Responsabilidad | Estado |
|---|---|---|---|
| IIS | Proxy inverso con HttpPlatformHandler | Termina TLS, envía `/` a la web y `/mcp` a la API, y supervisa los dos procesos | Pendiente: scripts de instalación |
| Web | Next.js 15 | Chat, Catálogo, Mis solicitudes, Curación, Métricas y Administración. Reenvía `/api/*` | Construida |
| ConverData-API | FastAPI, LangGraph, pyodbc | REST, servidor MCP y flujo de descubrimiento. Sin estado en disco | Construida |
| Builder | El mismo código, como comando | Lee metadatos, arma el catálogo y lo publica | Construido; falta programarlo |
| BD `ConverData` | SQL Server 2016 o posterior | Catálogo con historial, conocimiento, curación, inventario y auditoría | Construida (migraciones 001 y 002) |
| Programador de tareas | Windows | Refresco nocturno, purga y evaluación de regresión | Pendiente |

Hoy el desarrollo corre con `docker compose` y un modelo local. Los pasos para llegar al piloto están en la
[hoja de ruta on-premise](../wiki/hoja-de-ruta-on-premise.md).

### 3.2 AWS (después del piloto)
Diagrama: [cloud-native-architecture.html](cloud-native-architecture.html).

Las dos imágenes de `docker compose` corren en una tarea de ECS Fargate detrás de un balanceador interno. El Builder se
lanza cada noche como tarea aparte. Bedrock se llama por un VPC endpoint. La BD `ConverData` y las BDs de negocio se
quedan en el banco y se alcanzan por VPN, así que AWS no persiste catálogo, preguntas ni auditoría.

Nada de esto está desplegado y no hay infraestructura como código en el repositorio. Los pasos y los bloqueos conocidos
están en la [hoja de ruta cloud](../wiki/hoja-de-ruta-cloud.md).

### 3.3 Qué cambia entre los dos despliegues

| Aspecto | On-premise | AWS |
|---|---|---|
| Entrada | IIS con certificado de la PKI corporativa | ALB interno con certificado de ACM |
| Procesos | Dos procesos supervisados por IIS | Dos contenedores en una tarea de Fargate |
| Refresco del catálogo | Programador de tareas de Windows | EventBridge Scheduler con RunTask |
| Secretos del servicio | Cuenta del proceso (gMSA) y DPAPI | Secrets Manager |
| Modelo | Bedrock por el proxy corporativo | Bedrock por VPC endpoint |
| Logs | Archivos JSON y Visor de eventos | CloudWatch Logs |
| BD `ConverData`, login de los usuarios, SessionVault | Igual | Igual |

## 4. C4 nivel 3: componentes

### 4.1 ConverData-API
Diagrama: [c4-componentes-api.html](c4-componentes-api.html). Detalle: [API](../wiki/componentes/api.md).

El código sigue cuatro capas y las dependencias apuntan hacia adentro: integración → aplicación → dominio ←
infraestructura. La regla está en [capas-backend.md](capas-backend.md) y la comprueba `tests/test_architecture.py` para
el núcleo (`src/converdata/`).

| Grupo | Componentes | Qué hace |
|---|---|---|
| Borde HTTP | `SecurityMiddleware`, rutas REST, servidor MCP | Filtra la petición, identifica la sesión y comprueba el rol |
| Estado del proceso | `SessionVault`, `AgentRuntime`, `CurationDesk` | Sesiones cifradas en memoria, catálogo cargado, visibilidad de cada usuario, curación |
| Aplicación | Herramientas de descubrimiento, `DiscoverFlow`, refresco del catálogo | Casos de uso. El chat y el MCP terminan en el mismo `DiscoverFlow`; el MCP entra por las herramientas y las rutas REST llaman al flujo directamente |
| Dominio | Catálogo e índice, motor de descubrimiento, reglas de curación | Lógica determinista, sin entrada ni salida |
| Infraestructura | Gateway de LLM, conector SQL, repositorios y auditoría | Adaptadores hacia Bedrock, SQL Server y la BD `ConverData` |

Dos identidades distintas cruzan la API y nunca se mezclan. El login del usuario sirve solo para preguntar a SQL Server
qué puede leer. La cuenta de servicio sirve solo para la BD `ConverData`. El modelo no recibe ninguna de las dos.

### 4.2 Web
Detalle: [Web](../wiki/componentes/web.md).

| Componente | Qué hace |
|---|---|
| Rutas `(app)` | Preguntar, Catálogo, Mis solicitudes, Curación, Métricas y Administración. Cada una se muestra según el rol |
| Proxy `/api/[...path]` | Reenvía a la API con la cookie de sesión. La API no se publica directamente |
| `lib/api.ts` y `lib/types.ts` | Contrato con la API |
| `session-provider` | Sesión y roles en el cliente. No guarda credenciales |

### 4.3 Builder
Detalle: [Builder y catálogo](../wiki/componentes/builder-catalogo.md).

Es un flujo de cuatro pasos: leer metadatos, enriquecer, relacionar entidades entre BDs y escribir. Parte del catálogo
publicado y nunca pisa lo que editaron las personas. Lo lanzan por igual `converdata catalog build --db` y la pantalla
de Administración.

### 4.4 BD `ConverData`
Diagrama: [modelo-datos-converdata.html](modelo-datos-converdata.html). Detalle: [BD ConverData](../wiki/componentes/bd-converdata.md).

| Esquema | Contenido |
|---|---|
| `catalog` | Objetos, columnas y llaves con historial y autor; inventario de servidores |
| `knowledge` | Diccionarios, reglas, linaje, entidades y confirmaciones como plantilla sin literales |
| `curation` | Responsables, dudas escaladas y votos |
| `golden` | Texto original de una confirmación, solo si no traía literales |
| `audit` | Preguntas, pasos, candidatos, votos y eventos. Solo inserción para la API |

## 5. Detalle interno
Cada página de la wiki baja hasta archivos y funciones.

| Tema | Diagrama | Página |
|---|---|---|
| Cómo se responde una pregunta | [flujo-descubrimiento.html](flujo-descubrimiento.html) | [Descubrimiento](../wiki/componentes/descubrimiento.md) |
| Rutas, sesiones y curación | [c4-componentes-api.html](c4-componentes-api.html) | [API](../wiki/componentes/api.md) |
| Permisos, sesiones, auditoría y literales | [permisos-heredados.html](permisos-heredados.html), [controles-calidad-bancaria.html](controles-calidad-bancaria.html) | [Seguridad y auditoría](../wiki/componentes/seguridad-auditoria.md) |
| Modelos de lenguaje | [gateway-llm.html](gateway-llm.html) | [Gateway de LLM](../wiki/componentes/llm.md) |
| Construcción del catálogo | [flujo-construccion-catalogo.html](flujo-construccion-catalogo.html) | [Builder y catálogo](../wiki/componentes/builder-catalogo.md) |
| Sesión y login | [secuencia-login-sesion.html](secuencia-login-sesion.html) | [API](../wiki/componentes/api.md) |
| Curación y confirmaciones | [ciclo-curacion.html](ciclo-curacion.html) | [API](../wiki/componentes/api.md) |
| Tablas, roles y migraciones | [modelo-datos-converdata.html](modelo-datos-converdata.html) | [BD ConverData](../wiki/componentes/bd-converdata.md) |
| Frontend | — | [Web](../wiki/componentes/web.md) |
| Evaluación, compuerta y CI | [controles-calidad-bancaria.html](controles-calidad-bancaria.html) | [Evaluación y calidad](../wiki/componentes/evaluacion-calidad.md) |

### 5.1 El camino de una pregunta, en corto
1. La web envía la pregunta. La identidad sale del token de sesión.
2. La API comprueba el ritmo y el tope de tokens, y lee de SQL Server qué objetos ve ese login.
3. `intent` decide qué se pide. `retrieve` busca en el índice, solo entre lo visible. `grade` reformula una vez si lo encontrado es pobre.
4. `rerank` ordena. `expand` añade ubicaciones, reglas, responsables y relaciones. `review` corrige una vez si hace falta.
5. `respond` redacta. `finalize` escribe la auditoría, y solo entonces se entrega la respuesta.

## 6. Aspectos transversales

| Aspecto | Cómo se resuelve | Dónde leer más |
|---|---|---|
| Permisos | Filtro de visibilidad antes de ordenar y otra vez al expandir | [permisos-heredados.html](permisos-heredados.html) |
| Credenciales | Cifradas, solo en memoria, con clave que se genera al arrancar | [Seguridad y auditoría](../wiki/componentes/seguridad-auditoria.md) |
| Auditoría | Tablas de solo inserción en SQL Server; fail-closed | [OP-05](../specs/on-premise/OP-05-auditoria-observabilidad.md) |
| Residencia de datos | Solo sale el contexto enviado al modelo. Las confirmaciones se guardan sin literales | [OP-06](../specs/on-premise/OP-06-residencia-datos.md) |
| Calidad | `converdata eval gate`: siete suites en dos catálogos, en cada push | [calidad-bancaria.md](../calidad-bancaria.md) |
| Cadena de suministro | Dependencias con hash, imágenes por digest, análisis y SBOM en la CI | [requirements/README.md](../../requirements/README.md) |
| Observabilidad | Logs JSON con lista blanca de campos y contadores, sin texto de preguntas | [Seguridad y auditoría](../wiki/componentes/seguridad-auditoria.md) |

## 7. Qué falta
La arquitectura descrita está construida salvo lo que se marca como pendiente. El detalle está en tres páginas:

- [Deuda técnica](../wiki/deuda-tecnica.md): 66 deudas abiertas comprobadas contra el código, 8 de gravedad alta. El 2026-11-17 se cerraron las del borde entre la web y la API (el proxy reenvía `Origin`, la web envía cabeceras de seguridad y solo expone las rutas que usa) y la de la lectura de permisos por base de datos. Lo más urgente ahora es SQL Server en la CI (DT-39), la fecha de la auditoría (DT-04) y la instalación en Windows Server (DT-44). Queda mitigada la dirección del cliente tras el proxy (DT-02): falta activar `TRUST_FORWARDED_FOR` y `CONVERDATA_TRUST_PROXY` detrás de IIS.
- [Brechas funcionales](../wiki/brechas-funcionales.md): lo que prometen el PRD y las specs y aún no existe.
- Hojas de ruta [on-premise](../wiki/hoja-de-ruta-on-premise.md) y [cloud](../wiki/hoja-de-ruta-cloud.md): en qué orden se cierra.

## 8. Mantener los diagramas
Cada diagrama tiene una fuente `*.archify.json` junto a su HTML. Se edita la fuente y se regenera con el generador
incluido en `tools/archify` ([F13](../specs/comun/F13-architecture-docs.md)):

```bash
node tools/archify/bin/archify.mjs finalize <tipo> docs/architecture/<nombre>.archify.json docs/architecture/<nombre>.html --quality showcase --json
```

| Diagrama | Tipo |
|---|---|
| `c4-contexto`, `c4-componentes-api`, `onpremise-architecture`, `cloud-native-architecture`, `entorno-desarrollo` | `architecture` |
| `flujo-descubrimiento`, `controles-calidad-bancaria`, `flujo-construccion-catalogo` | `workflow` |
| `permisos-heredados`, `secuencia-login-sesion` | `sequence` |
| `modelo-datos-converdata` | `erd` |
| `mapa-codigo` | `tree` |
| `gateway-llm` | `class` |
| `ciclo-curacion` | `lifecycle` |

El generador deja un archivo `*.browser-check.json` junto al HTML. No se versiona: bórralo antes de regenerar.
Un cambio que mueva una pieza de proceso, añada una tabla o cambie un control actualiza su diagrama en el mismo cambio.
