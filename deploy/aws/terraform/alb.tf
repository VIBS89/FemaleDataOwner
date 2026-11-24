# Entrada: ALB con `/` a la web y `/mcp` a la API (CN-01, CN-04). Interno salvo en el entorno demo.
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "ALB de ConverData"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.name}-alb" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb" {
  for_each          = toset(var.alb_ingress_cidrs)
  security_group_id = aws_security_group.alb.id
  description       = "Usuarios"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = local.https ? 443 : 80
  to_port           = local.https ? 443 : 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_task" {
  for_each                     = { web = 3000, api = 8000 }
  security_group_id            = aws_security_group.alb.id
  description                  = "A ${each.key}"
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_lb" "this" {
  name                       = local.name
  internal                   = var.alb_internal
  load_balancer_type         = "application"
  subnets                    = var.alb_internal ? aws_subnet.private[*].id : aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  idle_timeout               = var.alb_idle_timeout
  drop_invalid_header_fields = true
  enable_deletion_protection = local.production

  dynamic "access_logs" {
    for_each = var.alb_access_logs_bucket == null ? [] : [var.alb_access_logs_bucket]
    content {
      bucket  = access_logs.value
      prefix  = local.name
      enabled = true
    }
  }

  depends_on = [aws_internet_gateway.this, terraform_data.validaciones]
}

resource "aws_lb_target_group" "this" {
  for_each = {
    web = { port = 3000, path = "/login", matcher = "200-399" }
    api = { port = 8000, path = "/health", matcher = "200" }
  }
  name                 = "${local.name}-${each.key}"
  vpc_id               = aws_vpc.this.id
  target_type          = "ip"
  protocol             = "HTTP"
  port                 = each.value.port
  deregistration_delay = 30

  health_check {
    path                = each.value.path
    matcher             = each.value.matcher
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# --- Certificado: el que se indique o, con una zona pública de Route 53, uno de ACM validado por DNS ---
resource "aws_acm_certificate" "this" {
  count             = var.route53_zone_id != null && var.certificate_arn == null ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for o in flatten(aws_acm_certificate.this[*].domain_validation_options) : o.domain_name => o
  }
  zone_id         = var.route53_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  count                   = length(aws_acm_certificate.this)
  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

resource "aws_route53_record" "site" {
  count   = var.route53_zone_id == null ? 0 : 1
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = false
  }
}

locals {
  certificate_arn = (
    var.certificate_arn != null ? var.certificate_arn :
    length(aws_acm_certificate_validation.this) > 0 ? aws_acm_certificate_validation.this[0].certificate_arn : null
  )
}

resource "aws_lb_listener" "this" {
  load_balancer_arn = aws_lb.this.arn
  port              = local.https ? 443 : 80
  protocol          = local.https ? "HTTPS" : "HTTP"
  ssl_policy        = local.https ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["web"].arn
  }
}

# El resto de la API no se publica: la web la alcanza por localhost dentro de la tarea.
resource "aws_lb_listener_rule" "mcp" {
  listener_arn = aws_lb_listener.this.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/mcp", "/mcp/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["api"].arn
  }
}
