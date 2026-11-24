# --- Entorno ---
variable "environment" {
  description = "Nombre de la pila: demo, qa, prod. Va en los nombres de los recursos y en la etiqueta env."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,11}$", var.environment))
    error_message = "Entre 2 y 12 caracteres, minúsculas y dígitos (p. ej. demo, qa, prod)."
  }
}

variable "discovery_data_agent_env" {
  description = "DISCOVERY_DATA_AGENT_ENV de la API. Con qa o prod la API no arranca con ajustes inseguros (docs/calidad-bancaria.md §4)."
  type        = string
  validation {
    condition     = contains(["dev", "qa", "prod"], var.discovery_data_agent_env)
    error_message = "dev, qa o prod."
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "demo" {
  description = "DISCOVERY_DATA_AGENT_DEMO=1: servidores simulados con metadatos de prueba (usuarios demo/analista). Nunca con qa ni prod."
  type        = bool
  default     = false
}

# --- Red ---
variable "vpc_cidr" {
  description = "Rango de la VPC (/24 o mayor). No debe solaparse con las redes del banco que viajan por la VPN."
  type        = string
  default     = "10.80.0.0/24"
}

variable "alb_internal" {
  description = "true: ALB interno, sin nada público (CN-01). false solo para el entorno demo: ALB público restringido a alb_ingress_cidrs."
  type        = bool
  default     = true
}

variable "alb_ingress_cidrs" {
  description = "Redes que pueden llegar al ALB: las de la red corporativa (por la VPN) o, en demo, las IP públicas del equipo."
  type        = list(string)
  validation {
    condition     = !contains(var.alb_ingress_cidrs, "0.0.0.0/0")
    error_message = "No se abre el ALB a todo internet: lista las redes concretas."
  }
}

variable "sql_server_cidrs" {
  description = "Redes on-premise de los SQL Server (datos y BD DiscoveryDataAgent). La tarea solo puede salir al 1433 de estas redes."
  type        = list(string)
  default     = []
}

variable "vpn" {
  description = "Site-to-Site VPN al banco (lado AWS). null = sin VPN. static_routes vacío = BGP."
  type = object({
    customer_gateway_ip = string
    bgp_asn             = optional(number, 65000)
    static_routes       = optional(list(string), [])
  })
  default = null
}

variable "onprem_dns" {
  description = "Reenvío de DNS a los servidores del banco, para resolver sus nombres (el TLS de SQL Server se valida contra el nombre). null = sin reenvío."
  type = object({
    domains    = list(string) # p. ej. ["banco.local"]
    target_ips = list(string) # servidores DNS on-premise
  })
  default = null
}

# --- Entrada ---
variable "domain_name" {
  description = "Nombre con el que los usuarios abren el sitio (el del certificado). null = el nombre DNS del ALB (solo sin HTTPS)."
  type        = string
  default     = null
}

variable "certificate_arn" {
  description = "Certificado de ACM (importado de la PKI del banco o emitido). Con él el ALB escucha en HTTPS 443. Obligatorio en qa y prod."
  type        = string
  default     = null
}

variable "route53_zone_id" {
  description = "Zona pública de Route 53 de domain_name: crea el registro y, si no hay certificate_arn, un certificado de ACM validado por DNS."
  type        = string
  default     = null
}

variable "alb_idle_timeout" {
  description = "Segundos de inactividad que el ALB tolera (streaming de /api/discover/stream y /mcp). Por confirmar en qa."
  type        = number
  default     = 300
}

variable "alb_access_logs_bucket" {
  description = "Bucket existente para los access logs del ALB (no registran cuerpos; CN-06). null = sin access logs."
  type        = string
  default     = null
}

# --- Tarea web + API ---
variable "task_cpu" {
  description = "CPU de la tarea en unidades de Fargate (1024 = 1 vCPU). Tamaño por confirmar (CN-01); referencia on-premise: 4 vCPU y 16 GB."
  type        = number
  default     = 2048
}

variable "task_memory" {
  type    = number
  default = 8192
}

variable "admins" {
  description = "Logins con rol data_admin (DISCOVERY_DATA_AGENT_ADMINS). Obligatorio en qa y prod."
  type        = list(string)
  default     = []
}

variable "db_secret_enabled" {
  description = "Crea el secreto de DISCOVERY_DATA_AGENT_DB (cadena ODBC de la BD DiscoveryDataAgent) y lo inyecta en la API y el Builder. Su valor se carga con `despliegue.sh secret`."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Fuerza una etiqueta de imagen sin leer el parámetro que escribe despliegue.sh. Solo para las pruebas del plan."
  type        = string
  default     = null
}

variable "extra_api_env" {
  description = "Variables de entorno adicionales de la API que no sean secretas (p. ej. DISCOVERY_DATA_AGENT_TOKEN_LIMIT)."
  type        = map(string)
  default     = {}
}

variable "enable_ecs_exec" {
  description = "Permite `aws ecs execute-command` en la tarea (añade el endpoint ssmmessages). Apagado por defecto."
  type        = bool
  default     = false
}

# --- LLM (Bedrock) ---
variable "models_yaml_file" {
  description = "Ruta (relativa a esta carpeta) del models.yaml que se entrega a la API. null = modo determinista, sin LLM."
  type        = string
  default     = null
}

variable "bedrock_resource_arns" {
  description = "ARN que la tarea puede invocar: el inference profile y los foundation-model a los que enruta. Vacío = sin Bedrock ni su VPC endpoint."
  type        = list(string)
  default     = []
}

variable "bedrock_model_id" {
  description = "ModelId tal como aparece en las métricas de CloudWatch de Bedrock; solo para la alarma de throttling y errores."
  type        = string
  default     = null
}

# --- Builder programado ---
variable "builder" {
  description = "Refresco del catálogo: `discovery-data-agent catalog build --db` lanzado por EventBridge Scheduler. Necesita db_secret_enabled."
  type = object({
    enabled               = optional(bool, false)
    schedule              = optional(string, "cron(0 2 * * ? *)")
    timezone              = optional(string, "America/El_Salvador")
    hosts                 = optional(list(string), [])                             # DISCOVERY_DATA_AGENT_BUILDER_HOSTS: hosts o sufijos (.banco.local)
    metadata_user_env     = optional(string, "DISCOVERY_DATA_AGENT_METADATA_USER") # nombres que usa el inventario (metadata_user_env)
    metadata_password_env = optional(string, "DISCOVERY_DATA_AGENT_METADATA_PASSWORD")
    use_llm               = optional(bool, false) # enriquecer descripciones con el rol planner
    cpu                   = optional(number, 1024)
    memory                = optional(number, 4096)
  })
  default = {}
}

# --- Observabilidad ---
variable "log_retention_days" {
  description = "Retención de los grupos de logs. Por confirmar con Seguridad (CN-05)."
  type        = number
  default     = 90
}

variable "alarm_email" {
  description = "Correo que recibe las alarmas (hay que confirmar la suscripción). null = el tema SNS queda sin suscriptores."
  type        = string
  default     = null
}

# --- Coste: solo entornos de prueba (demo). qa y prod los rechazan ---
variable "public_task" {
  description = "La tarea en las subredes públicas, con IP pública y salida HTTPS a internet: sin NAT ni VPC endpoints de interfaz (unos 60 USD/mes menos) y con acceso a proveedores externos como NVIDIA NIM. Necesita alb_internal = false. Nunca en qa ni prod."
  type        = bool
  default     = false
}

variable "fargate_spot" {
  description = "Corre la tarea en Fargate Spot (alrededor de un 70 % más barato). AWS puede pararla con dos minutos de aviso; ECS arranca otra sola y los usuarios vuelven a iniciar sesión. Nunca en qa ni prod."
  type        = bool
  default     = false
}

variable "schedule" {
  description = "Encendido y apagado programados de la tarea (EventBridge Scheduler, sin coste): fuera de horario no se paga Fargate. El ALB sigue en marcha y responde 503."
  type = object({
    enabled  = optional(bool, false)
    start    = optional(string, "cron(0 7 ? * MON-FRI *)")
    stop     = optional(string, "cron(0 20 ? * MON-FRI *)")
    timezone = optional(string, "America/El_Salvador")
  })
  default = {}
}

variable "llm_api_key_envs" {
  description = "Variables de entorno con claves de proveedores de LLM externos (p. ej. NVIDIA_API_KEY). Cada una es un secreto vacío que se carga con `despliegue.sh secret <entorno> nvidia-api-key` y llega solo a la API."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for e in var.llm_api_key_envs : can(regex("^[A-Z][A-Z0-9_]*_API_KEY$", e))])
    error_message = "Nombres en mayúsculas terminados en _API_KEY (p. ej. NVIDIA_API_KEY)."
  }
}

