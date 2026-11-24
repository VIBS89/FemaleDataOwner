# Encendido y apagado programados de la tarea web + API (schedule.enabled; solo entornos de prueba). EventBridge
# Scheduler llama a ecs:UpdateService con 1 o 0 tareas: fuera de horario no se paga Fargate. A mano, en cualquier
# momento: `despliegue.sh start|stop <entorno>`.
locals {
  schedule_enabled = var.schedule.enabled && local.deployed
  schedule_actions = { encender = { cron = var.schedule.start, count = 1 }, apagar = { cron = var.schedule.stop, count = 0 } }
}

data "aws_iam_policy_document" "schedule" {
  statement {
    actions   = ["ecs:UpdateService"]
    resources = ["arn:${local.partition}:ecs:${var.region}:${local.account_id}:service/${local.name}/${local.name}"]
  }
}

resource "aws_iam_role" "schedule" {
  count              = local.schedule_enabled ? 1 : 0
  name               = "${local.name}-horario"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

resource "aws_iam_role_policy" "schedule" {
  count  = local.schedule_enabled ? 1 : 0
  name   = "encender-apagar"
  role   = aws_iam_role.schedule[0].id
  policy = data.aws_iam_policy_document.schedule.json
}

resource "aws_scheduler_schedule" "service" {
  for_each                     = local.schedule_enabled ? local.schedule_actions : {}
  name                         = "${local.name}-${each.key}"
  description                  = "${each.key} la tarea de DiscoveryDataAgent"
  schedule_expression          = each.value.cron
  schedule_expression_timezone = var.schedule.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ecs:updateService"
    role_arn = aws_iam_role.schedule[0].arn
    input = jsonencode({
      Cluster      = aws_ecs_cluster.this.name
      Service      = aws_ecs_service.app[0].name
      DesiredCount = each.value.count
    })
  }
}
