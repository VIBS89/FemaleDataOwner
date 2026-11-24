# deploy/windows

Hoy esta carpeta tiene un solo script: `registrar-tareas.ps1`, que registra en el Programador de tareas de Windows las tareas de
mantenimiento de DiscoveryDataAgent (OP-07, HU-18 y HU-24).

> **Estado.** Verificado solo con análisis de sintaxis y con `-WhatIf` en un equipo de desarrollo. **No se ha registrado ni
> ejecutado en un Windows Server del banco.** Antes del piloto hay que probarlo con la cuenta de servicio real.

## Qué hace

Crea o actualiza tres tareas en la carpeta `\DiscoveryDataAgent\` del Programador de tareas:

| Tarea | Cuándo | Comando |
|---|---|---|
| Refrescar catalogo | cada noche (01:30 por defecto) | `discovery-data-agent catalog build --db [--models <archivo>]` |
| Purgar auditoria | cada domingo (03:30 por defecto) | `discovery-data-agent audit purge` (retención de 180 días) |
| Medir regresion | cada lunes a las 05:00; solo con `-GateRoot` | `discovery-data-agent eval gate --db --root <casos>` |

Todas corren con la cuenta de servicio indicada (en el servidor del banco, la gMSA de metadatos), aunque nadie haya iniciado
sesión, y dejan su salida en `data\logs\` dentro de la instalación (un archivo por tarea). La cadena de conexión no se pasa por
línea de comandos: cada tarea lee la variable de entorno `DISCOVERY_DATA_AGENT_DB` de la cuenta que la ejecuta. Con `-WhatIf` muestra lo que
haría sin registrar nada; con `-Remove` quita las tareas.

## Requisitos

- DiscoveryDataAgent instalado en `-InstallRoot`, con `.venv\Scripts\python.exe` y `db\discovery_data_agent`.
- La variable de entorno `DISCOVERY_DATA_AGENT_DB` definida para la cuenta de servicio.
- Para esa cuenta, el derecho "Iniciar sesión como proceso por lotes" y permiso de escritura en `data\logs`.
- Con `-ModelsPath` (`config\models.yaml`), el refresco describe con IA las tablas y columnas nuevas; sin él no usa modelo.

## Ejemplos

```powershell
# Registrar las tres tareas con la cuenta gMSA (termina en $ y no lleva contraseña)
.\registrar-tareas.ps1 -InstallRoot D:\DiscoveryDataAgent -ServiceAccount 'BANCO\svc-discovery-data-agent$' -ModelsPath D:\DiscoveryDataAgent\config\models.yaml

# Ver lo que haría, sin registrar nada
.\registrar-tareas.ps1 -InstallRoot D:\DiscoveryDataAgent -ServiceAccount 'BANCO\svc-discovery-data-agent$' -WhatIf

# Quitar las tareas
.\registrar-tareas.ps1 -InstallRoot D:\DiscoveryDataAgent -ServiceAccount 'BANCO\svc-discovery-data-agent$' -Remove
```

Otros parámetros: `-BuildTime` y `-PurgeTime` (`HH:mm`), `-GateRoot` (directorio con los casos de evaluación, p. ej.
`tests\fixtures\bancos`; sin él no se registra la regresión) y `-BuildHoursLimit` (tope de duración del refresco, 4 h por defecto).

## Lo que falta de OP-07

Este script cubre solo el paso 6 de [OP-07](../../docs/specs/on-premise/OP-07-instalacion-operacion.md). Faltan: IIS con
HttpPlatformHandler y los `web.config` de la web y de la API, el certificado TLS, el firewall, los secretos con DPAPI, el
endurecimiento, la verificación (`10-verificar.ps1`) y el respaldo con su prueba de restauración (HU-37 a HU-39). Además, el script
ejecuta las tres tareas con una sola cuenta; OP-07 pide separar la del Builder de la de mantenimiento (la purga), y no envía el
aviso por webhook de Teams cuando una tarea falla.

## Verificado y por verificar

Verificado el 2026-11-23 en un equipo de desarrollo, contra una base `DiscoveryDataAgent` temporal en SQL Server (creada y
eliminada para la prueba): los tres comandos que lanzan las tareas corren de verdad.

- `discovery-data-agent catalog build --db` necesita que el inventario de servidores ya esté registrado en la BD (se registra
  desde Administración → Servidores). Sin inventario termina con código de salida 1 y el mensaje "La BD DiscoveryDataAgent no
  tiene inventario de servidores", así que la tarea aparece como fallida en el Programador y no pasa inadvertida.
- Un refresco sobre un catálogo ya publicado conserva los objetos sin cambio de estructura, les suma los sinónimos
  por reglas que falten y deja pendientes de describir los que no tienen descripción: al configurar un modelo, el
  siguiente refresco los describe con IA.
- `discovery-data-agent eval gate --db --root tests\fixtures\bancos` aprueba contra el catálogo refrescado.
- `discovery-data-agent audit purge` corre y respeta la retención de 180 días.

Por verificar en el servidor del banco: el registro de las tareas con la cuenta de servicio (aquí solo con `-WhatIf`),
su ejecución sin sesión iniciada y los permisos de esa cuenta.
