# Planes de los dos perfiles con el proveedor simulado: no necesitan cuenta de AWS ni crean nada.
#   terraform init -backend=false && terraform test
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b", "us-east-1c"]
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "111111111111"
    }
  }
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  environment              = "demo"
  discovery_data_agent_env = "dev"
  demo                     = true
  alb_internal             = false
  alb_ingress_cidrs        = ["198.51.100.7/32"]
}

run "demo_sin_imagenes" {
  command = plan

  assert {
    condition     = length(aws_ecs_service.app) == 0
    error_message = "Sin imágenes publicadas no debe existir el servicio."
  }
  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_vpn_connection.this) == 0
    error_message = "El demo lleva subredes públicas para el ALB y ninguna VPN."
  }
  assert {
    condition     = length(aws_secretsmanager_secret.db) == 0 && length(aws_secretsmanager_secret.setup_token) == 0
    error_message = "El demo no crea secretos."
  }
}

run "demo_abierto_a_internet" {
  command = plan
  variables {
    alb_ingress_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.alb_ingress_cidrs]
}

run "demo_sin_redes" {
  command = plan
  variables {
    alb_ingress_cidrs = []
  }
  expect_failures = [terraform_data.validaciones]
}

run "qa_completo" {
  command = plan
  variables {
    environment              = "qa"
    discovery_data_agent_env = "qa"
    demo                     = false
    alb_internal             = true
    alb_ingress_cidrs        = ["10.0.0.0/16"]
    sql_server_cidrs         = ["10.20.30.0/24"]
    vpn                      = { customer_gateway_ip = "203.0.113.10", static_routes = ["10.0.0.0/16"] }
    onprem_dns               = { domains = ["banco.local"], target_ips = ["10.0.0.2", "10.0.0.3"] }
    domain_name              = "discovery-data-agent-qa.banco.local"
    certificate_arn          = "arn:aws:acm:us-east-1:111111111111:certificate/00000000-0000-0000-0000-000000000000"
    admins                   = ["admin_datos"]
    db_secret_enabled        = true
    models_yaml_file         = "config/models.bedrock.example.yaml"
    bedrock_resource_arns    = ["arn:aws:bedrock:us-east-1:111111111111:inference-profile/ejemplo"]
    bedrock_model_id         = "ejemplo"
    builder                  = { enabled = true, hosts = [".banco.local"] }
    alarm_email              = "operaciones@example.com"
  }

  assert {
    condition     = length(aws_subnet.public) == 0 && length(aws_internet_gateway.this) == 0
    error_message = "En qa nada es público (CN-01 CA2)."
  }
  assert {
    condition     = aws_lb.this.internal && aws_lb_listener.this.protocol == "HTTPS"
    error_message = "En qa el ALB es interno y solo HTTPS."
  }
  assert {
    condition     = contains(keys(aws_vpc_endpoint.interface), "bedrock-runtime")
    error_message = "Bedrock se llama por su VPC endpoint."
  }
  assert {
    condition     = length(aws_secretsmanager_secret.metadata) == 2
    error_message = "El Builder necesita los dos secretos del login de metadatos."
  }
}

run "qa_sin_https" {
  command = plan
  variables {
    environment              = "qa"
    discovery_data_agent_env = "qa"
    demo                     = false
    alb_internal             = true
    alb_ingress_cidrs        = ["10.0.0.0/16"]
    admins                   = ["admin_datos"]
    db_secret_enabled        = true
  }
  expect_failures = [terraform_data.validaciones]
}

# Con una etiqueta publicada aparecen la tarea, el servicio y el Builder programado.
run "qa_desplegado" {
  command = plan
  variables {
    environment              = "qa"
    discovery_data_agent_env = "qa"
    demo                     = false
    alb_internal             = true
    alb_ingress_cidrs        = ["10.0.0.0/16"]
    sql_server_cidrs         = ["10.20.30.0/24"]
    domain_name              = "discovery-data-agent-qa.banco.local"
    certificate_arn          = "arn:aws:acm:us-east-1:111111111111:certificate/00000000-0000-0000-0000-000000000000"
    admins                   = ["admin_datos"]
    db_secret_enabled        = true
    models_yaml_file         = "config/models.bedrock.example.yaml"
    bedrock_resource_arns    = ["arn:aws:bedrock:us-east-1:111111111111:inference-profile/ejemplo"]
    builder                  = { enabled = true, hosts = [".banco.local"] }
    image_tag                = "abc123def456"
  }

  assert {
    condition     = aws_ecs_service.app[0].desired_count == 1 && aws_ecs_service.app[0].deployment_maximum_percent == 100
    error_message = "Una sola tarea, y nunca dos a la vez durante un despliegue."
  }
  assert {
    condition     = [for s in local.api_secrets : s.name] == ["DISCOVERY_DATA_AGENT_SETUP_TOKEN", "DISCOVERY_DATA_AGENT_DB"]
    error_message = "La tarea de la API recibe solo sus secretos, no el login de metadatos (CN-03 CA3)."
  }
  assert {
    condition     = local.builder_command == "discovery-data-agent catalog build --db"
    error_message = "El Builder ejecuta discovery-data-agent catalog build --db."
  }
  assert {
    condition     = length(aws_scheduler_schedule.builder) == 1
    error_message = "El Builder queda programado."
  }
}
