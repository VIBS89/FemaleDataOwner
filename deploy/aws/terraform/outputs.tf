output "url" {
  description = "Dirección del sitio"
  value       = local.public_url
}

output "alb_dns_name" {
  description = "Nombre DNS del ALB: a él apunta el registro interno de domain_name"
  value       = aws_lb.this.dns_name
}

output "image_tag" {
  description = "Etiqueta desplegada (none = todavía sin imágenes)"
  value       = local.image_tag
}

output "image_tag_parameter" {
  value = aws_ssm_parameter.image_tag.name
}

output "ecr_api" {
  value = aws_ecr_repository.this["api"].repository_url
}

output "ecr_web" {
  value = aws_ecr_repository.this["web"].repository_url
}

output "ecr_sqlserver" {
  description = "Repositorio de la imagen de SQL Server Express (vacío sin sql_sidecar)"
  value       = var.sql_sidecar ? aws_ecr_repository.this["sqlserver"].repository_url : ""
}

output "sql_logins_secret" {
  description = "Secreto con las contraseñas de dda_admin y analista: `despliegue.sh credentials <entorno>`"
  value       = var.sql_sidecar ? aws_secretsmanager_secret.sql[0].name : ""
}

output "cluster" {
  value = aws_ecs_cluster.this.name
}

output "service" {
  value = local.name
}

output "builder_task_definition" {
  value = local.builder_enabled ? aws_ecs_task_definition.builder[0].family : ""
}

output "task_subnets" {
  description = "Subredes de las tareas: el firewall del banco abre el 1433 solo a sus rangos"
  value       = { for s in aws_subnet.private : s.id => s.cidr_block }
}

output "task_subnet_ids" {
  value = join(",", local.task_subnet_ids)
}

output "task_assign_public_ip" {
  description = "ENABLED con public_task (demo): lo usa `despliegue.sh builder-run`"
  value       = var.public_task ? "ENABLED" : "DISABLED"
}

output "task_security_group" {
  value = aws_security_group.task.id
}

output "secrets" {
  description = "Secretos cuyo valor se carga con `despliegue.sh secret`"
  value = concat(
    [for s in aws_secretsmanager_secret.db : s.name],
    [for s in aws_secretsmanager_secret.metadata : s.name],
    [for s in aws_secretsmanager_secret.llm : s.name],
  )
}

output "vpn" {
  description = "Datos para que Redes configure el lado on-premise. Las claves precompartidas: `aws ec2 describe-vpn-connections`."
  value = var.vpn == null ? null : {
    id              = aws_vpn_connection.this[0].id
    tunnel1_address = aws_vpn_connection.this[0].tunnel1_address
    tunnel2_address = aws_vpn_connection.this[0].tunnel2_address
    tunnel1_cidr    = aws_vpn_connection.this[0].tunnel1_inside_cidr
    tunnel2_cidr    = aws_vpn_connection.this[0].tunnel2_inside_cidr
    amazon_side_asn = aws_vpn_gateway.this[0].amazon_side_asn
    vpc_cidr        = var.vpc_cidr
  }
}

output "alarms_topic" {
  value = aws_sns_topic.alarms.arn
}
