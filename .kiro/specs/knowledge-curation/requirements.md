# Requisitos: Curación del conocimiento

Spec detallada: [docs/specs/comun/F24-knowledge-curation.md](../../../docs/specs/comun/F24-knowledge-curation.md).

## Introducción
El agente aprende de los expertos: cada confirmación de un usuario y cada respuesta de un responsable de dominio se convierte en
conocimiento revisado que sirve a toda la organización.

## Requisito 1: Confirmar o rechazar candidatos
**Historia:** Como analista, quiero marcar si un candidato es el correcto, para que la siguiente persona lo encuentre antes.

#### Criterios de aceptación
1. WHEN la persona pulsa "Es este" THEN el sistema SHALL guardar un par plantilla anónima de la pregunta → `asset_key`.
2. The system SHALL quitar de la plantilla todo literal (palabra con dígito o arroba) que no sea vocabulario conocido del banco.
3. IF la plantilla aún parece llevar datos personales THEN el sistema SHALL contar y auditar el voto sin aprenderlo.
4. WHEN un par suma 2 o más confirmaciones netas de usuarios THEN el sistema SHALL usarlo en la confianza con peso 0,7.

## Requisito 2: Escalar al responsable
**Historia:** Como analista, quiero preguntar al responsable cuando el agente no sabe, para no quedarme sin respuesta.

#### Criterios de aceptación
1. WHEN hay brecha de conocimiento o la persona lo pide THEN el sistema SHALL crear una solicitud asignada al responsable del dominio probable.
2. WHEN se crea una solicitud THEN el sistema SHALL notificar solo el dominio y un enlace, nunca el texto de la pregunta.
3. WHEN el responsable responde THEN el sistema SHALL guardar la respuesta como conocimiento revisado y como golden discovery.
4. WHEN otro usuario hace una pregunta equivalente THEN el sistema SHALL devolver el activo respondido con confianza ≥ 0,85.
5. IF el activo correcto está fuera de la visibilidad del usuario THEN el sistema SHALL indicarle que solicite acceso, sin nombrar objetos.

## Requisito 3: Revisión del catálogo
**Historia:** Como responsable de dominio, quiero revisar las descripciones más buscadas, para que el catálogo sea confiable.

#### Criterios de aceptación
1. The system SHALL mostrar la vista Curación solo a `steward` y `data_admin`; a un `consumer` SHALL responderle 403.
2. WHEN se edita una descripción THEN el sistema SHALL versionarla con autor y fecha y auditar el cambio.
3. WHEN corre un refresco del catálogo THEN el sistema SHALL conservar toda edición humana.
4. WHEN un responsable vota "No es" THEN el sistema SHALL retirar el par en la siguiente búsqueda.
