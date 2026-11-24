# Alarmas de CN-05. Umbrales y canal de aviso por confirmar con Seguridad y Operaciones; ninguna lleva contenido.
resource "aws_sns_topic" "alarms" {
  name              = "${local.name}-alarmas"
  kms_master_key_id = aws_kms_key.this.id
}

data "aws_iam_policy_document" "alarms_topic" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com", "events.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms_topic.json
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# Crítica: fallo de escritura de auditoría (las respuestas quedan bloqueadas, F11). Depende de que el evento
# `audit.write_failed` llegue al log (contenedor api-eventos; ver DT-37 y DT-58 en docs/wiki/deuda-tecnica.md).
resource "aws_cloudwatch_log_metric_filter" "audit_failed" {
  name           = "${local.name}-auditoria"
  log_group_name = aws_cloudwatch_log_group.this["api"].name
  pattern        = "{ $.event = \"audit.write_failed\" }"

  metric_transformation {
    namespace = "DiscoveryDataAgent/${var.environment}"
    name      = "AuditWriteFailed"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "audit_failed" {
  alarm_name          = "${local.name}-auditoria"
  alarm_description   = "Critica: fallo al escribir la auditoria"
  namespace           = "DiscoveryDataAgent/${var.environment}"
  metric_name         = "AuditWriteFailed"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.audit_failed]
}

# Crítica: los dos túneles de la VPN caídos.
resource "aws_cloudwatch_metric_alarm" "vpn" {
  count               = var.vpn == null ? 0 : 1
  alarm_name          = "${local.name}-vpn"
  alarm_description   = "Critica: VPN al banco caida"
  namespace           = "AWS/VPN"
  metric_name         = "TunnelState"
  dimensions          = { VpnId = aws_vpn_connection.this[0].id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# Crítica: destino del ALB no saludable.
resource "aws_cloudwatch_metric_alarm" "unhealthy" {
  for_each            = local.deployed ? aws_lb_target_group.this : {}
  alarm_name          = "${local.name}-${each.key}-no-saludable"
  alarm_description   = "Critica: ${each.key} no responde a la comprobacion del ALB"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix, TargetGroup = each.value.arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# Crítica: tarea detenida. También avisa en cada despliegue, que para la tarea anterior.
resource "aws_cloudwatch_event_rule" "task_stopped" {
  name        = "${local.name}-tarea-detenida"
  description = "La tarea web + API se detuvo"
  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.this.arn]
      lastStatus = ["STOPPED"]
      group      = ["service:${local.name}"]
    }
  })
}

# Alta: el Builder termina con error o no llega a arrancar. Que no se haya lanzado no se detecta aquí.
resource "aws_cloudwatch_event_rule" "builder_failed" {
  name        = "${local.name}-builder-fallido"
  description = "El Builder termino con error"
  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn        = [aws_ecs_cluster.this.arn]
      lastStatus        = ["STOPPED"]
      taskDefinitionArn = [{ prefix = "arn:${local.partition}:ecs:${var.region}:${local.account_id}:task-definition/${local.name}-builder:" }]
      "$or" = [
        { containers = { exitCode = [{ anything-but = 0 }] } },
        { stopCode = [{ anything-but = "EssentialContainerExited" }] },
      ]
    }
  })
}

resource "aws_cloudwatch_event_target" "to_alarms" {
  for_each = {
    tarea   = aws_cloudwatch_event_rule.task_stopped.name
    builder = aws_cloudwatch_event_rule.builder_failed.name
  }
  rule = each.value
  arn  = aws_sns_topic.alarms.arn
}

# Alta: 5xx del ALB por encima del 5 % durante 5 minutos.
resource "aws_cloudwatch_metric_alarm" "errors_5xx" {
  alarm_name          = "${local.name}-5xx"
  alarm_description   = "Alta: mas del 5 % de respuestas 5xx"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  evaluation_periods  = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "tasa"
    expression  = "IF(total > 0, 100 * (FILL(destino, 0) + FILL(alb, 0)) / total, 0)"
    label       = "Porcentaje de 5xx"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { total = "RequestCount", destino = "HTTPCode_Target_5XX_Count", alb = "HTTPCode_ELB_5XX_Count" }
    content {
      id = metric_query.key
      metric {
        namespace   = "AWS/ApplicationELB"
        metric_name = metric_query.value
        dimensions  = { LoadBalancer = aws_lb.this.arn_suffix }
        stat        = "Sum"
        period      = 60
      }
    }
  }
}

# Alta: p95 por encima de 10 s durante 15 minutos. Es el tiempo de respuesta de todo el ALB, no solo del
# descubrimiento: las respuestas en streaming lo alargan. El p95 propio de /discover está en /health/metrics.
resource "aws_cloudwatch_metric_alarm" "latency" {
  alarm_name          = "${local.name}-latencia"
  alarm_description   = "Alta: p95 de respuesta mayor que 10 s"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

# Alta: throttling o errores de Bedrock por encima del 5 % durante 5 minutos.
resource "aws_cloudwatch_metric_alarm" "bedrock" {
  count               = var.bedrock_model_id == null ? 0 : 1
  alarm_name          = "${local.name}-bedrock"
  alarm_description   = "Alta: throttling o errores de Bedrock"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  evaluation_periods  = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "tasa"
    expression  = "IF(total > 0, 100 * (FILL(limitadas, 0) + FILL(errores, 0)) / (total + FILL(limitadas, 0)), 0)"
    label       = "Porcentaje de invocaciones fallidas"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { total = "Invocations", limitadas = "InvocationThrottles", errores = "InvocationServerErrors" }
    content {
      id = metric_query.key
      metric {
        namespace   = "AWS/Bedrock"
        metric_name = metric_query.value
        dimensions  = { ModelId = var.bedrock_model_id }
        stat        = "Sum"
        period      = 60
      }
    }
  }
}

# Media: certificado del ALB a menos de 30 días de expirar.
resource "aws_cloudwatch_metric_alarm" "certificate" {
  count               = local.https ? 1 : 0
  alarm_name          = "${local.name}-certificado"
  alarm_description   = "Media: el certificado del ALB expira en menos de 30 dias"
  namespace           = "AWS/CertificateManager"
  metric_name         = "DaysToExpiry"
  dimensions          = { CertificateArn = local.certificate_arn }
  statistic           = "Minimum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "LessThanThreshold"
  threshold           = 30
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
