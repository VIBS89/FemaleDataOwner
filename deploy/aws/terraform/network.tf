# VPC con subredes privadas sin ruta a internet (CN-01, CN-06 CA4). No hay NAT: la tarea sale solo por los VPC
# endpoints y por la VPN. Las subredes públicas existen únicamente con alb_internal = false (entorno demo) y solo
# alojan el ALB.
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id # sin reglas: nadie usa el grupo por defecto
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 2, count.index)
  tags              = { Name = "${local.name}-privada-${count.index + 1}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-privada" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# --- Solo demo: subredes públicas para el ALB ---
resource "aws_subnet" "public" {
  count             = var.alb_internal ? 0 : 2
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 3, 4 + count.index)
  tags              = { Name = "${local.name}-publica-${count.index + 1}" }
}

resource "aws_internet_gateway" "this" {
  count  = var.alb_internal ? 0 : 1
  vpc_id = aws_vpc.this.id
  tags   = { Name = local.name }
}

resource "aws_route_table" "public" {
  count  = var.alb_internal ? 0 : 1
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-publica" }

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this[0].id
  }
}

resource "aws_route_table_association" "public" {
  count          = var.alb_internal ? 0 : 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# --- VPC endpoints: lo único que la tarea alcanza de AWS ---
locals {
  interface_endpoints = toset(concat(
    ["ecr.api", "ecr.dkr", "logs", "secretsmanager"],
    local.bedrock_enabled ? ["bedrock-runtime"] : [],
    var.enable_ecs_exec ? ["ssmmessages"] : [],
  ))
}

resource "aws_security_group" "endpoints" {
  name_prefix = "${local.name}-endpoints-"
  description = "VPC endpoints de interfaz"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.name}-endpoints" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_from_task" {
  security_group_id            = aws_security_group.endpoints.id
  description                  = "HTTPS desde las tareas"
  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_endpoints
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  tags                = { Name = "${local.name}-${each.key}" }
}

# ECR guarda las capas de las imágenes en S3: endpoint de puerta de enlace, sin coste.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${local.name}-s3" }
}

# --- Grupo de seguridad de las tareas (web + API y Builder) ---
resource "aws_security_group" "task" {
  name_prefix = "${local.name}-task-"
  description = "Tareas de DiscoveryDataAgent"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.name}-task" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "task_from_alb" {
  for_each                     = { web = 3000, api = 8000 }
  security_group_id            = aws_security_group.task.id
  description                  = "ALB a ${each.key}"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_vpc_security_group_egress_rule" "task_to_endpoints" {
  security_group_id            = aws_security_group.task.id
  description                  = "VPC endpoints"
  referenced_security_group_id = aws_security_group.endpoints.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "task_to_s3" {
  security_group_id = aws_security_group.task.id
  description       = "Capas de ECR en S3"
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "task_to_sql" {
  for_each          = toset(var.sql_server_cidrs)
  security_group_id = aws_security_group.task.id
  description       = "SQL Server on-premise por la VPN"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 1433
  to_port           = 1433
}
