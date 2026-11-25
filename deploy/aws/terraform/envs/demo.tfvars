# Entorno demo: la solución completa en AWS con datos de prueba, al menor coste, para mostrarla y destruirla
# después (`despliegue.sh up demo` / `teardown demo`). Todo en una tarea de Fargate Spot:
#   web + API + SQL Server 2022 Express con las 5 bases de BancosSQL (100 % ficticias) y la BD DiscoveryDataAgent.
# Usuarios SQL: dda_admin (administrador, las 5 bases) y analista (2 bases). Contraseñas: `despliegue.sh credentials demo`.
# El estado se pierde en cada reinicio de la tarea: hay que volver a registrar el servidor y descubrir los esquemas.
environment              = "demo"
discovery_data_agent_env = "dev"
region                   = "us-east-1"
demo                     = false

# ALB público, restringido a las IP indicadas. Con la lista vacía, despliegue.sh pone la IP pública de quien lo
# ejecuta (/32). Para enseñarlo a otras personas, añadir aquí sus IP. Sin certificado escucha en HTTP: las
# contraseñas y la sesión viajan en claro. Con más de una IP, mejor HTTPS (domain_name y route53_zone_id, abajo).
alb_internal      = false
alb_ingress_cidrs = []

# Para HTTPS con un dominio propio en una zona pública de Route 53:
# domain_name     = "discovery-data-agent-demo.ejemplo.com"
# route53_zone_id = "Z0123456789ABCDEFGHIJ"

# --- Perfil económico (README §Coste) ---
public_task     = true # sin NAT ni VPC endpoints de interfaz: unos 60 USD/mes menos
fargate_spot    = true # unos 70 % menos en la tarea
task_cpu        = 1024
task_memory     = 4096 # SQL Server 2 GB + API y web
ecr_keep_images = 3
# Encendido solo en horario laboral (descomentar si el demo se queda varios días):
# schedule = { enabled = true, start = "cron(0 7 ? * MON-FRI *)", stop = "cron(0 20 ? * MON-FRI *)" }

log_retention_days = 3

# --- Datos: SQL Server Express dentro de la tarea, sin RDS ---
sql_sidecar       = true
sql_memory_mb     = 2048
db_secret_enabled = true
admins            = ["dda_admin", "demo"]
# Login `demo` / contraseña `demo` con todo el acceso, y el SQL Server ya registrado al arrancar (sin código de
# instalación). Solo con estos datos ficticios y el ALB limitado a las IP de alb_ingress_cidrs.
sql_demo_login = true
# El mismo catálogo y conocimiento con el que se miden los resultados en local (BancosSQL con su glosario), publicado
# en la BD al arrancar: sin esto la API lo descubre y lo describe de cero con el modelo, y responde distinto.
catalog_seed = {
  root      = "tests/fixtures/bancos"
  knowledge = "tests/fixtures/bancos/eval/conocimiento"
  server_id = "LOCAL_SQLEXPRESS"
}

# Respuestas con datos, como en local: cifras con los permisos de cada login (ask_flow) y, cuando la plantilla no
# basta, el SQL que escribe el rol `coder` (fase 1b). Solo sobre las bases ficticias del SQL Server de la tarea.
extra_api_env = {
  DISCOVERY_DATA_AGENT_ASK_FLOW    = "1"
  DISCOVERY_DATA_AGENT_ASK_LLM_SQL = "1"
}

# --- LLM: elegible en pantalla (Administración → Modelos de IA) ---
# Por defecto NVIDIA NIM y Claude por la API de Anthropic, como en local; sus claves las carga `up` desde el .env (o
# `secret demo nvidia-api-key`…). Perfiles en Bedrock, con el rol de la tarea: Nova Pro, Claude Sonnet y Haiku.
models_yaml_file = "config/models.aws.yaml"
bedrock_mantle   = true
# Amazon Nova Pro por Converse (perfil por defecto mientras la cuenta no tenga cuota de Claude): el inference
# profile de EE. UU. y los foundation-model de las regiones a las que enruta. Con public_task no crea VPC endpoint.
bedrock_resource_arns = [
  "arn:aws:bedrock:us-east-1:*:inference-profile/us.amazon.nova-pro-v1:0",
  "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",
]
llm_api_key_envs = ["NVIDIA_API_KEY", "ANTHROPIC_API_KEY"]
api_requirements = "requirements/dev.lock" # runtime.lock no trae los clientes de NIM ni de Anthropic
