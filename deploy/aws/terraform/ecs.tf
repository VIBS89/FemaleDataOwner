# Una tarea de Fargate con la web y la API (CN-01). Una sola: el SessionVault vive en la memoria del proceso.
resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = local.production ? "enabled" : "disabled"
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each          = toset(["api", "web", "builder"])
  name              = "/discovery-data-agent/${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.this.arn
}

locals {
  log_configuration = {
    for name, prefix in { api = "api", eventos = "eventos", web = "web", builder = "builder" } : name => {
      logDriver               = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this[name == "eventos" ? "api" : name].name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = prefix
      }
    }
  }

  api_env = merge(
    {
      DISCOVERY_DATA_AGENT_ENV                = var.discovery_data_agent_env
      DISCOVERY_DATA_AGENT_DEMO               = var.demo ? "1" : "0"
      DISCOVERY_DATA_AGENT_DATA_ROOT          = "/app/data/catalog"
      DISCOVERY_DATA_AGENT_INVENTORY          = "/app/data/inventory.yaml"
      DISCOVERY_DATA_AGENT_AUDIT_DIR          = "/app/data/audit"
      DISCOVERY_DATA_AGENT_CURATION_DIR       = "/app/data/curation"
      DISCOVERY_DATA_AGENT_LOG_DIR            = "/app/data/logs"
      DISCOVERY_DATA_AGENT_EVENT_LOG          = "0"
      DISCOVERY_DATA_AGENT_ALLOW_WINDOWS_AUTH = "0"
      DISCOVERY_DATA_AGENT_COOKIE_SECURE      = local.https ? "1" : "0"
      DISCOVERY_DATA_AGENT_ADMINS             = join(",", var.admins)
      DISCOVERY_DATA_AGENT_ADMINS_ONLY        = local.production ? "1" : "0"
      DISCOVERY_DATA_AGENT_CORS_ORIGINS       = local.public_url
      DISCOVERY_DATA_AGENT_PUBLIC_URL         = local.public_url
      DISCOVERY_DATA_AGENT_MCP_HOSTS          = "${local.host},${local.host}:*"
      # El ALB añade la dirección del cliente al final de X-Forwarded-For: de ahí sale el origen para el bloqueo de login.
      DISCOVERY_DATA_AGENT_TRUST_PROXY = "1"
    },
    local.models_yaml == null ? {} : {
      DISCOVERY_DATA_AGENT_MODELS      = "/tmp/models.yaml"
      DISCOVERY_DATA_AGENT_MODELS_YAML = local.models_yaml
    },
    var.extra_api_env,
  )

  api_secrets = concat(
    [for s in aws_secretsmanager_secret.setup_token : { name = "DISCOVERY_DATA_AGENT_SETUP_TOKEN", valueFrom = s.arn }],
    [for s in aws_secretsmanager_secret.db : { name = "DISCOVERY_DATA_AGENT_DB", valueFrom = s.arn }],
  )

  data_mount = [{ sourceVolume = "data", containerPath = "/app/data", readOnly = false }]
}

resource "aws_ecs_task_definition" "app" {
  count                    = local.deployed ? 1 : 0
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.task["api"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  # Disco efímero de la tarea, no persistente (CN-06): desaparece al parar. Con DISCOVERY_DATA_AGENT_DB solo lleva los logs.
  volume {
    name = "data"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.api_image
      essential = true
      # Sin models.yaml vale el CMD de la imagen; con él, el arranque lo escribe antes de lanzar el mismo uvicorn.
      command          = local.models_yaml == null ? split(" ", trimprefix(local.uvicorn, "exec ")) : ["sh", "-c", "${local.write_models} && ${local.uvicorn}"]
      portMappings     = [{ containerPort = 8000, protocol = "tcp" }]
      environment      = [for k, v in local.api_env : { name = k, value = v }]
      secrets          = local.api_secrets
      mountPoints      = local.data_mount
      linuxParameters  = { initProcessEnabled = true }
      logConfiguration = local.log_configuration["api"]
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    },
    {
      # Puente hasta que la API escriba sus logs en la salida estándar (CN-01 §Dependencias, punto 2): hoy van al
      # archivo de DISCOVERY_DATA_AGENT_LOG_DIR, y este contenedor los lleva a CloudWatch. Se quita con ese cambio de código.
      name             = "api-eventos"
      image            = local.api_image
      essential        = false
      command          = ["sh", "-c", "mkdir -p /app/data/logs && touch /app/data/logs/discovery-data-agent.log && exec tail -n +1 -F /app/data/logs/discovery-data-agent.log"]
      mountPoints      = local.data_mount
      logConfiguration = local.log_configuration["eventos"]
    },
    {
      name         = "web"
      image        = local.web_image
      essential    = true
      portMappings = [{ containerPort = 3000, protocol = "tcp" }]
      environment = [
        { name = "API_URL", value = "http://localhost:8000" },
        # Fargate pone HOSTNAME al nombre de la tarea y Next.js escucharía solo ahí.
        { name = "HOSTNAME", value = "0.0.0.0" },
        { name = "TRUST_FORWARDED_FOR", value = "1" },
      ]
      dependsOn        = [{ containerName = "api", condition = "HEALTHY" }]
      logConfiguration = local.log_configuration["web"]
    },
  ])
}

