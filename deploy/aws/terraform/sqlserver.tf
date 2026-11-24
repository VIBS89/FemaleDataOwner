# SQL Server 2022 Express como contenedor de la tarea (sql_sidecar; solo entornos de prueba). Hace de "servidor del
# banco" con las cinco bases de BancosSQL y aloja la BD de trabajo DiscoveryDataAgent. Sin RDS: Express no paga
# licencia y comparte la tarea, así que no añade ni red ni máquina. Lo escrito se pierde al parar la tarea (CN-06).
locals {
  sql_logins = var.sql_sidecar ? toset(["sa", "admin", "analista", "app"]) : toset([])
  # La API ve SQL Server en localhost: los contenedores de una tarea comparten la red.
  sql_db_connection = var.sql_sidecar ? join(";", [
    "Driver={ODBC Driver 18 for SQL Server}", "Server=localhost,1433", "Database=DiscoveryDataAgent",
    "UID=dda_app", "PWD=${random_password.sql["app"].result}", "Encrypt=yes", "TrustServerCertificate=yes",
  ]) : null

  sql_container = var.sql_sidecar ? [{
    name      = "sqlserver"
    image     = "${aws_ecr_repository.this["sqlserver"].repository_url}:${local.image_tag}"
    essential = true
    environment = [
      { name = "MSSQL_MEMORY_LIMIT_MB", value = tostring(var.sql_memory_mb) },
      { name = "DDA_DEMO_LOGIN", value = var.sql_demo_login ? "1" : "0" },
    ]
    secrets = [
      for env, key in {
        MSSQL_SA_PASSWORD = "sa", DDA_ADMIN_PASSWORD = "admin", DDA_ANALISTA_PASSWORD = "analista", DDA_APP_PASSWORD = "app"
      } : { name = env, valueFrom = "${aws_secretsmanager_secret.sql[0].arn}:${key}::" }
    ]
    logConfiguration = local.log_configuration["sqlserver"]
    healthCheck = {
      command     = ["CMD-SHELL", "SQLCMDPASSWORD=\"$MSSQL_SA_PASSWORD\" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -Q 'SELECT 1' >/dev/null"]
      interval    = 15
      timeout     = 10
      retries     = 5
      startPeriod = 90
    }
  }] : []
}

# Alfanuméricas: iniciar.sh las inserta en SQL sin escapar, y lo comprueba.
resource "random_password" "sql" {
  for_each    = local.sql_logins
  length      = 28
  special     = false
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}

resource "aws_secretsmanager_secret" "sql" {
  count                   = var.sql_sidecar ? 1 : 0
  name                    = "discovery-data-agent/${var.environment}/sql-logins"
  description             = "Contraseñas de SQL Server Express de pruebas: sa, admin (dda_admin), analista y app (dda_app)"
  kms_key_id              = aws_kms_key.this.arn
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "sql" {
  count         = var.sql_sidecar ? 1 : 0
  secret_id     = aws_secretsmanager_secret.sql[0].id
  secret_string = jsonencode({ for k in local.sql_logins : k => random_password.sql[k].result })
}

# Con el contenedor, la cadena de la BD DiscoveryDataAgent la escribe Terraform (en qa y prod la carga el equipo).
resource "aws_secretsmanager_secret_version" "db" {
  count         = var.sql_sidecar ? 1 : 0
  secret_id     = aws_secretsmanager_secret.db[0].id
  secret_string = local.sql_db_connection
}
