# Requisitos: DiscoverFlow

Spec detallada: [docs/specs/comun/F22-discovery-flow.md](../../../docs/specs/comun/F22-discovery-flow.md).

## Introducción
El DiscoverFlow es el caso de uso principal: una persona describe en lenguaje natural el dato que necesita y recibe en segundos una lista
priorizada de candidatos con ubicación, descripción, reglas, relaciones, responsables y confianza, sin depender de expertos.

## Requisito 1: Descubrir un dato en lenguaje natural
**Historia:** Como analista de datos, quiero preguntar en español dónde está un dato, para no depender del conocimiento tribal.

#### Criterios de aceptación
1. WHEN la persona envía una pregunta de descubrimiento THEN el sistema SHALL devolver una lista priorizada de candidatos con base de datos, esquema, tabla, campo, tipo, ambiente y servidor.
2. WHEN se devuelve un candidato THEN el sistema SHALL mostrar su descripción y la fuente de la descripción (revisada, diccionario, documento o sugerida por IA sin revisar).
3. WHEN se devuelve un candidato THEN el sistema SHALL mostrar reglas de negocio, relaciones a un salto, responsables y alternativas con la misma semántica.
4. WHEN el mismo objeto existe en varios ambientes THEN el sistema SHALL agruparlo en un candidato y avisar si las estructuras difieren.
5. The system SHALL responder con p50 < 5 s y p95 < 10 s.

## Requisito 2: Confianza calibrada y brechas
**Historia:** Como analista, quiero saber cuánto confiar en la respuesta, para no elegir una fuente equivocada.

#### Criterios de aceptación
1. WHEN se calcula un candidato THEN el sistema SHALL asignarle una confianza entre 0 y 1 calibrada contra los sets de evaluación.
2. IF ningún candidato alcanza 0,6 THEN el sistema SHALL marcar `knowledge_gap` y ofrecer "Preguntar al responsable".
3. IF la pregunta trae calificativos que ningún activo conoce THEN el sistema SHALL responder por debajo del umbral de brecha.

## Requisito 3: Autonomía del agente
**Historia:** Como usuario de negocio, quiero que el agente decida cómo encontrar el dato, para escribir como hablo.

#### Criterios de aceptación
1. WHEN la búsqueda cubre poco la pregunta y hay modelo THEN el agente SHALL reformularla con el LLM y medir la reformulación contra el catálogo.
2. WHEN el mismo dato existe en varias áreas THEN el agente SHALL responder y ofrecer hasta cuatro opciones de aclaración.
3. WHEN el mensaje es un seguimiento corto THEN el agente SHALL completarlo con hasta tres turnos del historial.
4. WHEN la persona pide modificar datos THEN el agente SHALL rechazar la orden.
5. WHEN la pregunta es sobre el propio asistente THEN el agente SHALL responder con un texto fijo, listando solo las bases visibles.

## Requisito 4: Seguridad
**Historia:** Como responsable de seguridad, quiero que el agente no amplíe permisos ni invente, para poder usarlo en un banco.

#### Criterios de aceptación
1. The system SHALL filtrar candidatos, relaciones y términos por la visibilidad del login SQL de la persona.
2. The system SHALL rechazar cualquier texto generado que mencione un objeto que no esté en los candidatos, alternativas o relacionados.
3. IF la auditoría de la pregunta falla THEN el sistema SHALL no responder.
4. IF no hay modelo o se agotó el tope de tokens THEN el sistema SHALL responder en modo determinista.

## Requisito 5: Medición
#### Criterios de aceptación
1. The system SHALL medir Hit@1, Hit@3, fugas, objetos inventados y latencia por tipo de pregunta con `eval discovery`.
2. WHEN un cambio baja la línea base THEN la compuerta `eval gate` SHALL fallar en la CI.
