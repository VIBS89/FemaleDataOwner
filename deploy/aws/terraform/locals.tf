locals {
  name       = "converdata-${var.environment}"
  production = contains(["qa", "prod"], var.converdata_env)
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)

  https      = var.certificate_arn != null || var.route53_zone_id != null
  host       = coalesce(var.domain_name, aws_lb.this.dns_name)
  public_url = "${local.https ? "https" : "http"}://${local.host}"

  # La etiqueta desplegada la escribe `despliegue.sh deploy` en el parámetro; "none" = todavía no hay imágenes.
  image_tag = coalesce(var.image_tag, nonsensitive(aws_ssm_parameter.image_tag.value))
  deployed  = local.image_tag != "none"
  api_image = "${aws_ecr_repository.this["api"].repository_url}:${local.image_tag}"
  web_image = "${aws_ecr_repository.this["web"].repository_url}:${local.image_tag}"

  models_yaml     = var.models_yaml_file == null ? null : file("${path.module}/${var.models_yaml_file}")
  bedrock_enabled = length(var.bedrock_resource_arns) > 0
  builder_enabled = var.builder.enabled && local.deployed

  uvicorn = "exec uvicorn converdata_api.main:app --app-dir api --host 0.0.0.0 --port 8000 --workers 1"
  # El models.yaml no va en la imagen: llega como variable y el arranque lo escribe en /tmp.
  write_models = "printf '%s' \"$CONVERDATA_MODELS_YAML\" > /tmp/models.yaml"
}

# Etiqueta de las imágenes en uso. Terraform solo la crea; su valor lo mueve cada despliegue.
resource "aws_ssm_parameter" "image_tag" {
  name        = "${local.name}-image-tag"
  description = "Etiqueta de las imágenes api y web desplegadas (la escribe despliegue.sh)"
  type        = "String"
  value       = "none"

  lifecycle {
    ignore_changes = [value]
  }
}

# Comprobaciones que dan un mensaje claro antes de crear nada.
resource "terraform_data" "validaciones" {
  lifecycle {
    precondition {
      condition     = length(var.alb_ingress_cidrs) > 0
      error_message = "alb_ingress_cidrs está vacío: indica las redes que pueden abrir el sitio."
    }
    precondition {
      condition     = !local.production || (local.https && var.alb_internal && !var.demo)
      error_message = "Con converdata_env qa o prod: HTTPS (certificate_arn), ALB interno y sin modo demo (CN-01)."
    }
    precondition {
      condition     = !local.production || (var.db_secret_enabled && length(var.admins) > 0)
      error_message = "Con converdata_env qa o prod: db_secret_enabled = true y admins con al menos un login."
    }
    precondition {
      condition     = !local.https || var.domain_name != null
      error_message = "Con HTTPS hace falta domain_name: el nombre del certificado."
    }
    precondition {
      condition     = !var.builder.enabled || (var.db_secret_enabled && length(var.builder.hosts) > 0)
      error_message = "El Builder necesita db_secret_enabled = true y builder.hosts (CONVERDATA_BUILDER_HOSTS)."
    }
    precondition {
      condition     = !local.bedrock_enabled || var.models_yaml_file != null
      error_message = "bedrock_resource_arns sin models_yaml_file: la API no usaría el modelo."
    }
  }
}
