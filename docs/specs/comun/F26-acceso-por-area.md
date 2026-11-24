# F26 — Acceso por área de trabajo · común

> **Estado: propuesta para una versión futura. No construido.** Escrito el 2026-11-24. No cambia el alcance de la
> fase 1a ni el piloto: se retoma cuando el banco confirme las decisiones abiertas del final.
>
> Relacionado: [F14](F14-identity.md) (permisos heredados), [F24](F24-knowledge-curation.md) (dominios y responsables),
> [F23](F23-knowledge-sources.md) (ACL de los documentos), [F11](F11-audit.md) (auditoría).

## Problema
Hoy lo que ve cada persona sale solo de los permisos de su login en SQL Server (F14). Eso protege los datos, pero no
expresa la organización del banco: una analista de Tarjetas con lectura amplia en el DWH ve en el chat, el catálogo y
el MCP tablas de Préstamos o de Cumplimiento que no le corresponden por su trabajo. Pedir al DBA que recorte permisos
por área es lento y mezcla dos decisiones distintas: **qué puede leer un login** (seguridad de la base) y **qué
información le corresponde a una persona según su área** (gobierno de datos).

Además, el filtro por grupos de los documentos de conocimiento (`allowed_groups`, F23) existe en
`src/discovery_data_agent/memory/memory_store.py`, pero `Session.groups` nunca se rellena: hoy un documento con ACL no
lo ve nadie.

## Qué hace
El administrador de datos define **áreas** y asigna personas a ellas. Lo que una persona alcanza es la intersección:

```
visible = permisos SQL del login (F14)  ∩  activos de sus áreas (F26)
```

El área **solo recorta**: nunca da acceso a algo que SQL Server niega.

| Pieza | Contenido |
|---|---|
| Área | Nombre, descripción y responsable funcional (por ejemplo Tarjetas, Préstamos, Cumplimiento, Riesgo) |
| Activos del área | Patrones de `asset_key`, los mismos que ya usan los dominios de F24 (`BancaPrestamos.*`, `BancaTarjetasCredito.dbo.Pagos*`) |
| Grupos de conocimiento | Los grupos que habilitan glosarios, manuales y reglas con `allowed_groups` |
| Capacidades | Qué puede hacer el área: descubrir dónde está el dato (siempre), cifras agregadas (`ask_flow`), herramientas MCP, exportar fichas |
| Miembros | Logins (o grupos de AD, según la decisión 1) |

## Flujo
1. Al iniciar sesión, la API resuelve las áreas del login y las guarda en la sesión, junto con sus grupos.
2. `AgentRuntime.visible_ids` cruza los objetos que permite SQL Server con los patrones de las áreas. Como todo el flujo
   ya filtra por `visible_ids` (búsqueda, candidatos, ubicaciones, alternativas, fichas, catálogo, MCP, cifras), lo
   heredan sin cambios. Un cambio de áreas invalida la caché de esa sesión (hoy de 15 minutos).
3. `UserContext.groups` sale de las áreas: el filtro `allowed_groups` de glosarios y documentos empieza a funcionar.
4. Antes de ejecutar una capacidad (por ejemplo cifras), el flujo comprueba que alguna de las áreas del usuario la
   tenga. La intención ya la detecta el nodo `intent`.
5. Si lo pedido existe pero cae fuera de sus áreas, la respuesta dice «no está disponible para tu área» y ofrece pedir
   acceso al responsable, **sin nombrar el objeto**. Se audita como `area_denied`.

## Reglas
- **Se restringen datos, no textos de pregunta.** Prohibir preguntas por tema se evita reformulando y depende del LLM;
  lo que se controla es qué activos se pueden alcanzar.
- **Fail-closed.** Sin áreas asignadas no se ve nada (salvo decisión 2 del banco). Si no se pueden leer las áreas, nada.
- `data_admin` ve todo lo que su login permite; los responsables (F24) curan dentro de sus dominios, como hoy.
- Las cifras agregadas siguen usando la credencial del usuario: el área es un filtro adicional, no una credencial.

## Persistencia (migración `003_acceso_por_area.sql`)
Esquema `access`, tablas temporales con historial (quién cambió qué y cuándo), como `curation`:

| Tabla | Columnas principales |
|---|---|
| `access.area` | `area_id`, `name`, `description`, `owner_login`, `capabilities_json` |
| `access.area_asset` | `area_id`, `pattern` |
| `access.area_group` | `area_id`, `group_name` |
| `access.area_member` | `area_id`, `login` (o `ad_group`) |

## Interfaces
- API: `GET/PUT/DELETE /admin/areas`, `PUT /admin/areas/{id}/members`; `/auth/me` devuelve `areas`.
- Web: **Administración → Áreas** (crear, patrones con vista previa de los objetos que cubren, miembros, capacidades).
  El usuario ve sus áreas en su perfil. El catálogo y el chat ya muestran solo lo visible.
- MCP: sin cambios de contrato; hereda el filtro.
- Métricas (F25): preguntas fuera de área por área, para detectar áreas mal definidas.

## Criterios de aceptación
| # | Criterio |
|---|---|
| CA1 | Un usuario con lectura SQL sobre cinco bases y un área que cubre dos solo recibe candidatos, fichas, catálogo y respuestas MCP de esas dos |
| CA2 | Un área nunca amplía: un patrón que cubre una tabla sin permiso SQL no la hace visible |
| CA3 | Un usuario sin área no ve ningún objeto (o lo que decida el banco en la decisión 2), y la API lo registra |
| CA4 | Un glosario con `allowed_groups` solo aparece a quien tiene ese grupo por sus áreas |
| CA5 | Una pregunta de cifras de un área sin esa capacidad se responde sin ejecutar SQL y se audita `area_denied` |
| CA6 | La respuesta fuera de área no contiene el nombre de ningún objeto oculto (prueba del literal marcado, como F14) |
| CA7 | Un cambio de áreas se aplica en la siguiente pregunta, sin esperar la caché |
| CA8 | Cada cambio de áreas, patrones o miembros queda en el historial con autor y fecha |
| CA9 | Evaluación por área: Hit@1 sin regresión para cada área frente a la línea base sin F26 |

## Decisiones abiertas (del banco)
1. **Fuente de las áreas:** manual en la app, grupos de Active Directory (lo más mantenible on-premise; en AWS exige
   Entra ID o un conector) o roles de SQL Server (los administra el DBA y la app solo los lee).
2. **Usuario sin área:** no ve nada (recomendado) o ve lo que le permite SQL Server.
3. **Capacidades por área:** solo datos, o también cifras, MCP y exportación.
4. **Pedir acceso:** si la solicitud fuera de área va al responsable del área (F24) o a un flujo de accesos existente.

## Fuera de alcance
- Enmascarar valores de columnas: DiscoveryDataAgent no devuelve valores de datos (F1, F17).
- Sustituir los permisos de SQL Server: siguen siendo la primera barrera.

## Tamaño estimado
Una migración, un filtro en `visible_ids`, la resolución de áreas en el login, la pantalla de administración y sus
pruebas de fuga: alrededor de dos semanas de una persona, más la decisión 1 si se integra con AD.
