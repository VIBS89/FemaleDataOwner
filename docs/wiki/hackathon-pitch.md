# Hackathon pitch

Presentación de Discovery Data Agent para el hackathon AWS Builders League · Women Agentic 2026 (formato Shark
Tank: 5 minutos de pitch y 2 de preguntas). Las diapositivas principales van primero y los anexos, para la ronda
de preguntas, al final. Cada una lleva sus notas del orador: tiempo, quién habla y qué decir.

Esta página se genera con `scripts/build_pitch.py` desde [docs/pitch](../pitch/README.md); no se edita a mano.
La presentación para proyectar es `docs/pitch/presentacion.html`. Los marcadores `[N]`, `[x h]` y `[__]` se
completan con datos reales del equipo antes del pitch.

| # | Diapositiva |
|---|---|
| 1 | [Discovery Data Agent](#1-discovery-data-agent) |
| 2 | [Hoy, un dato depende de quién lo sabe](#2-hoy-un-dato-depende-de-quien-lo-sabe) |
| 3 | [El agente decide su camino, no sigue un guion](#3-el-agente-decide-su-camino-no-sigue-un-guion) |
| 4 | [10 servicios de AWS, desplegados con Terraform](#4-10-servicios-de-aws-desplegados-con-terraform) |
| 5 | [Míralo decidir](#5-miralo-decidir) |
| 6 | [Medido hoy, comprometido para el piloto](#6-medido-hoy-comprometido-para-el-piloto) |
| 7 | [Que ninguna pregunta sobre datos dependa de una sola persona](#7-que-ninguna-pregunta-sobre-datos-dependa-de-una-sola-persona) |
| 8 | [Pregunta en español, respuesta con evidencia](#8-pregunta-en-espanol-respuesta-con-evidencia) |
| 9 | [One question replaces a chain of messages to experts](#9-one-question-replaces-a-chain-of-messages-to-experts) |
| 10 | [10 herramientas por MCP y 5 reglas que nunca rompe](#10-10-herramientas-por-mcp-y-5-reglas-que-nunca-rompe) |
| 11 | [Cómo sabemos que el problema es real](#11-como-sabemos-que-el-problema-es-real) |

## 1. Discovery Data Agent

*AWS Builders League · Women Agentic 2026*

- Hackathon · Shark Tank
- Pregunta en tu idioma dónde está un dato. El agente lo encuentra, te dice cuánto confiar y aprende de tus expertos.
- Para la Gerencia de Datos de Banco Atlántida El Salvador
- Amazon Bedrock · ECS Fargate · MCP

**Notas del orador**

> RELOJ 0:00–0:10 (10 s, ~25 palabras) · [Integrante 1]. Hola, somos [nombre del equipo] y les presentamos Discovery Data Agent: un agente que encuentra cualquier dato del banco con solo preguntar. Pasar al siguiente slide sin pausa.
>
> PLAN DE TIEMPO TOTAL (5:00, objetivo terminar en 4:50 para no cortarnos): portada 0:00–0:10 · problema 0:10–0:50 · solución agéntica 0:50–1:30 · arquitectura 1:30–1:50 · DEMO 1:50–3:50 · impacto 3:50–4:25 · cierre 4:25–4:50 · 10 s de colchón. Quedan 2 min de preguntas: anexos al final del deck.

## 2. Hoy, un dato depende de quién lo sabe

*1 · Problema y cliente*

- Un martes cualquiera, una analista de BI pregunta:
- “¿Dónde está el identificador único del cliente de onboarding digital?”
- Cliente
- Gerencia de Datos de Banco Atlántida El Salvador y sus siete perfiles: de ingenieros de datos a nuevos colaboradores.
- **Dependencia de expertos**
- Cuellos de botella cuando la persona que sabe no está.
- **Búsquedas duplicadas**
- Cada equipo investiga de nuevo lo que otro ya encontró.
- **Reprocesos**
- Una fuente equivocada se descubre tarde, en el reporte.
- **Conocimiento que se va**
- Cuando alguien cambia de rol, lo que sabía se va.
- **[x h]**
- por semana dedica cada analista a buscar datos, según [N] entrevistas con la Gerencia de Datos. Lo planteó el propio cliente y hoy nadie lo mide.

**Notas del orador**

> RELOJ 0:10–0:50 (40 s, ~100 palabras) · [Integrante 1]. Una analista de BI necesita un campo para un reporte y no sabe en cuál de las bases está. La respuesta vive en la cabeza de dos o tres expertos: pregunta, espera y a veces elige la fuente equivocada. Nuestro cliente es la Gerencia de Datos de Banco Atlántida El Salvador, y fue ella quien nos planteó este problema. En [N] entrevistas, cada analista dedica [x h] por semana a buscar datos, y hoy nadie lo mide. El resultado: esperas, búsquedas duplicadas, reprocesos y conocimiento que se va cuando alguien cambia de rol.
>
> ANTES DEL PITCH: completar [N] y [x h] con la cifra real de las entrevistas. Si no hay entrevistas, decir: “nadie lo mide hoy; nuestro agente mide la línea base desde el día uno”.

## 3. El agente decide su camino, no sigue un guion

*2 · Solución agéntica*

- 1
- Entiende la intención
- 2
- Busca en catálogo y grafo
- 3
- Califica: ¿cubre la pregunta?
- 4
- Ordena y expande relaciones
- 5
- Revisa: ¿existe y tiene permiso?
- 6
- Responde con evidencia
- Los pasos 3 y 5 pueden devolver el flujo atrás (ciclos acotados). Cuando no encuentra, decide:
- **Cubre poco**
- Reformula la pregunta con el LLM y vuelve a buscar.
- **Confianza baja**
- No inventa: lo dice y escala al responsable del dato.
- **Varias áreas**
- Responde y ofrece aclarar si el dato existe en varias áreas.
- **Piden modificar**
- Rechaza la orden: el agente es de solo lectura.
- Cinco reglas que nunca rompe
- Permisos heredados
- Datos no salen del banco
- Nunca inventa objetos
- Solo lectura
- Todo auditado

**Notas del orador**

> RELOJ 0:50–1:30 (40 s, ~100 palabras) · [Integrante 2]. La persona pregunta en español dónde está un dato y el agente responde con el campo, la tabla, la base, la regla de negocio, el responsable y cuánto confiar. No es un buscador: decide su camino. Califica si lo encontrado cubre la pregunta y, si no, reformula y vuelve a buscar; si la confianza es baja, no inventa y escala al experto; si piden modificar datos, se niega. Y sigue cinco reglas que nunca rompe: permisos heredados, datos que no salen del banco, nada inventado, solo lectura y todo auditado. Todo sin intervención humana.
>
> PARA PREGUNTAS: LangGraph orquesta el flujo; Amazon Bedrock reformula y redacta; el orden de resultados es determinista y auditable. Detalle de herramientas MCP en el anexo.

## 4. 10 servicios de AWS, desplegados con Terraform

*Arquitectura en AWS*

- Usuarios del banco
- Chat web
- Otros agentes
- Kiro, Claude Code · 10 herramientas MCP
- AWS · us-east-1 · entorno demo
- ALB
- Solo IP del equipo · /mcp
- ECS Fargate Spot
- Web Next.js · API FastAPI + LangGraph · SQL Server Express
- Amazon Bedrock
- Claude Sonnet 5.5, rol de la tarea
- Agente de esquemas
- Descubrir esquemas
- Catálogo en SQL Server
- Extrae metadatos y describe con IA en Bedrock
- VPC
- EventBridge
- ECR
- Secrets Manager
- KMS
- CloudWatch
- SNS
- Datos de prueba
- BancosSQL 100 % ficticio, en la tarea
- En producción
- VPN al SQL Server del banco: solo metadatos

**Notas del orador**

> RELOJ 1:30–1:50 (20 s, ~50 palabras) · [Integrante 3]. Todo está desplegado en AWS con Terraform: web, API y un SQL Server con datos ficticios en Fargate, y Claude Sonnet en Bedrock, que también describe el catálogo que arma el agente de esquemas. Son diez servicios. Otros agentes, como Kiro, usan las diez herramientas MCP. En producción, la misma imagen se conecta por VPN al SQL Server del banco. Vamos a la demo.
>
> PARA PREGUNTAS: los diez servicios son VPC, ALB, ECS Fargate, Bedrock, EventBridge, ECR, Secrets Manager, KMS, CloudWatch y SNS. Diferencias del demo con producción: tarea con IP pública en lugar de subredes privadas con VPC endpoints; ALB por HTTP limitado a la IP del equipo en lugar de interno con HTTPS; SQL Server Express con datos ficticios en lugar del SQL Server del banco por Site-to-Site VPN; el catálogo se arma desde Administración → Descubrir esquemas, mientras que en producción lo refresca cada noche un Builder lanzado por EventBridge Scheduler. En el demo EventBridge avisa si la tarea se detiene. Todo está en el mismo Terraform (deploy/aws).

## 5. Míralo decidir

*3 · Demo en vivo · desplegada en AWS*

- 1
- Encuentra. Pregunta por el identificador del cliente de onboarding: ClientCode al 96 %, con su regla y sus relaciones.
- 2
- Respeta permisos. Abre el catálogo y no ve RRHH: hereda los permisos de SQL Server.
- 3
- No inventa. Puntaje de riesgo crediticio: 44 %. Lo dice y escala al responsable.
- 4
- Aprende. El responsable responde una vez y la misma pregunta sube a 93 %.

**Notas del orador**

> RELOJ 1:50–3:50 (2:00) · [Integrante 4] maneja, [Integrante 5] narra. Es la parte que más pesa: no pasar de 3:50.
> PASO 1 (1:50–2:30, 40 s): analista pregunta por el identificador del cliente de onboarding; mostrar ClientCode al 96 %, la regla BR-ONB-004 y las relaciones. Decir: “el agente califica, ordena y expande relaciones solo”.
> PASO 2 (2:30–3:00, 30 s): abrir el catálogo y mostrar que no aparece RRHH. “Hereda los permisos de SQL Server: nadie ve más de lo que ya puede ver”.
> PASO 3 (3:00–3:25, 25 s): preguntar el puntaje de riesgo crediticio; confianza 44 %. “No inventa: lo dice y escala al responsable”.
> PASO 4 (3:25–3:50, 25 s): el responsable responde una vez; la misma pregunta sube a 93 %. “El agente aprende del experto”.
>
> ANTES DE SUBIR: sesiones de analista y responsable ya iniciadas, preguntas copiadas en un bloc, demo ensayada con cronómetro. Ir directo a los cuatro pasos, sin explorar menús. Solo mostrar lo que está funcionando en vivo (criterio de desempate: “todo lo descrito se demostró”).
> OPCIONAL, solo si ya está probado y cabe sin pasar de 3:50: 10 s mostrando a Kiro o Claude Code consultando el mismo catálogo por MCP.
> PLAN B si falla la conexión: usar los 2 min de gracia; si sigue fallando, ir al anexo “Pregunta en español, respuesta con evidencia” y narrar los cuatro pasos sobre esa pantalla. No se aceptan demos grabadas.

## 6. Medido hoy, comprometido para el piloto

*4 · Impacto*

- Medido en nuestras evaluaciones
- **98 %**
- acierta a la primera en 58 preguntas sobre bases bancarias
- **0**
- fugas de permisos y objetos inventados en todas las corridas
- **1 332**
- pruebas automáticas y compuerta de calidad en cada cambio
- Metas de negocio, contra la línea base que mide el propio agente
- ≈ [__] h por semana liberadas
- **−50 %**
- tiempo para localizar una fuente
- **−30 %**
- consultas a expertos
- **−20 a 40 %**
- tiempo de análisis de requerimientos
- **−20 %**
- reprocesos por fuente equivocada

**Notas del orador**

> RELOJ 3:50–4:25 (35 s, ~85 palabras) · [Integrante 6]. Lo medido: 98 % de acierto a la primera en 58 preguntas, cero fugas de permisos y cero objetos inventados, con 1 332 pruebas automáticas. Lo que comprometemos en el piloto: 50 % menos de tiempo para localizar datos y 30 % menos de consultas a expertos. En horas: con [N] analistas que dedican [x] h por semana a buscar datos, son [N·x/2] h por semana liberadas. Y como el agente mide la línea base desde el primer día, el ahorro se puede demostrar.
>
> ANTES DEL PITCH: reemplazar [__] en el slide por el resultado de N·x/2 (mismos N y x del slide del problema). Si hay costo por hora, agregar “≈ US$ [__] al mes”.
> Distinguir siempre “medido” (evaluaciones) de “meta” (piloto): el jurado valora impacto cuantificado y honesto.

## 7. Que ninguna pregunta sobre datos dependa de una sola persona

*Think Big*

- Hoy
- **Clientes y onboarding**
- Descubrimiento con permisos heredados, desplegado en AWS con 10 servicios.
- Siguiente paso
- **Piloto de 8 semanas**
- 10–15 usuarios de la Gerencia de Datos, medidos contra la línea base.
- Visión
- **Todo el patrimonio**
- Cada base del banco, para personas y para otros agentes por MCP.
- Equipo · un repositorio, seis integrantes, Spec-Driven Development (PRD, 39 specs y backlog)

**Notas del orador**

> RELOJ 4:25–4:50 (25 s, ~65 palabras) · [Integrante 1] cierra. Hoy resolvemos clientes y onboarding. El siguiente paso es un piloto de 8 semanas con 10 a 15 usuarios de la Gerencia de Datos. Y la visión: que todo el patrimonio de datos del banco sea consultable por personas y por agentes. Somos seis, trabajamos en un repositorio con Spec-Driven Development, y cualquiera de nosotras puede explicar cualquier parte. Que ninguna pregunta sobre datos dependa de una sola persona. Gracias.
>
> TERMINAR EN 4:50 como máximo; a los 5:00 el tiempo cuenta en Presentación. Para las preguntas (2 min), todo el equipo al frente: responde quien conozca el tema, sin silencios. Anexos listos: respuesta del agente, herramientas MCP y reglas, evidencia.

## 8. Pregunta en español, respuesta con evidencia

*Anexo · Respuesta del agente*

- El agente razona sobre los metadatos de todas las bases, los diccionarios, el linaje ETL y lo que ya respondieron los expertos.
- Dónde está: campo, tabla, base, ambiente, servidor
- Qué significa y qué regla de negocio aplica
- Con qué se relaciona y quién es el responsable
- Cuánto confiar: confianza calibrada
- Posibles coincidencias
- 1. ClientCode
- Confianza 92 %
- VBank_ING · dbo.Users · Producción · SQL Producción Canales
- Código que identifica a los clientes digitales registrados. Revisada por Banca Digital
- Regla BR-ONB-004: se asigna al completar la verificación de identidad.
- Relacionadas: UserDevices (FK UserId) · DWH.dim.Cliente (ETL ONB_CargaUsuarios)
- Alternativas: LegalClientId 71 % · UserId 64 % · Botones: Es este / No es

**Notas del orador**

> Anexo para preguntas y plan B de la demo. La persona escribe como habla. El agente devuelve una lista priorizada con la ubicación exacta, la descripción y quién la revisó, la regla de negocio, las relaciones y la confianza. Con “Es este” el conocimiento se fortalece para los siguientes usuarios.

## 9. One question replaces a chain of messages to experts

*Annex · Use case*

- A BI analyst, building a report, asks in Spanish:
- “Where is the unique client identifier for digital onboarding?”
- Without the agent
- She messages two or three experts, waits, and may end up on the wrong source.
- 1 · Finds
- **Right field, with context**
- Returns ClientCode with its business rule (BR-ONB-004) and related tables, ranked by confidence.
- 2 · Respects permissions
- **Nobody sees more than allowed**
- HR objects never appear: the agent inherits the person’s SQL Server permissions.
- 3 · Does not invent
- **Low confidence, so it escalates**
- Asked for the credit risk score, confidence is 44 %. It says so and routes the question to the data owner.
- 4 · Learns
- **The expert answers once**
- The same question now returns 93 %, for this analyst and for the next one.
- **1 question**
- gives a sourced answer with a confidence level, and what the owner confirms stays available to everyone.

**Notas del orador**

> Annex for Q&A. Use case in English: a BI analyst asks in Spanish where the digital onboarding client identifier lives. The agent finds ClientCode with its business rule and relations, respects inherited SQL Server permissions, declines to invent an answer when confidence is low (credit risk score, 44 %) and escalates to the owner, and learns from the owner’s answer (same question, 93 %). The four steps mirror the live demo, so it also works as the plan B narration.

## 10. 10 herramientas por MCP y 5 reglas que nunca rompe

*Anexo · Herramientas y reglas*

- discover
- search_catalog
- get_asset
- get_related
- find_alternatives
- list_business_rules
- get_lineage
- where_is
- find_join_path
- estate_overview
- Servidor MCP propio (SDK oficial, Apache-2.0): el chat web y cualquier otro agente, como Kiro o Claude Code, consultan el mismo catálogo con el login de la persona.
- **Nadie ve más de lo que ya puede ver**
- Usa el login SQL de cada persona: hereda sus permisos.
- **Los datos de clientes no salen del banco**
- El catálogo guarda solo metadatos, nunca valores.
- **Nunca inventa objetos**
- Todo lo que menciona existe en el catálogo.
- **Solo lectura**
- No escribe ni modifica datos en ninguna base.
- **Todo queda auditado**
- Si la auditoría falla, la respuesta no sale.

**Notas del orador**

> Anexo para preguntas. El agente expone diez herramientas por MCP, así otros agentes lo usan igual que el chat. Y sigue cinco reglas fijas, probadas en cada cambio por una compuerta de calidad: permisos heredados, residencia de datos, cero objetos inventados, solo lectura y auditoría fail-closed.

## 11. Cómo sabemos que el problema es real

*Anexo · Evidencia*

- **Lo pidió el cliente**
- La Gerencia de Datos lo planteó en su Propuesta 1: el acceso al dato depende del conocimiento tribal y de documentación parcial.
- **El patrimonio es grande**
- [N] servidores SQL Server, [N] bases de datos y [N] tablas entre producción, QA, DWH y desarrollo.
- **Nadie lo mide hoy**
- No existe medición del tiempo de búsqueda. El agente mide la línea base desde el primer día.
- **[x h]**
- por semana dedica cada analista a localizar y entender fuentes de datos, según [N] entrevistas con la Gerencia de Datos.

**Notas del orador**

> Anexo para preguntas. Tres pruebas: lo pidió el propio cliente, el patrimonio es grande y nadie lo mide. Dar la cifra de las entrevistas (completar antes del pitch). Si no hay entrevistas, decir que el producto mide la línea base desde el día uno: tiempo hasta encontrar el dato, escalamientos y brechas.
