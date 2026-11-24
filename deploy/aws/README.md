# DiscoveryDataAgent en AWS

Infraestructura como código del despliegue de [CN-01](../../docs/specs/cloud-native/CN-01-despliegue-aws.md): las dos
imágenes de `docker compose` en **una tarea de ECS Fargate** detrás de un ALB, el Builder del catálogo lanzado por
EventBridge Scheduler, Bedrock por VPC endpoint y la VPN al SQL Server del banco. AWS procesa y muestra; no guarda
catálogo, preguntas ni auditoría (CN-06).

Todo se hace con un script, igual en Windows (Git Bash), Linux y macOS:

```bash
bash deploy/aws/despliegue.sh <comando> <entorno>
```

| Carpeta | Qué es |
|---|---|
| `despliegue.sh` | Los comandos del equipo: `plan`, `apply`, `deploy`, `rollback`, `logs`… (`help` los lista) |
| `terraform/` | La pila de un entorno. Un archivo por tema: red, VPN, seguridad, ALB, ECS, alarmas |
| `terraform/envs/` | Un `.tfvars` por entorno: `demo.tfvars` y la plantilla `qa.tfvars.example` |
| `terraform/config/` | El `models.yaml` de Bedrock que recibe la tarea |
| `terraform/tests/` | Planes de prueba con el proveedor simulado (`despliegue.sh validate`) |
| `bootstrap/` | El bucket del estado de Terraform, una vez por cuenta |

No hay Ansible: en Fargate no existen servidores que configurar. La configuración de la aplicación son las
variables de la tarea, que salen del `.tfvars`, y los secretos de Secrets Manager.

## Qué se crea

| Pieza | Detalle |
|---|---|
| Red | VPC con dos subredes privadas **sin ruta a internet y sin NAT**. La tarea solo alcanza los VPC endpoints (ECR, S3, CloudWatch Logs, Secrets Manager, Bedrock) y, por la VPN, el 1433 de `sql_server_cidrs` |
| VPN y DNS | Lado AWS de la Site-to-Site VPN y reenvío de DNS a los servidores del banco (opcionales: `vpn`, `onprem_dns`) |
| Entrada | ALB interno con HTTPS; `/` va a la web y `/mcp` a la API. El resto de la API no se publica |
| Cómputo | Una tarea con `web` (3000), `api` (8000, un worker) y `api-eventos`, que lleva el log JSON de la API a CloudWatch |
| Builder | La imagen de la API con `discovery-data-agent catalog build --db`, cada noche; corre y termina |
| Secretos | Código de instalación (lo genera Terraform), cadena de la BD `DiscoveryDataAgent` y login de metadatos del Builder |
| Roles | Uno de ejecución y uno de tarea por cada tarea: la de la API no puede leer el login de metadatos (CN-03 CA3) |
| Observabilidad | Grupos de logs cifrados con KMS y las alarmas de CN-05 hacia un tema SNS |
| Imágenes | Dos repositorios ECR con etiquetas inmutables y análisis al subir |

Un despliegue **para la tarea anterior antes de arrancar la nueva**: nunca hay dos procesos con dos SessionVault.
Son alrededor de dos minutos de corte y los usuarios vuelven a iniciar sesión, así que conviene desplegar fuera de horario.

## Requisitos

