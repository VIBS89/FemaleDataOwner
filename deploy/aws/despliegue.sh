#!/usr/bin/env bash
# Despliegue de DiscoveryDataAgent en AWS (CN-01). Guía completa: deploy/aws/README.md
#
#   bash deploy/aws/despliegue.sh <comando> <entorno> [opciones de terraform]
#
# Funciona igual en Linux, macOS y Git Bash de Windows. Necesita terraform >= 1.10, AWS CLI v2 con credenciales de la
# cuenta del entorno (AWS_PROFILE o variables de entorno) y, para `deploy`, Docker en marcha.
set -euo pipefail
# Git Bash convierte en rutas de Windows los argumentos que empiezan por "/" (nombres de grupos de logs, cadenas ODBC).
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Uso: bash deploy/aws/despliegue.sh <comando> <entorno> [opciones]

De punta a punta (entornos de prueba)
  up <entorno>              bootstrap si falta, apply, claves de LLM desde el .env y deploy. Imprime la dirección.
  teardown <entorno>        Destruye el entorno y, si no queda otro en la cuenta, el bucket del estado: sin cobros.

Preparación
  validate                  Formato, validación y planes de prueba del Terraform. No necesita cuenta de AWS.
  bootstrap <región>        Una vez por cuenta: crea el bucket del estado de Terraform.

Infraestructura (el entorno es el nombre de terraform/envs/<entorno>.tfvars)
  plan <entorno>            Muestra lo que cambiaría.
  apply <entorno>           Crea o actualiza la infraestructura. Pide confirmación.
  output <entorno>          Direcciones y nombres de lo creado.
  destroy <entorno>         Elimina el entorno. Pide confirmación.

Aplicación
  deploy <entorno>          Construye las imágenes del commit actual, las sube a ECR y actualiza la tarea.
  rollback <entorno> <etq>  Vuelve a una etiqueta ya publicada.
  restart <entorno>         Reinicia la tarea (p. ej. tras cambiar un secreto). Cierra las sesiones.
  secret <entorno> <nombre> Carga el valor de un secreto (db, metadata-user, metadata-password, nvidia-api-key…). Lo
                            pide sin mostrarlo, o lo lee de la entrada estándar: ... secret demo nvidia-api-key < archivo
  setup-token <entorno>     Muestra el código de instalación que pide el registro del primer servidor.
  credentials <entorno>     Con SQL Server en la tarea: cómo registrar el servidor y las contraseñas de los usuarios.
  builder-run <entorno>     Lanza ahora el Builder del catálogo, sin esperar a la hora programada.

Operación
  status <entorno>          Estado del servicio y dirección del sitio.
  start|stop <entorno>      Enciende o apaga la tarea (0 tareas = no se paga Fargate; el ALB sigue).
  logs <entorno> [grupo]    Sigue los logs: api (por defecto), web o builder.
EOF
  exit "${1:-0}"
}

die() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Falta '$1' en el PATH. Ver deploy/aws/README.md §Requisitos."; }
tfvar() { sed -n "s/^$1[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$TFVARS" | head -n 1; }

