# deploy/windows

Hoy esta carpeta tiene un solo script: `registrar-tareas.ps1`, que registra en el Programador de tareas de Windows las tareas de
mantenimiento de ConverData (OP-07, HU-18 y HU-24).

> **Estado.** Verificado solo con análisis de sintaxis y con `-WhatIf` en un equipo de desarrollo. **No se ha registrado ni
> ejecutado en un Windows Server del banco.** Antes del piloto hay que probarlo con la cuenta de servicio real.

## Qué hace

Crea o actualiza tres tareas en la carpeta `\ConverData\` del Programador de tareas:

| Tarea | Cuándo | Comando |
|---|---|---|
| Refrescar catalogo | cada noche (01:30 por defecto) | `converdata catalog build --db [--models <archivo>]` |
| Purgar auditoria | cada domingo (03:30 por defecto) | `converdata audit purge` (retención de 180 días) |
| Medir regresion | cada lunes a las 05:00; solo con `-GateRoot` | `converdata eval gate --db --root <casos>` |

Todas corren con la cuenta de servicio indicada (en el servidor del banco, la gMSA de metadatos), aunque nadie haya iniciado
sesión, y dejan su salida en `data\logs\` dentro de la instalación (un archivo por tarea). La cadena de conexión no se pasa por
línea de comandos: cada tarea lee la variable de entorno `CONVERDATA_DB` de la cuenta que la ejecuta. Con `-WhatIf` muestra lo que
haría sin registrar nada; con `-Remove` quita las tareas.

## Requisitos

- ConverData instalado en `-InstallRoot`, con `.venv\Scripts\python.exe` y `db\converdata`.
- La variable de entorno `CONVERDATA_DB` definida para la cuenta de servicio.
- Para esa cuenta, el derecho "Iniciar sesión como proceso por lotes" y permiso de escritura en `data\logs`.
- Con `-ModelsPath` (`config\models.yaml`), el refresco describe con IA las tablas y columnas nuevas; sin él no usa modelo.

## Ejemplos

```powershell
# Registrar las tres tareas con la cuenta gMSA (termina en $ y no lleva contraseña)
.\registrar-tareas.ps1 -InstallRoot D:\ConverData -ServiceAccount 'BANCO\svc-converdata$' -ModelsPath D:\ConverData\config\models.yaml

# Ver lo que haría, sin registrar nada
.\registrar-tareas.ps1 -InstallRoot D:\ConverData -ServiceAccount 'BANCO\svc-converdata$' -WhatIf

# Quitar las tareas
.\registrar-tareas.ps1 -InstallRoot D:\ConverData -ServiceAccount 'BANCO\svc-converdata$' -Remove
```

Otros parámetros: `-BuildTime` y `-PurgeTime` (`HH:mm`), `-GateRoot` (directorio con los casos de evaluación, p. ej.
`tests\fixtures\bancos`; sin él no se registra la regresión) y `-BuildHoursLimit` (tope de duración del refresco, 4 h por defecto).

## Lo que falta de OP-07

Este script cubre solo el paso 6 de [OP-07](../../docs/specs/on-premise/OP-07-instalacion-operacion.md). Faltan: IIS con
HttpPlatformHandler y los `web.config` de la web y de la API, el certificado TLS, el firewall, los secretos con DPAPI, el
endurecimiento, la verificación (`10-verificar.ps1`) y el respaldo con su prueba de restauración (HU-37 a HU-39). Además, el script
ejecuta las tres tareas con una sola cuenta; OP-07 pide separar la del Builder de la de mantenimiento (la purga), y no envía el
aviso por webhook de Teams cuando una tarea falla.
