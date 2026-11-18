# Wiki de ConverData

Actualizado el 2026-11-17. Documentación interna para el equipo que desarrolla y opera ConverData. Va de lo general a
lo particular: primero el enfoque y la arquitectura, después cada componente por dentro, y al final lo que falta.

ConverData responde en lenguaje natural dónde vive un dato del banco, qué significa y cuánta confianza merece la
respuesta. Lee solo metadatos de SQL Server, y cada persona descubre únicamente lo que su login ya puede leer.

## Por dónde empezar

| Si eres | Lee en este orden |
|---|---|
| Nuevo en el equipo | [Arquitectura](../architecture/README.md) → [Descubrimiento](componentes/descubrimiento.md) → [manual de desarrollo](../manual-desarrollo.md) §4 |
| Quien va a tocar la API o la web | [API](componentes/api.md) → [Web](componentes/web.md) → [Seguridad y auditoría](componentes/seguridad-auditoria.md) |
| Quien va a instalar u operar | [Hoja de ruta on-premise](hoja-de-ruta-on-premise.md) → [BD ConverData](componentes/bd-converdata.md) → [OP-07](../specs/on-premise/OP-07-instalacion-operacion.md) |
| Quien planifica | [Brechas funcionales](brechas-funcionales.md) → [Deuda técnica](deuda-tecnica.md) → hojas de ruta |
| Seguridad de la Información | [Seguridad y auditoría](componentes/seguridad-auditoria.md) → [calidad bancaria](../calidad-bancaria.md) → [permisos heredados](../architecture/permisos-heredados.html) |

## Arquitectura
[Arquitectura de ConverData](../architecture/README.md) explica el enfoque y recorre el modelo C4.

| Nivel | Diagrama |
|---|---|
| C4 1 · Contexto | [c4-contexto.html](../architecture/c4-contexto.html) |
| C4 2 · Contenedores on-premise | [onpremise-architecture.html](../architecture/onpremise-architecture.html) |
| C4 2 · Contenedores en AWS | [cloud-native-architecture.html](../architecture/cloud-native-architecture.html) |
| C4 3 · Componentes de la API | [c4-componentes-api.html](../architecture/c4-componentes-api.html) |
| Detalle · Flujo de una pregunta | [flujo-descubrimiento.html](../architecture/flujo-descubrimiento.html) |
| Detalle · Modelo de datos | [modelo-datos-converdata.html](../architecture/modelo-datos-converdata.html) |
| Detalle · Permisos heredados | [permisos-heredados.html](../architecture/permisos-heredados.html) |
| Detalle · Controles y compuerta | [controles-calidad-bancaria.html](../architecture/controles-calidad-bancaria.html) |

## Componentes por dentro

| Página | Qué cubre |
|---|---|
| [Descubrimiento](componentes/descubrimiento.md) | El flujo que responde una pregunta: pasos, confianza, índice y guardas |
| [API](componentes/api.md) | Rutas, sesiones, visibilidad, curación y variables de entorno |
| [Seguridad y auditoría](componentes/seguridad-auditoria.md) | Cada control, qué protege y qué prueba lo cubre |
| [Gateway de LLM](componentes/llm.md) | Proveedores, roles de modelo, respaldo y qué se envía al modelo |
| [Builder y catálogo](componentes/builder-catalogo.md) | Lectura de metadatos, relaciones entre BDs y publicación |
| [BD ConverData](componentes/bd-converdata.md) | Esquemas, tablas, roles, purga y migraciones |
| [Web](componentes/web.md) | Pantallas, proxy hacia la API y contrato |
| [Evaluación y calidad](componentes/evaluacion-calidad.md) | Sets de evaluación, compuerta, CI y cadena de suministro |

## Qué falta

| Página | Qué responde |
|---|---|
| [Deuda técnica](deuda-tecnica.md) | Qué hay que arreglar en lo construido, con evidencia, gravedad y esfuerzo |
| [Brechas funcionales](brechas-funcionales.md) | Qué prometen el PRD y las specs y qué existe de verdad |
| [Hoja de ruta on-premise](hoja-de-ruta-on-premise.md) | Fases hasta el piloto y después |
| [Hoja de ruta cloud](hoja-de-ruta-cloud.md) | Fases hasta un despliegue en AWS |

## Otros documentos

| Documento | Para qué |
|---|---|
| [PRD](../PRD.md) | Producto, requisitos, fases y decisiones (§13) |
| [Plan de desarrollo](../PLAN-desarrollo.md) | Estado, resultados medidos y cómo retomar |
| [Backlog on-premise](../backlog/on-premise.md) | Historias de usuario y su estado |
| [Reparto entre 5 desarrolladores](../backlog/reparto-5-devs.md) | Quién puede empezar qué |
| [Calidad bancaria](../calidad-bancaria.md) | Controles de seguridad y compuerta de calidad |
| [Manual de desarrollo](../manual-desarrollo.md) | Resumen de componentes y mejoras. Es el que la aplicación muestra a los administradores de datos |
| Specs [comunes](../specs/comun/), [on-premise](../specs/on-premise/) y [cloud](../specs/cloud-native/) | Cómo debe comportarse cada pieza |

## Cómo mantener esta wiki
- La wiki vive en el repositorio, en `docs/wiki/`. Se cambia en el mismo cambio que el código que describe.
- Si una página contradice al código, manda el código: corrige la página.
- Cada afirmación sobre el código cita la ruta del archivo. Lo que no se pudo comprobar se marca "sin verificar".
- Sin credenciales, nombres de servidores reales ni nombres de personas.
- Los diagramas se regeneran como indica [Arquitectura §8](../architecture/README.md#8-mantener-los-diagramas).
