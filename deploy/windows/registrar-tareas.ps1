<#
.SYNOPSIS
  Registra en el Programador de tareas de Windows las tareas de mantenimiento de ConverData (OP-07, HU-18).

.DESCRIPTION
  Crea o actualiza tres tareas en la carpeta \ConverData\ del Programador de tareas:

    Refrescar catalogo   cada noche    converdata catalog build --db [--models <archivo>]
        Vuelve a leer los metadatos de los servidores del inventario, detecta tablas y columnas nuevas, cambiadas
        o eliminadas, describe lo nuevo con IA (si se indica el archivo de modelos) y publica el catalogo en la BD
        ConverData. La API carga la version nueva sin reiniciar.
    Purgar auditoria     cada domingo  converdata audit purge
        Retencion de 180 dias de la auditoria, las dudas escaladas y los originales.
    Medir regresion      cada lunes    converdata eval gate --db --root <fixtures>   (solo con -GateRoot)
        Compuerta de calidad contra el catalogo vigente; sale con error si un indicador baja.

  Las tareas corren con la cuenta de servicio indicada (en el servidor del banco, la gMSA de metadatos), aunque nadie
  haya iniciado sesion. La cadena de conexion de la BD ConverData no se pasa por linea de comandos: cada tarea lee la
  variable de entorno CONVERDATA_DB de la cuenta que la ejecuta.

  Con -WhatIf muestra lo que haria sin registrar nada. Con -Remove quita las tareas.

.EXAMPLE
  .\registrar-tareas.ps1 -InstallRoot D:\ConverData -ServiceAccount 'BANCO\svc-converdata$' -ModelsPath D:\ConverData\config\models.yaml

.EXAMPLE
  .\registrar-tareas.ps1 -InstallRoot D:\ConverData -ServiceAccount 'BANCO\svc-converdata$' -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Carpeta de la instalacion: contiene .venv y db\converdata.
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    # Cuenta que ejecuta las tareas. Una gMSA termina en $ y no lleva contrasena.
    [Parameter(Mandatory = $true)] [string] $ServiceAccount,
    # config\models.yaml: con el, las tablas y columnas nuevas reciben descripcion sugerida por IA (sin revisar).
    [string] $ModelsPath,
    # Hora del refresco nocturno del catalogo (HH:mm, hora del servidor).
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')] [string] $BuildTime = '01:30',
    # Hora de la purga semanal (domingo).
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')] [string] $PurgeTime = '03:30',
    # Directorio con los casos de evaluacion (p. ej. tests\fixtures\bancos). Sin el no se registra la regresion.
    [string] $GateRoot,
    # Tope de duracion de un refresco (OP-07: un build largo termina aunque IIS recicle la API).
    [ValidateRange(1, 12)] [int] $BuildHoursLimit = 4,
    # Quita las tareas en lugar de registrarlas.
    [switch] $Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskPath = '\ConverData\'
$Python = Join-Path $InstallRoot '.venv\Scripts\python.exe'
$LogDir = Join-Path $InstallRoot 'data\logs'

if ($Remove) {
    foreach ($name in 'Refrescar catalogo', 'Purgar auditoria', 'Medir regresion') {
        if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $name -ErrorAction SilentlyContinue) {
            if ($PSCmdlet.ShouldProcess("$TaskPath$name", 'Quitar tarea programada')) {
                Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $name -Confirm:$false
            }
        }
    }
    return
}

if (-not (Test-Path $Python)) {
    throw "No existe $Python. Instale ConverData en $InstallRoot antes de registrar las tareas."
}
if ($ModelsPath -and -not (Test-Path $ModelsPath)) {
    throw "No existe el archivo de modelos $ModelsPath."
}
if ($GateRoot -and -not (Test-Path $GateRoot)) {
    throw "No existe el directorio de evaluacion $GateRoot."
}

function Get-Principal {
    # Una gMSA (termina en $) inicia sesion como servicio sin contrasena; otra cuenta de servicio, con la contrasena
    # guardada por el Programador (se pide al registrar, nunca se escribe en este script).
    if ($ServiceAccount.EndsWith('$')) {
        return New-ScheduledTaskPrincipal -UserId $ServiceAccount -LogonType Password -RunLevel Limited
    }
    return New-ScheduledTaskPrincipal -UserId $ServiceAccount -LogonType S4U -RunLevel Limited
}

function Register-ConverDataTask {
    param([string] $Name, [string] $Description, [string[]] $CliArgs, $Trigger, [int] $HoursLimit)

    # Cada corrida deja su salida en un archivo por tarea (sin contenido de datos: el CLI imprime solo conteos).
    $log = Join-Path $LogDir (($Name -replace ' ', '-').ToLower() + '.log')
    $cli = '-m converdata.cli ' + ($CliArgs -join ' ')
    $command = "/c `"`"$Python`" $cli >> `"$log`" 2>&1`""
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $command -WorkingDirectory $InstallRoot
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours $HoursLimit) -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 15)

    if ($PSCmdlet.ShouldProcess("$TaskPath$Name", "Registrar tarea programada: python $cli")) {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        Register-ScheduledTask -TaskPath $TaskPath -TaskName $Name -Description $Description -Action $action `
            -Trigger $Trigger -Settings $settings -Principal (Get-Principal) -Force | Out-Null
        Write-Host "Registrada: $TaskPath$Name"
    }
}

$buildArgs = @('catalog', 'build', '--db')
if ($ModelsPath) { $buildArgs += @('--models', "`"$ModelsPath`"") }
Register-ConverDataTask -Name 'Refrescar catalogo' `
    -Description 'ConverData: lee los metadatos de los servidores del inventario y publica el catalogo (tablas y columnas nuevas, cambiadas o eliminadas).' `
    -CliArgs $buildArgs -Trigger (New-ScheduledTaskTrigger -Daily -At $BuildTime) -HoursLimit $BuildHoursLimit

Register-ConverDataTask -Name 'Purgar auditoria' `
    -Description 'ConverData: retencion de 180 dias de la auditoria, las dudas escaladas y los originales.' `
    -CliArgs @('audit', 'purge') -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $PurgeTime) -HoursLimit 1

if ($GateRoot) {
    Register-ConverDataTask -Name 'Medir regresion' `
        -Description 'ConverData: compuerta de calidad contra el catalogo vigente; falla si un indicador baja.' `
        -CliArgs @('eval', 'gate', '--db', '--root', "`"$GateRoot`"") `
        -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '05:00') -HoursLimit 1
}

Write-Host ''
Write-Host 'Recuerde: la cuenta de servicio necesita la variable de entorno CONVERDATA_DB, el derecho "Iniciar sesion como'
Write-Host 'proceso por lotes" y permiso de escritura en' $LogDir