# Lee el tfvars del entorno y deja listos región, cuenta y bucket del estado.
load_env() {
  [ -n "${ENV_NAME:-}" ] || usage 1
  TFVARS="terraform/envs/$ENV_NAME.tfvars"
  [ -f "$TFVARS" ] || die "No existe deploy/aws/$TFVARS. Para qa o prod, copia envs/qa.tfvars.example y rellénalo."
  [ "$(tfvar environment)" = "$ENV_NAME" ] || die "$TFVARS declara environment = \"$(tfvar environment)\", no \"$ENV_NAME\"."
  need terraform; need aws
  REGION="$(tfvar region)"; REGION="${REGION:-${AWS_REGION:-us-east-1}}"
  export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
  ACCOUNT="$(aws sts get-caller-identity --query Account --output text)" \
    || die "Sin credenciales de AWS válidas. Configura AWS_PROFILE o inicia sesión con 'aws sso login'."
  BUCKET="discovery-data-agent-tfstate-$ACCOUNT-$REGION"
  NAME="discovery-data-agent-$ENV_NAME"
  echo ">> Entorno $ENV_NAME · cuenta $ACCOUNT · región $REGION" >&2

  # Entornos de prueba con `alb_ingress_cidrs = []`: se abre solo a la IP pública de quien ejecuta el script.
  TF_VARS=(-var-file="envs/$ENV_NAME.tfvars")
  if grep -Eq '^alb_ingress_cidrs[[:space:]]*=[[:space:]]*\[\]' "$TFVARS"; then
    case "$(tfvar discovery_data_agent_env)" in qa|prod) die "alb_ingress_cidrs vacío en $TFVARS." ;; esac
    local ip; ip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')" || die "No se pudo averiguar la IP pública."
    TF_VARS+=(-var "alb_ingress_cidrs=[\"$ip/32\"]")
    echo ">> ALB abierto solo a $ip/32" >&2
  fi
}

tf() { (cd terraform && terraform "$@"); }

tf_init() {
  tf init -input=false -reconfigure \
    -backend-config="bucket=$BUCKET" -backend-config="key=discovery-data-agent/$ENV_NAME/terraform.tfstate" \
    -backend-config="region=$REGION" >/dev/null \
    || die "terraform init falló. ¿Se ejecutó 'bootstrap $REGION' en esta cuenta?"
}

tf_apply() { tf apply -input=false "${TF_VARS[@]}" "$@"; }
out() { tf output -raw "$1"; }

wait_stable() {
  echo ">> Esperando a que la tarea quede en servicio (unos minutos)…" >&2
  aws ecs wait services-stable --cluster "$NAME" --services "$NAME" \
    || die "El servicio no se estabilizó. Revisa: bash deploy/aws/despliegue.sh logs $ENV_NAME"
  echo ">> En servicio: $(out url)"
}

# Publica una etiqueta en el parámetro que lee Terraform y aplica; si el apply falla o se cancela, lo deja como estaba.
release() {
  local tag="$1" previous param; shift
  previous="$(out image_tag)"; param="$(out image_tag_parameter)"
  aws ssm put-parameter --name "$param" --type String --overwrite --value "$tag" >/dev/null
  if ! tf_apply "$@"; then
    aws ssm put-parameter --name "$param" --type String --overwrite --value "$previous" >/dev/null
    die "No se aplicó el cambio; la etiqueta desplegada sigue siendo $previous."
  fi
  wait_stable
}

image_exists() { aws ecr describe-images --repository-name "$1" --image-ids "imageTag=$2" >/dev/null 2>&1; }

