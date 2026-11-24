# Entorno demo: servidores simulados con metadatos de prueba (usuarios demo/analista, contraseña demo), sin VPN,
# sin BD y sin datos del banco. Sirve para probar el despliegue de punta a punta. El estado se pierde en cada reinicio.
environment              = "demo"
discovery_data_agent_env = "dev"
region                   = "us-east-1"
demo                     = true

# ALB público, restringido a las IP del equipo. Sin certificado escucha en HTTP: usar solo con los datos simulados.
alb_internal      = false
alb_ingress_cidrs = [] # RELLENAR: IP públicas del equipo, p. ej. ["198.51.100.7/32"]. Con la lista vacía no se crea nada.

# Para HTTPS con un dominio propio en una zona pública de Route 53:
# domain_name     = "discovery-data-agent-demo.ejemplo.com"
# route53_zone_id = "Z0123456789ABCDEFGHIJ"

task_cpu           = 1024
task_memory        = 4096
log_retention_days = 14

# Sin models_yaml_file el descubrimiento corre en modo determinista. Para probar Bedrock:
# models_yaml_file      = "config/models.demo.yaml"   # copia de config/models.bedrock.example.yaml
# bedrock_resource_arns = ["arn:aws:bedrock:us-east-1:<cuenta>:inference-profile/<perfil>", "arn:aws:bedrock:*::foundation-model/<modelo>"]
