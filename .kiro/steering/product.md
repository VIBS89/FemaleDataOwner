---
inclusion: always
---

# Producto: Discovery Data Agent

Asistente de IA para la **Gerencia de Datos de Banco Atlántida El Salvador**. Responde en lenguaje natural dónde está un dato
(campo, tabla, base, ambiente, servidor), qué significa, qué reglas de negocio aplican, con qué se relaciona, quién es su responsable y
cuánta confianza merece la recomendación. Convierte la respuesta de cada experto en conocimiento reutilizable por toda la organización.

Fuente completa: [docs/PRD.md](../../docs/PRD.md).

## Usuarios
Ingeniero de datos, analista o desarrollador BI, científico de datos, Product Owner, responsable de dominio (steward), nuevo
colaborador y administrador de datos.

## Flujos
- **DiscoverFlow** (caso principal): pregunta en español → lista priorizada de candidatos con evidencia y confianza.
- **AskFlow** (fase 1b): primer corte de cifras agregadas, apagado por defecto.

## Principios que ningún cambio puede romper
1. Nadie ve más de lo que ya puede ver: cada usuario descubre solo lo que su login SQL puede leer, metadatos incluidos.
2. Los datos de clientes no salen del banco: el catálogo guarda metadatos, nunca valores.
3. Nunca se inventan objetos: todo lo mencionado existe en el catálogo.
4. Solo lectura: el agente no escribe ni modifica datos.
5. Auditoría fail-closed: si no se puede auditar, no se responde.
6. Cada recomendación muestra su evidencia y su confianza; el éxito se mide contra una línea base.

## Metas (se validan en el piloto)
−50 % tiempo para localizar fuentes · −30 % consultas a expertos · −20 a −40 % tiempo de análisis · −20 % reprocesos.

## Idioma
Español en la interfaz, la documentación, los commits y los nombres de pruebas.