# SQL Server Express con las bases de BancosSQL.zip cargadas (sql_sidecar). La carga tarda unos 6 minutos.
build_sqlserver() {
  local image="$1" ctx
  need unzip
  ctx="$(mktemp -d)"
  cp sqlserver/* "$ctx/"
  mkdir "$ctx/bancos"
  unzip -q -j ../../BancosSQL.zip 'bancos_sql/0[1-9]_*.sql' -d "$ctx/bancos"
  echo ">> Construyendo SQL Server con las bases de prueba (unos 6 minutos)" >&2
  (cd "$ctx" && docker build --platform linux/amd64 --provenance=false -t "$image" .) || { rm -rf "$ctx"; die "Falló la imagen de SQL Server."; }
  rm -rf "$ctx"
  docker push "$image"
}

cmd_deploy() {
  need docker; need git
  docker info >/dev/null 2>&1 || die "Docker no está en marcha."
  local tag dirty api web registry
  tag="$(git rev-parse --short=12 HEAD)"
  dirty="$(git status --porcelain)"
  if [ -n "$dirty" ]; then
    case "$(tfvar discovery_data_agent_env)" in
      qa|prod) die "Hay cambios sin commit. A qa y prod solo se sube un commit, para que la etiqueta diga qué código corre." ;;
    esac
    [ "${ALLOW_DIRTY:-0}" = "1" ] || die "Hay cambios sin commit. Haz commit o repite con ALLOW_DIRTY=1 (solo entornos de prueba)."
    tag="$tag-local-$(date +%Y%m%d%H%M%S)"
  fi
  tf_init
  api="$(out ecr_api)" || die "Aún no existe la infraestructura: ejecuta antes 'apply $ENV_NAME'."
  web="$(out ecr_web)"; registry="${api%%/*}"
  echo ">> Etiqueta $tag" >&2
  aws ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null

  # Las etiquetas son inmutables: si la imagen de este commit ya está en ECR, no se vuelve a construir.
  if image_exists "${api#*/}" "$tag"; then echo ">> api:$tag ya está publicada" >&2; else
    local requirements; requirements="$(tfvar api_requirements)"
    (cd ../.. && docker build --platform linux/amd64 --provenance=false \
      --build-arg "REQUIREMENTS=${requirements:-requirements/runtime.lock}" -f api/Dockerfile -t "$api:$tag" .)
    docker push "$api:$tag"
  fi
  if image_exists "${web#*/}" "$tag"; then echo ">> web:$tag ya está publicada" >&2; else
    (cd ../.. && docker build --platform linux/amd64 --provenance=false -t "$web:$tag" web)
    docker push "$web:$tag"
  fi
  local sql; sql="$(out ecr_sqlserver)"
  if [ -n "$sql" ]; then
    if image_exists "${sql#*/}" "$tag"; then echo ">> sqlserver:$tag ya está publicada" >&2; else build_sqlserver "$sql:$tag"; fi
  fi
  release "$tag" "$@"
}

cmd_rollback() {
  local tag="${1:-}"; [ -n "$tag" ] || die "Indica la etiqueta: rollback $ENV_NAME <etiqueta>"; shift
  tf_init
  local repos="api web"; [ -z "$(out ecr_sqlserver)" ] || repos="$repos sqlserver"
  for repo in $repos; do
    image_exists "$NAME/$repo" "$tag" || die "La etiqueta $tag no está en el repositorio $NAME/$repo."
  done
  release "$tag" "$@"
}

cmd_secret() {
  local name="${1:-}" value
  [[ "$name" =~ ^[a-z][a-z-]*$ ]] || die "Indica el secreto: db, metadata-user, metadata-password, nvidia-api-key… (salida 'secrets')."
  read -r -s -p "Valor de discovery-data-agent/$ENV_NAME/$name (no se muestra): " value || true; echo >&2
  [ -n "$value" ] || die "Valor vacío: no se cambió nada."
  aws secretsmanager put-secret-value --secret-id "discovery-data-agent/$ENV_NAME/$name" --secret-string "$value" >/dev/null
  echo ">> Guardado. La tarea lo lee al arrancar: 'restart $ENV_NAME' para que lo tome." >&2
}

cmd_builder_run() {
  tf_init
  local family; family="$(out builder_task_definition)"
  [ -n "$family" ] || die "El Builder no está activo en este entorno (builder.enabled y un deploy hecho)."
  aws ecs run-task --cluster "$NAME" --task-definition "$family" --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$(out task_subnet_ids)],securityGroups=[$(out task_security_group)],assignPublicIp=$(out task_assign_public_ip)}" \
    --query 'tasks[0].taskArn' --output text
  echo ">> Lanzado. Seguimiento: bash deploy/aws/despliegue.sh logs $ENV_NAME builder" >&2
}

# Ruta que entiende el AWS CLI: en Git Bash es un .exe de Windows y no ve /tmp ni /dev/stdin.
native_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
state_bucket_exists() { aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; }

