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

# Perfil económico del demo: sin endpoints de interfaz, tarea pública en Spot, horario y clave de NIM.
run "demo_economico" {
  command = plan
  variables {
    public_task      = true
    fargate_spot     = true
    schedule         = { enabled = true }
    models_yaml_file = "config/models.aws.yaml"
    llm_api_key_envs = ["NVIDIA_API_KEY"]
    image_tag        = "abc123def456"
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface) == 0 && length(aws_vpc_security_group_egress_rule.task_to_internet) == 1
    error_message = "Con public_task no hay endpoints de interfaz y la tarea sale por HTTPS a internet."
  }
  assert {
    condition     = aws_ecs_service.app[0].network_configuration[0].assign_public_ip
    error_message = "La tarea lleva IP pública (no hay NAT)."
  }
  assert {
    condition     = one(aws_ecs_service.app[0].capacity_provider_strategy).capacity_provider == "FARGATE_SPOT"
    error_message = "La tarea corre en Fargate Spot."
  }
  assert {
    condition     = length(aws_scheduler_schedule.service) == 2
    error_message = "Hay un horario de encendido y otro de apagado."
  }
  assert {
    condition     = contains([for s in local.api_secrets : s.name], "NVIDIA_API_KEY") && length(aws_secretsmanager_secret.llm) == 1
    error_message = "La clave de NIM es un secreto que solo recibe la API."
  }
}

run "qa_sin_atajos_de_coste" {
  command = plan
  variables {
    environment              = "qa"
    discovery_data_agent_env = "qa"
    demo                     = false
    alb_internal             = true
    alb_ingress_cidrs        = ["10.0.0.0/16"]
    domain_name              = "discovery-data-agent-qa.banco.local"
    certificate_arn          = "arn:aws:acm:us-east-1:111111111111:certificate/00000000-0000-0000-0000-000000000000"
    admins                   = ["admin_datos"]
    db_secret_enabled        = true
    fargate_spot             = true
  }
  expect_failures = [terraform_data.validaciones]
}

# El entorno demo completo: SQL Server Express en la tarea, Claude en Bedrock y perfiles de NIM y Anthropic.
run "demo_completo_en_aws" {
  command = plan
  variables {
    demo              = false
    public_task       = true
    fargate_spot      = true
    task_memory       = 4096
    sql_sidecar       = true
    db_secret_enabled = true
    admins            = ["dda_admin"]
    models_yaml_file  = "config/models.aws.yaml"
    bedrock_mantle    = true
    llm_api_key_envs  = ["NVIDIA_API_KEY", "ANTHROPIC_API_KEY"]
    image_tag         = "abc123def456"
  }

  assert {
    condition     = contains(keys(aws_ecr_repository.this), "sqlserver") && length(aws_secretsmanager_secret_version.db) == 1
    error_message = "Con sql_sidecar hay repositorio de la imagen de SQL Server y la cadena de la BD la escribe Terraform."
  }
  assert {
    condition     = [for c in local.app_containers : c.name] == ["sqlserver", "api", "api-eventos", "web"]
    error_message = "La tarea lleva SQL Server, la API, su puente de logs y la web."
  }
  assert {
    condition     = local.app_containers[1].dependsOn[0].containerName == "sqlserver"
    error_message = "La API espera a que SQL Server esté sano."
  }
  assert {
    condition     = strcontains(local.app_containers[1].command[2], "discovery-data-agent db migrate && exec uvicorn")
    error_message = "La API migra la BD DiscoveryDataAgent antes de arrancar."
  }
  assert {
    condition     = length(aws_iam_role_policy.bedrock_mantle) == 1 && length(aws_secretsmanager_secret.llm) == 2
    error_message = "La API puede llamar a Claude en Bedrock y recibe las claves de NIM y Anthropic."
  }
}

run "sql_sidecar_sin_memoria" {
  command = plan
  variables {
    demo              = false
    sql_sidecar       = true
    db_secret_enabled = true
    task_memory       = 2048
  }
  expect_failures = [terraform_data.validaciones]
}

# Los atajos del demo (salida a internet, claves de LLM de terceros) nunca junto a la red del banco.
run "demo_con_red_del_banco" {
  command = plan
  variables {
    public_task      = true
    llm_api_key_envs = ["NVIDIA_API_KEY"]
    sql_server_cidrs = ["10.20.30.0/24"]
  }
  expect_failures = [terraform_data.validaciones]
}

# Una pila llamada prod no acepta los atajos aunque la API diga dev.
run "prod_por_nombre" {
  command = plan
  variables {
    environment  = "prod"
    fargate_spot = true
  }
  expect_failures = [terraform_data.validaciones]
}
