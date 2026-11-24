#!/usr/bin/env bash
# Despliegue de ConverData en AWS (CN-01). Guía completa: deploy/aws/README.md
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
  secret <entorno> <nombre> Carga el valor de un secreto: db, metadata-user o metadata-password. Lo pide sin mostrarlo.
  setup-token <entorno>     Muestra el código de instalación que pide el registro del primer servidor.
  builder-run <entorno>     Lanza ahora el Builder del catálogo, sin esperar a la hora programada.

Operación
  status <entorno>          Estado del servicio y dirección del sitio.
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
  BUCKET="converdata-tfstate-$ACCOUNT-$REGION"
  NAME="converdata-$ENV_NAME"
  echo ">> Entorno $ENV_NAME · cuenta $ACCOUNT · región $REGION" >&2
}

tf() { (cd terraform && terraform "$@"); }

tf_init() {
  tf init -input=false -reconfigure \
    -backend-config="bucket=$BUCKET" -backend-config="key=converdata/$ENV_NAME/terraform.tfstate" \
    -backend-config="region=$REGION" >/dev/null \
    || die "terraform init falló. ¿Se ejecutó 'bootstrap $REGION' en esta cuenta?"
}

tf_apply() { tf apply -input=false -var-file="envs/$ENV_NAME.tfvars" "$@"; }
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

cmd_deploy() {
  need docker; need git
  docker info >/dev/null 2>&1 || die "Docker no está en marcha."
  local tag dirty api web registry
  tag="$(git rev-parse --short=12 HEAD)"
  dirty="$(git status --porcelain)"
  if [ -n "$dirty" ]; then
    case "$(tfvar converdata_env)" in
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
    (cd ../.. && docker build --platform linux/amd64 --provenance=false -f api/Dockerfile -t "$api:$tag" .)
    docker push "$api:$tag"
  fi
  if image_exists "${web#*/}" "$tag"; then echo ">> web:$tag ya está publicada" >&2; else
    (cd ../.. && docker build --platform linux/amd64 --provenance=false -t "$web:$tag" web)
    docker push "$web:$tag"
  fi
  release "$tag" "$@"
}

cmd_rollback() {
  local tag="${1:-}"; [ -n "$tag" ] || die "Indica la etiqueta: rollback $ENV_NAME <etiqueta>"; shift
  tf_init
  for repo in api web; do
    image_exists "$NAME/$repo" "$tag" || die "La etiqueta $tag no está en el repositorio $NAME/$repo."
  done
  release "$tag" "$@"
}

cmd_secret() {
  local name="${1:-}" value
  case "$name" in db|metadata-user|metadata-password) ;; *) die "Secreto desconocido: usa db, metadata-user o metadata-password." ;; esac
  read -r -s -p "Valor de converdata/$ENV_NAME/$name (no se muestra): " value; echo >&2
  [ -n "$value" ] || die "Valor vacío: no se cambió nada."
  aws secretsmanager put-secret-value --secret-id "converdata/$ENV_NAME/$name" --secret-string "$value" >/dev/null
  echo ">> Guardado. La tarea lo lee al arrancar: 'restart $ENV_NAME' para que lo tome." >&2
}

cmd_builder_run() {
  tf_init
  local family; family="$(out builder_task_definition)"
  [ -n "$family" ] || die "El Builder no está activo en este entorno (builder.enabled y un deploy hecho)."
  aws ecs run-task --cluster "$NAME" --task-definition "$family" --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$(out task_subnet_ids)],securityGroups=[$(out task_security_group)],assignPublicIp=DISABLED}" \
    --query 'tasks[0].taskArn' --output text
  echo ">> Lanzado. Seguimiento: bash deploy/aws/despliegue.sh logs $ENV_NAME builder" >&2
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
  plan)        load_env; tf_init; tf plan -input=false -var-file="envs/$ENV_NAME.tfvars" "$@" ;;
  apply)       load_env; tf_init; tf_apply "$@" ;;
  output)      load_env; tf_init; tf output "$@" ;;
  destroy)     load_env; tf_init; tf destroy -input=false -var-file="envs/$ENV_NAME.tfvars" "$@" ;;
  deploy)      load_env; cmd_deploy "$@" ;;
  rollback)    load_env; cmd_rollback "$@" ;;
  secret)      load_env; cmd_secret "$@" ;;
  builder-run) load_env; cmd_builder_run ;;
  restart)
    load_env
    aws ecs update-service --cluster "$NAME" --service "$NAME" --force-new-deployment --query 'service.status' --output text
    tf_init; wait_stable
    ;;
  setup-token)
    load_env
    aws secretsmanager get-secret-value --secret-id "converdata/$ENV_NAME/setup-token" --query SecretString --output text
    ;;
  status)
    load_env; tf_init
    echo "Sitio:    $(out url)"
    echo "Etiqueta: $(out image_tag)"
    aws ecs describe-services --cluster "$NAME" --services "$NAME" --output table \
      --query 'services[0].{Estado:status,Deseadas:desiredCount,EnMarcha:runningCount,Despliegue:deployments[0].rolloutState,UltimoEvento:events[0].message}'
    ;;
  logs)        load_env; aws logs tail "/converdata/$ENV_NAME/${1:-api}" --follow --since 30m ;;
  *)           echo "Comando desconocido: $COMMAND" >&2; usage 1 ;;
esac
