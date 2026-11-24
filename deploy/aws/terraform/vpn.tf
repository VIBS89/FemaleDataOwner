# Lado AWS de la Site-to-Site VPN al banco. El lado on-premise y las reglas del firewall (1433 solo desde las
# subredes de la tarea) los configura Redes con los datos de `terraform output vpn` (CN-01 CA1 los excluye del IaC).
resource "aws_vpn_gateway" "this" {
  count  = var.vpn == null ? 0 : 1
  vpc_id = aws_vpc.this.id
  tags   = { Name = local.name }
}

resource "aws_customer_gateway" "this" {
  count      = var.vpn == null ? 0 : 1
  type       = "ipsec.1"
  ip_address = var.vpn.customer_gateway_ip
  bgp_asn    = var.vpn.bgp_asn
  tags       = { Name = "${local.name}-banco" }
}

resource "aws_vpn_connection" "this" {
  count               = var.vpn == null ? 0 : 1
  type                = "ipsec.1"
  vpn_gateway_id      = aws_vpn_gateway.this[0].id
  customer_gateway_id = aws_customer_gateway.this[0].id
  static_routes_only  = length(var.vpn.static_routes) > 0
  tags                = { Name = local.name }
}

resource "aws_vpn_connection_route" "this" {
  for_each               = toset(var.vpn == null ? [] : var.vpn.static_routes)
  vpn_connection_id      = aws_vpn_connection.this[0].id
  destination_cidr_block = each.value
}

resource "aws_vpn_gateway_route_propagation" "private" {
  count          = var.vpn == null ? 0 : 1
  vpn_gateway_id = aws_vpn_gateway.this[0].id
  route_table_id = aws_route_table.private.id
}

# --- DNS del banco: sin él la tarea no resuelve sqlqa.banco.local y el TLS de SQL Server no se puede validar ---
resource "aws_security_group" "resolver" {
  count       = var.onprem_dns == null ? 0 : 1
  name_prefix = "${local.name}-dns-"
  description = "Reenvio de DNS al banco"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.name}-dns" }

  dynamic "egress" {
    for_each = ["tcp", "udp"]
    content {
      description = "DNS on-premise"
      protocol    = egress.value
      from_port   = 53
      to_port     = 53
      cidr_blocks = [for ip in var.onprem_dns.target_ips : "${ip}/32"]
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_resolver_endpoint" "outbound" {
  count              = var.onprem_dns == null ? 0 : 1
  name               = "${local.name}-salida"
  direction          = "OUTBOUND"
  security_group_ids = [aws_security_group.resolver[0].id]

  dynamic "ip_address" {
    for_each = aws_subnet.private[*].id
    content {
      subnet_id = ip_address.value
    }
  }
}

resource "aws_route53_resolver_rule" "onprem" {
  for_each             = toset(var.onprem_dns == null ? [] : var.onprem_dns.domains)
  name                 = "${local.name}-${replace(each.value, ".", "-")}"
  domain_name          = each.value
  rule_type            = "FORWARD"
  resolver_endpoint_id = aws_route53_resolver_endpoint.outbound[0].id

  dynamic "target_ip" {
    for_each = var.onprem_dns.target_ips
    content {
      ip = target_ip.value
    }
  }
}

resource "aws_route53_resolver_rule_association" "onprem" {
  for_each         = aws_route53_resolver_rule.onprem
  resolver_rule_id = each.value.id
  vpc_id           = aws_vpc.this.id
}