# Carga las claves de LLM (llm_api_key_envs) que aún no tengan valor, desde el entorno o el .env del repositorio.
load_llm_keys() {
  local env_file="${ENV_FILE:-../../.env}" pair secret var value tmp
  for pair in $(tf output -json llm_secrets | tr -d '{}" ' | tr ',' ' '); do
    secret="${pair%%:*}"; var="${pair#*:}"
    if aws secretsmanager get-secret-value --secret-id "discovery-data-agent/$ENV_NAME/$secret" >/dev/null 2>&1; then
      echo ">> $secret ya tiene valor" >&2; continue
    fi
    value="${!var:-}"
    if [ -z "$value" ] && [ -f "$env_file" ]; then
      value="$(sed -n "s/^$var=//p" "$env_file" | head -n 1 | tr -d '\r"')"
    fi
    [ -n "$value" ] || die "Falta $var: expórtala, ponla en $env_file o usa 'secret $ENV_NAME $secret'."
    tmp="$(mktemp)"; printf '%s' "$value" > "$tmp"
    aws secretsmanager put-secret-value --secret-id "discovery-data-agent/$ENV_NAME/$secret" \
      --secret-string "file://$(native_path "$tmp")" >/dev/null || { rm -f "$tmp"; die "No se pudo guardar $secret."; }
    rm -f "$tmp"
    echo ">> $secret cargado desde $var" >&2
  done
}

# Datos para entrar al entorno de pruebas con SQL Server en la tarea (sql_sidecar).
cmd_credentials() {
  local secret logins
  secret="$(out sql_logins_secret)"
  [ -n "$secret" ] || die "Este entorno no tiene SQL Server en la tarea (sql_sidecar)."
  logins="$(aws secretsmanager get-secret-value --secret-id "$secret" --query SecretString --output text)"
  cat >&2 <<EOF
>> Primer acceso (tras cada arranque de la tarea): entrar con autenticación SQL y registrar el servidor
     Servidor:   localhost,1433   (confiar en el certificado del servidor: sí)
     Código de instalación: $(aws secretsmanager get-secret-value --secret-id "discovery-data-agent/$ENV_NAME/setup-token" --query SecretString --output text)
   Luego Administración → Descubrir esquemas.
>> Usuarios
     dda_admin   $(printf '%s' "$logins" | sed -n 's/.*"admin":"\([^"]*\)".*/\1/p')   (administrador: las 5 bases)
     analista    $(printf '%s' "$logins" | sed -n 's/.*"analista":"\([^"]*\)".*/\1/p')   (consumidor: BancaCuentasDebito y BancaPrestamos)
EOF
}

cmd_up() {
  case "$(tfvar discovery_data_agent_env)" in qa|prod) die "'up' es para entornos de prueba; en qa y prod, paso a paso (README)." ;; esac
  if ! state_bucket_exists; then
    echo ">> Creando el bucket del estado ($BUCKET)" >&2
    (cd bootstrap && terraform init -input=false >/dev/null && terraform apply -input=false -var "region=$REGION" "$@")
  fi
  tf_init
  tf_apply "$@"
  load_llm_keys
  ALLOW_DIRTY=1 cmd_deploy "$@"
  echo ">> Listo: $(out url)"
  [ -z "$(out sql_logins_secret)" ] || cmd_credentials
  echo ">> Para no pagar más: bash deploy/aws/despliegue.sh teardown $ENV_NAME"
}

