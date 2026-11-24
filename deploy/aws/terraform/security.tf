# Clave KMS del entorno, repositorios ECR, secretos de servicio y roles IAM (CN-03).

# --- KMS: cifra logs, secretos, imágenes y el tema de alarmas ---
data "aws_iam_policy_document" "kms" {
  statement {
    sid       = "Cuenta"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "CloudWatchLogs"
    actions   = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:/discovery-data-agent/${var.environment}/*"]
    }
  }

  statement {
    sid       = "AlarmasYEventos"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com", "events.amazonaws.com"]
    }
  }
}

resource "aws_kms_key" "this" {
  description             = "DiscoveryDataAgent ${var.environment}"
  enable_key_rotation     = true
  deletion_window_in_days = local.production ? 30 : 7
  policy                  = data.aws_iam_policy_document.kms.json
}

resource "aws_kms_alias" "this" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.this.key_id
}

# --- ECR: etiquetas inmutables y análisis al subir ---
resource "aws_ecr_repository" "this" {
  for_each             = toset(["api", "web"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = !local.production

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.this.arn
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Conserva las 20 imagenes mas recientes"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

# --- Secretos de servicio (nunca logins de usuarios: CN-03 CA2) ---
# El código de instalación lo genera Terraform; los demás se crean vacíos y su valor se carga con
# `despliegue.sh secret <entorno> <nombre>`, para que no pase por el estado ni por el repositorio.
resource "random_password" "setup_token" {
  count   = var.demo ? 0 : 1
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "setup_token" {
  count                   = var.demo ? 0 : 1
  name                    = "discovery-data-agent/${var.environment}/setup-token"
  description             = "DISCOVERY_DATA_AGENT_SETUP_TOKEN: lo pide el registro del primer servidor del inventario"
  kms_key_id              = aws_kms_key.this.arn
  recovery_window_in_days = local.production ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "setup_token" {
  count         = var.demo ? 0 : 1
  secret_id     = aws_secretsmanager_secret.setup_token[0].id
  secret_string = random_password.setup_token[0].result
}

resource "aws_secretsmanager_secret" "db" {
  count                   = var.db_secret_enabled ? 1 : 0
  name                    = "discovery-data-agent/${var.environment}/db"
  description             = "DISCOVERY_DATA_AGENT_DB: cadena ODBC de la BD DiscoveryDataAgent"
  kms_key_id              = aws_kms_key.this.arn
  recovery_window_in_days = local.production ? 30 : 0
}

resource "aws_secretsmanager_secret" "metadata" {
  for_each                = var.builder.enabled ? toset(["metadata-user", "metadata-password"]) : toset([])
  name                    = "discovery-data-agent/${var.environment}/${each.key}"
  description             = "Login de metadatos del Builder (solo lo lee la tarea del Builder)"
  kms_key_id              = aws_kms_key.this.arn
  recovery_window_in_days = local.production ? 30 : 0
}

# --- Roles ---
data "aws_iam_policy_document" "assume_ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

locals {
  api_secret_arns = concat(aws_secretsmanager_secret.setup_token[*].arn, aws_secretsmanager_secret.db[*].arn)
  builder_secret_arns = concat(
    aws_secretsmanager_secret.db[*].arn, [for s in aws_secretsmanager_secret.metadata : s.arn]
  )
}

# Roles de ejecución: con ellos ECS descarga la imagen, escribe los logs e inyecta los secretos. Uno por tarea, para
# que la de la API no pueda recibir el login de metadatos (CN-03 CA3).
resource "aws_iam_role" "execution" {
  for_each           = toset(["api", "builder"])
  name               = "${local.name}-${each.key}-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  for_each   = aws_iam_role.execution
  role       = each.value.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  for_each = {
    api     = local.api_secret_arns
    builder = local.builder_secret_arns
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.this.arn]
  }

  dynamic "statement" {
    for_each = length(each.value) > 0 ? [1] : []
    content {
      actions   = ["secretsmanager:GetSecretValue"]
      resources = each.value
    }
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  for_each = aws_iam_role.execution
  name     = "secretos"
  role     = each.value.id
  policy   = data.aws_iam_policy_document.read_secrets[each.key].json
}

# Roles de tarea: lo que el código puede hacer en AWS. Solo invocar el modelo elegido, sin claves.
resource "aws_iam_role" "task" {
  for_each           = toset(["api", "builder"])
  name               = "${local.name}-${each.key}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

data "aws_iam_policy_document" "bedrock" {
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.bedrock_resource_arns
  }
}

resource "aws_iam_role_policy" "bedrock" {
  for_each = local.bedrock_enabled ? toset(var.builder.use_llm ? ["api", "builder"] : ["api"]) : toset([])
  name     = "bedrock"
  role     = aws_iam_role.task[each.key].id
  policy   = data.aws_iam_policy_document.bedrock.json
}

data "aws_iam_policy_document" "ecs_exec" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ecs_exec" {
  count  = var.enable_ecs_exec ? 1 : 0
  name   = "ecs-exec"
  role   = aws_iam_role.task["api"].id
  policy = data.aws_iam_policy_document.ecs_exec.json
}