variable "api_requirements" {
  description = "Bloqueo de dependencias con el que despliegue.sh construye la imagen de la API. runtime.lock trae Bedrock; NVIDIA NIM necesita requirements/dev.lock. Terraform no lo usa."
  type        = string
  default     = "requirements/runtime.lock"
}

variable "ecr_keep_images" {
  description = "Imágenes que conserva cada repositorio de ECR (las más recientes)."
  type        = number
  default     = 20
}

variable "sql_sidecar" {
  description = "SQL Server 2022 Express con las bases de BancosSQL como contenedor de la tarea (deploy/aws/sqlserver): servidor de datos y BD DiscoveryDataAgent sin RDS. Solo entornos de prueba."
  type        = bool
  default     = false
}

variable "sql_demo_login" {
  description = "Con sql_sidecar: habilita el login `demo` (contraseña `demo`, permisos de dda_admin) y registra el SQL Server de la tarea al arrancar, sin código de instalación. Solo para mostrar la solución con datos de prueba y el ALB limitado por IP."
  type        = bool
  default     = false
  validation {
    condition     = !var.sql_demo_login || var.sql_sidecar
    error_message = "sql_demo_login necesita sql_sidecar = true."
  }
}

variable "catalog_seed" {
  description = <<-EOT
    Con sql_demo_login: catálogo que la API publica en la BD al arrancar, en lugar de descubrirlo y describirlo con el
    modelo. Así el entorno de pruebas busca sobre el mismo catálogo y conocimiento con el que se miden los resultados.
    root: directorio de la imagen con config/, catalog/ y knowledge/. knowledge: fuentes de conocimiento extra
    (items/, rules/…) que se suman a las de root. server_id: id del servidor en ese catálogo, que recibe el SQL Server
    de la tarea para que los permisos de cada login casen con los activos.
  EOT
  type = object({
    root      = string
    knowledge = optional(string)
    server_id = string
  })
  default = null
  validation {
    condition     = var.catalog_seed == null || var.sql_demo_login
    error_message = "catalog_seed necesita sql_demo_login = true (el SQL Server de la tarea registrado al arrancar)."
  }
}

variable "sql_memory_mb" {
  description = "Memoria máxima de SQL Server dentro de la tarea (MSSQL_MEMORY_LIMIT_MB). SQL Server pide al menos 2000."
  type        = number
  default     = 2048
}

variable "bedrock_mantle" {
  description = "Permite a la API llamar a Claude en Bedrock por la Messages API (bedrock-mantle:CreateInference), con el rol de la tarea. Los modelos se eligen en el models.yaml."
  type        = bool
  default     = false
}