- [Terraform](https://developer.hashicorp.com/terraform/install) 1.10 o superior, [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) y Docker Desktop en marcha (solo para `deploy`).
- Credenciales de la cuenta de AWS del entorno: `export AWS_PROFILE=<perfil>` tras `aws sso login`, o las variables `AWS_ACCESS_KEY_ID`… El script muestra la cuenta y la región antes de hacer nada.
- Permisos para crear VPC, ECS, ELB, IAM, KMS, Secrets Manager, ECR, CloudWatch, EventBridge y SSM.

Comprobación sin cuenta de AWS, útil antes de un PR que toque esta carpeta:

```bash
bash deploy/aws/despliegue.sh validate
```

## Primer despliegue: entorno demo

El demo usa servidores simulados (usuarios `demo` y `analista`, contraseña `demo`), sin VPN ni datos del banco. Sirve
para probar el camino completo. Su ALB es público pero solo acepta las IP que se indiquen; sin certificado va por HTTP.

1. **Estado de Terraform**, una vez por cuenta:
   ```bash
   bash deploy/aws/despliegue.sh bootstrap us-east-1
   ```
2. **Redes permitidas**: en `terraform/envs/demo.tfvars`, poner en `alb_ingress_cidrs` las IP públicas del equipo (`curl https://checkip.amazonaws.com`, con `/32`).
3. **Infraestructura** (unos 5 minutos; todavía sin tarea, porque no hay imágenes):
   ```bash
   bash deploy/aws/despliegue.sh apply demo
   ```
4. **Aplicación**: construye las imágenes del commit actual, las sube y arranca la tarea. Muestra el plan y pide confirmación.
   ```bash
   bash deploy/aws/despliegue.sh deploy demo
   ```
   Al terminar imprime la dirección del sitio. Con cambios sin commit: `ALLOW_DIRTY=1 bash deploy/aws/despliegue.sh deploy demo`.
5. **Apagarlo** cuando no se use (cuesta aunque nadie entre):
   ```bash
   bash deploy/aws/despliegue.sh destroy demo
   ```

## Entornos qa y prod

Cada uno en su cuenta de AWS, con el mismo código y distinto `.tfvars`.

1. Copiar `terraform/envs/qa.tfvars.example` a `qa.tfvars` y rellenarlo con los datos de Redes, Seguridad y el DBA. No lleva secretos.
2. Copiar `terraform/config/models.bedrock.example.yaml` a `models.qa.yaml` con el modelo elegido, y medirlo antes de aceptarlo (`discovery-data-agent eval discovery`).
3. `bootstrap <región>` y `apply qa`.
4. Entregar a Redes la salida `vpn` (`despliegue.sh output qa`) y las subredes de `task_subnets`: el firewall del banco abre el 1433 solo a esos rangos. Esto y la configuración del equipo VPN on-premise no se automatizan (CN-01 CA1).
5. Crear en el DNS interno el registro de `domain_name` hacia `alb_dns_name`.
6. Cargar los secretos (el valor se pide sin mostrarlo y no pasa por el repositorio ni por el estado):
   ```bash
   bash deploy/aws/despliegue.sh secret qa db                 # cadena ODBC de la BD DiscoveryDataAgent
   bash deploy/aws/despliegue.sh secret qa metadata-user      # login de metadatos del Builder
   bash deploy/aws/despliegue.sh secret qa metadata-password
   ```
   Los servidores del inventario deben nombrar esas variables: `metadata_user_env: DISCOVERY_DATA_AGENT_METADATA_USER` y `metadata_password_env: DISCOVERY_DATA_AGENT_METADATA_PASSWORD`.
7. Migraciones de la BD al día (`discovery-data-agent db migrate`, las aplica el DBA como en on-premise: la BD es la misma).
8. `deploy qa`. El primer servidor del inventario se registra desde la web con el código de `despliegue.sh setup-token qa`.

A qa y prod solo se sube un commit limpio: la etiqueta de la imagen es el hash del commit.

### Lo que hoy impide arrancar qa y prod

La infraestructura se crea completa, pero la tarea no quedará en servicio contra el banco hasta resolver estos puntos
de la [hoja de ruta cloud §5](../../docs/wiki/hoja-de-ruta-cloud.md). Ninguno se arregla con Terraform.

| Bloqueo | Efecto | Quién decide |
|---|---|---|
| Con `DISCOVERY_DATA_AGENT_ENV=qa\|prod` la API rechaza una `DISCOVERY_DATA_AGENT_DB` con contraseña (exige la gMSA), y un contenedor Linux no tiene gMSA | La tarea se detiene al arrancar con el mensaje de `production_violations` | Seguridad y cambio de código |
| El contenedor no confía en la CA que firma el certificado de los SQL Server del banco, y `TrustServerCertificate` está prohibido | Falla la conexión TLS | Seguridad; la CA debe entrar en la imagen |
| La cuenta de AWS, Bedrock habilitado sin *invocation logging*, la VPN y el firewall | Sin red no hay SQL Server | Nube, Redes |
| El webhook de Teams no tiene salida: la tarea no llega a internet | Notificaciones apagadas | Redes |

Mientras tanto, el demo valida todo lo demás: imágenes, ECR, tarea, ALB, endpoints, logs, alarmas y Bedrock.

## Día a día

| Para | Comando |
|---|---|
| Subir una versión | `despliegue.sh deploy <entorno>` |
| Volver a la anterior | `despliegue.sh rollback <entorno> <etiqueta>` (la etiqueta actual: `status`) |
| Cambiar configuración | Editar el `.tfvars`, luego `plan` y `apply` |
| Ver el estado | `despliegue.sh status <entorno>` |
| Ver logs | `despliegue.sh logs <entorno> [api\|web\|builder]` |
| Rotar un secreto | `despliegue.sh secret <entorno> <nombre>` y `restart` |
| Refrescar el catálogo ya | `despliegue.sh builder-run <entorno>` |

`plan` y `apply` no cambian la versión desplegada: la etiqueta vive en un parámetro de SSM que solo mueven `deploy` y
`rollback`, así que cualquiera del equipo obtiene el mismo plan. Si la tarea nueva no pasa la comprobación de salud,
ECS vuelve sola a la definición anterior.

Las alarmas llegan al correo de `alarm_email` tras confirmar la suscripción. La de «tarea detenida» también avisa en
cada despliegue.

## Coste orientativo

Con precios de lista de `us-east-1`, que conviene comprobar: el demo ronda los **120–130 USD al mes** encendido todo
el tiempo (los VPC endpoints unos 60, la tarea de 1 vCPU y 4 GB unos 45, el ALB unos 20). En qa y prod se suman la
tarea mayor, la VPN (unos 36) y el reenvío de DNS (unos 180: es lo más caro; se evita si el banco acepta registrar los
nombres en una zona privada de Route 53).

## Pendiente

- **CI**: construir y analizar las imágenes y ejecutar `despliegue.sh validate` en `calidad.yml` (DT-45); desplegar desde GitHub Actions con un rol OIDC.
- **Logs a la salida estándar** en la API: al hacerlo se quita el contenedor `api-eventos` de `terraform/ecs.tf`.
- **Bedrock desde la tarea** (HU-35) está sin probar: si `langchain-aws` consulta además el plano de control, hay que añadir el endpoint `bedrock` a `interface_endpoints` en `terraform/network.tf`.
- **Alarma de «el Builder no corrió»** y comprobación automática del *invocation logging* de Bedrock (CN-06 CA3).
- Tamaño de la tarea, retención de logs, umbrales y tiempo de inactividad del ALB: valores por defecto por confirmar en qa.