resource "aws_ecs_service" "app" {
  count                             = local.deployed ? 1 : 0
  name                              = local.name
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.app[0].arn
  launch_type                       = "FARGATE"
  platform_version                  = "LATEST"
  desired_count                     = 1
  enable_execute_command            = var.enable_ecs_exec
  availability_zone_rebalancing     = "DISABLED"
  health_check_grace_period_seconds = 120

  # Nunca dos tareas a la vez (dos SessionVault): cada despliegue para la tarea vieja y luego arranca la nueva.
  # Hay un corte de alrededor de un minuto y los usuarios vuelven a iniciar sesión.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = { web = 3000, api = 8000 }
    content {
      target_group_arn = aws_lb_target_group.this[load_balancer.key].arn
      container_name   = load_balancer.key
      container_port   = load_balancer.value
    }
  }

  depends_on = [aws_lb_listener_rule.mcp, aws_vpc_endpoint.interface, aws_vpc_endpoint.s3]
}

# --- Builder: la misma imagen ejecutando `discovery-data-agent catalog build --db`; corre y termina (CN-02) ---
locals {
  builder_command = "discovery-data-agent catalog build --db${var.builder.use_llm ? " --models /tmp/models.yaml" : ""}"
  builder_env = merge(
    {
      DISCOVERY_DATA_AGENT_ENV           = var.discovery_data_agent_env
      DISCOVERY_DATA_AGENT_BUILDER_HOSTS = join(",", var.builder.hosts)
    },
    var.builder.use_llm && local.models_yaml != null ? { DISCOVERY_DATA_AGENT_MODELS_YAML = local.models_yaml } : {},
  )
}

resource "aws_ecs_task_definition" "builder" {
  count                    = local.builder_enabled ? 1 : 0
  family                   = "${local.name}-builder"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.builder.cpu
  memory                   = var.builder.memory
  execution_role_arn       = aws_iam_role.execution["builder"].arn
  task_role_arn            = aws_iam_role.task["builder"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "builder"
    image     = local.api_image
    essential = true
    command = (var.builder.use_llm
      ? ["sh", "-c", "${local.write_models} && exec ${local.builder_command}"]
      : split(" ", local.builder_command)
    )
    environment = [for k, v in local.builder_env : { name = k, value = v }]
    secrets = [
      { name = "DISCOVERY_DATA_AGENT_DB", valueFrom = aws_secretsmanager_secret.db[0].arn },
      { name = var.builder.metadata_user_env, valueFrom = aws_secretsmanager_secret.metadata["metadata-user"].arn },
      { name = var.builder.metadata_password_env, valueFrom = aws_secretsmanager_secret.metadata["metadata-password"].arn },
    ]
    logConfiguration = local.log_configuration["builder"]
  }])
}

data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["ecs:RunTask"]
    resources = ["arn:${local.partition}:ecs:${var.region}:${local.account_id}:task-definition/${local.name}-builder:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }

  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution["builder"].arn, aws_iam_role.task["builder"].arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  count              = var.builder.enabled ? 1 : 0
  name               = "${local.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

resource "aws_iam_role_policy" "scheduler" {
  count  = var.builder.enabled ? 1 : 0
  name   = "run-builder"
  role   = aws_iam_role.scheduler[0].id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "builder" {
  count                        = local.builder_enabled ? 1 : 0
  name                         = "${local.name}-builder"
  description                  = "Refresco del catalogo de DiscoveryDataAgent"
  schedule_expression          = var.builder.schedule
  schedule_expression_timezone = var.builder.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler[0].arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.builder[0].arn
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.task.id]
        assign_public_ip = false
      }
    }

    retry_policy {
      maximum_retry_attempts = 0 # un Builder que falla no se repite solo: dispara la alarma
    }
  }
}
