# Features futuros para el banco

> Propuestas del 2026-11-24, **sin priorizar ni comprometer**. Ninguna entra en la fase 1a ni en el piloto. Cada una
> se convierte en spec (`docs/specs/comun/Fxx`) e historias cuando el banco la elija. Lo que ya está especificado se
> cita en lugar de repetirse: la fase 1b (generar y ejecutar SQL: F5–F10), el motor de análisis (F20) y la capa
> semántica (F21).

## Resumen

| # | Feature | Para quién | Valor | Tamaño | Spec |
|---|---|---|---|---|---|
| 1 | Acceso por área de trabajo | Seguridad, gobierno de datos | Cada persona ve solo la información de su área | M | [F26](../specs/comun/F26-acceso-por-area.md) |
| 2 | Pedir acceso desde el chat | Analistas, responsables | Del «no está disponible para tu área» a una solicitud aprobada y auditada | S | Por escribir |
| 3 | Clasificación de datos sensibles | Cumplimiento, Seguridad | Saber qué columnas tienen datos personales o de tarjeta antes de usarlas | M | Por escribir |
| 4 | Linaje para reportes normativos | Regulatorio, auditoría | Del reporte a la SSF a las columnas de origen, con evidencia | L | Amplía F19 (HU-27) |
| 5 | Fuentes certificadas | Gobierno de datos, BI | Distinguir la fuente oficial de un dato de sus copias | S | Amplía F24 |
| 6 | Avisos de cambio a quien usa una tabla | Analistas, BI | Enterarse antes de que un reporte se rompa | M | Amplía F1 y F24 |
| 7 | Integración con el gestor de requerimientos | Analistas, PMO | Adjuntar las fuentes elegidas a la historia y medir F25 sin encuestas | S | Amplía F25 |
| 8 | Asistente en Microsoft Teams | Todo el banco | Preguntar donde ya se trabaja, con los mismos permisos | M | Amplía F12 |
| 9 | Inicio de sesión corporativo (Entra ID / AD) | Seguridad, usuarios | Un solo inicio de sesión; base de las áreas por grupo | M | Amplía F14 |
| 10 | Informe de uso para auditoría | Auditoría interna, Cumplimiento | Quién buscó qué datos sensibles y cuándo | S | Amplía F11 |

Tamaño orientativo para una persona: S ≈ 1 semana, M ≈ 2–3 semanas, L ≈ 4–6 semanas.

## 1. Acceso por área de trabajo
Spec completa en [F26](../specs/comun/F26-acceso-por-area.md). Lo que ve cada persona es la intersección entre los
permisos SQL de su login y los activos de sus áreas, y las áreas también habilitan documentos de conocimiento y
capacidades (cifras, MCP). Corrige además que hoy el filtro de grupos de los documentos no tiene efecto.

## 2. Pedir acceso desde el chat
Cuando F26 responde «no está disponible para tu área», el usuario pulsa **Pedir acceso** y explica para qué lo
necesita. La solicitud llega al responsable del área, en la bandeja de Solicitudes que ya existe para las dudas
escaladas (F24). Al aprobarla se añade la persona al área, con fecha de vencimiento opcional. Todo queda auditado.
Reutiliza `curation.request` y el aviso por webhook.

## 3. Clasificación de datos sensibles
El Builder ya lee las etiquetas de sensibilidad de SQL Server (`sys.sensitivity_classifications`, F18). Se trata de:
- proponer la clasificación por nombre y tipo de columna (DUI, NIT, PAN, teléfono, correo, saldo) sin leer valores;
- que el responsable la confirme;
- mostrarla en la ficha y en el chat («contiene datos personales: requiere justificación»).

Cumplimiento obtiene un inventario de dónde viven los datos personales y de tarjeta, útil para la ley de protección de
datos y para PCI DSS. Se combina con F26: un área puede no tener acceso a columnas sensibles aunque vea la tabla.

## 4. Linaje para reportes normativos
Hoy hay linaje de vistas y claves foráneas. Falta el de los paquetes SSIS, los jobs del Agente y los `INSERT…SELECT`
de los procedimientos (HU-27). Con eso, una pregunta como «¿de dónde sale la cartera vencida del reporte de la SSF?»
devuelve la cadena completa hasta las tablas de origen, con la evidencia de cada salto. Es lo que más pide una
auditoría regulatoria y lo que más tiempo cuesta hoy reconstruir a mano.

## 5. Fuentes certificadas
El responsable marca una tabla o vista como **fuente oficial** de un dato (por ejemplo la cartera en el DWH de
producción) y las demás copias por ambiente quedan como «copia» o «no usar». El chat ordena primero la oficial y lo
dice. Evita reprocesos por elegir la tabla equivocada, una de las métricas de F25.

## 6. Avisos de cambio a quien usa una tabla
El Builder ya sabe qué objetos cambiaron entre dos catálogos (compara su `schema_hash`); faltaría el detalle por
columna (nueva, borrada, cambio de tipo). Con el historial de confirmaciones
(«Es este») se sabe quién depende de cada tabla. Cuando cambia, se avisa a esas personas y al responsable antes de que
falle un reporte. Solo metadatos, sin valores.

## 7. Integración con el gestor de requerimientos
Desde el chat, **Adjuntar a requerimiento** lleva las fuentes confirmadas a la historia de Jira o Azure DevOps. Deja
documentado de dónde sale cada dato del requerimiento y permite medir automáticamente las métricas de F25 (tiempo de
análisis, reprocesos) en lugar de con encuestas.

## 8. Asistente en Microsoft Teams
Un bot de Teams que usa el mismo `/discover` y el MCP, con la misma identidad y los mismos permisos. Llega a quien no
abre la web, y las respuestas incluyen el enlace a la ficha. Depende del inicio de sesión corporativo (feature 9):
con login SQL no hay forma segura de autenticar en Teams.

## 9. Inicio de sesión corporativo (Entra ID / AD)
Hoy cada persona entra con su login SQL por servidor (F14). Con Entra ID o AD, un solo inicio de sesión. Los permisos
de SQL se siguen heredando mediante la autenticación integrada de Windows on-premise, o con identidades de Entra en
Azure SQL. Los grupos del directorio alimentan las áreas de F26. Necesita la decisión de Seguridad sobre la
delegación de credenciales.

## 10. Informe de uso para auditoría
Un informe periódico, para Auditoría interna, con quién buscó, abrió o pidió acceso a activos clasificados como
sensibles (feature 3) y desde qué área. La auditoría encadenada ya existe (F11); falta la vista por sensibilidad y la
exportación firmada.

## Orden sugerido
1. **F26 y Pedir acceso (1 y 2):** dan el control por área que el banco pide y son pequeños sobre lo que ya existe.
2. **Clasificación y certificación (3 y 5):** elevan la confianza en las respuestas con poco código.
3. **Linaje normativo (4):** el de mayor valor regulatorio, pero el más grande.
4. **Canales e integración (7, 8 y 9):** cuando el piloto confirme la adopción.