# Destruye el entorno y, si el bucket del estado no guarda ningún otro entorno, lo vacía (todas las versiones) y lo
# borra. Queda solo la clave KMS, programada para borrarse en 7 días (AWS no permite menos).
cmd_teardown() {
  case "$(tfvar discovery_data_agent_env)" in qa|prod) die "'teardown' es para entornos de prueba: usa 'destroy'." ;; esac
  if state_bucket_exists; then
    tf_init
    tf destroy -input=false "${TF_VARS[@]}" "$@"
  fi
  if state_bucket_exists; then
    local key="discovery-data-agent/$ENV_NAME/terraform.tfstate" others versions
    others="$(aws s3api list-objects-v2 --bucket "$BUCKET" --output text \
      --query "Contents[?Key!='$key' && !ends_with(Key, '.tflock')].Key")"
    if [ -n "$others" ] && [ "$others" != "None" ]; then
      echo ">> El bucket $BUCKET guarda otros entornos ($others): se conserva." >&2
    else
      echo ">> Borrando el bucket del estado $BUCKET" >&2
      versions="$(mktemp)"
      while :; do
        aws s3api list-object-versions --bucket "$BUCKET" --max-items 500 --output json \
          --query '{Objects: [Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId}, Quiet: `true`}' > "$versions"
        grep -q '"Key"' "$versions" || break
        aws s3api delete-objects --bucket "$BUCKET" --delete "file://$(native_path "$versions")" >/dev/null
      done
      rm -f "$versions"
      aws s3api delete-bucket --bucket "$BUCKET"
      rm -f bootstrap/terraform.tfstate bootstrap/terraform.tfstate.backup
    fi
  fi
  echo ">> Recursos con la etiqueta app=discovery-data-agent que siguen en $REGION (la clave KMS se borra sola):" >&2
  aws resourcegroupstaggingapi get-resources --tag-filters "Key=app,Values=discovery-data-agent" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n'
}

COMMAND="${1:-}"; ENV_NAME="${2:-}"
[ -n "$COMMAND" ] || usage 1
shift; [ $# -gt 0 ] && shift
cd "$HERE"

case "$COMMAND" in
  -h|--help|help) usage ;;
  validate)
    need terraform
    terraform fmt -check -recursive . || die "Formato: ejecuta 'terraform fmt -recursive deploy/aws'."
    tf init -input=false -backend=false >/dev/null
    tf validate
    tf test
    ;;
  bootstrap)
    [ -n "$ENV_NAME" ] || die "Indica la región: bootstrap us-east-1"
    need terraform; need aws
    (cd bootstrap && terraform init -input=false >/dev/null && terraform apply -input=false -var "region=$ENV_NAME" "$@")
    ;;
  up)          load_env; cmd_up "$@" ;;
  teardown)    load_env; cmd_teardown "$@" ;;
  start|stop)
    load_env
    aws ecs update-service --cluster "$NAME" --service "$NAME" --desired-count "$([ "$COMMAND" = start ] && echo 1 || echo 0)" \
      --query 'service.desiredCount' --output text >/dev/null
    tf_init; wait_stable
    ;;
  plan)        load_env; tf_init; tf plan -input=false "${TF_VARS[@]}" "$@" ;;
  apply)       load_env; tf_init; tf_apply "$@" ;;
  output)      load_env; tf_init; tf output "$@" ;;
  destroy)     load_env; tf_init; tf destroy -input=false "${TF_VARS[@]}" "$@" ;;
  deploy)      load_env; cmd_deploy "$@" ;;
  rollback)    load_env; cmd_rollback "$@" ;;
  secret)      load_env; cmd_secret "$@" ;;
  builder-run) load_env; cmd_builder_run ;;
  restart)
    load_env
    aws ecs update-service --cluster "$NAME" --service "$NAME" --force-new-deployment --query 'service.status' --output text
    tf_init; wait_stable
    ;;
  credentials) load_env; tf_init; cmd_credentials ;;
  setup-token)
    load_env
    aws secretsmanager get-secret-value --secret-id "discovery-data-agent/$ENV_NAME/setup-token" --query SecretString --output text
    ;;
  status)
    load_env; tf_init
    echo "Sitio:    $(out url)"
    echo "Etiqueta: $(out image_tag)"
    aws ecs describe-services --cluster "$NAME" --services "$NAME" --output table \
      --query 'services[0].{Estado:status,Deseadas:desiredCount,EnMarcha:runningCount,Despliegue:deployments[0].rolloutState,UltimoEvento:events[0].message}'
    ;;
  logs)        load_env; aws logs tail "/discovery-data-agent/$ENV_NAME/${1:-api}" --follow --since 30m ;;
  *)           echo "Comando desconocido: $COMMAND" >&2; usage 1 ;;
esac
