#!/usr/bin/env bash
# Arranque del contenedor: SQL Server con las bases ya cargadas en la imagen; pone las contraseñas que inyecta ECS
# (Secrets Manager) y habilita los logins. Cada arranque parte de la imagen: lo escrito se pierde al parar la tarea.
set -euo pipefail
: "${MSSQL_SA_PASSWORD:?}" "${DDA_ADMIN_PASSWORD:?}" "${DDA_ANALISTA_PASSWORD:?}" "${DDA_APP_PASSWORD:?}"
# La contraseña va en SQLCMDPASSWORD y el SQL por la entrada estándar: nada secreto en la línea de comandos.
SQLCMD=(/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b)

/opt/mssql/bin/sqlservr &
pid=$!
for _ in $(seq 1 90); do
  SQLCMDPASSWORD="$SEED_SA_PASSWORD" "${SQLCMD[@]}" -Q "SELECT 1" >/dev/null 2>&1 && break
  sleep 2
done

# Las contraseñas son alfanuméricas (las genera Terraform sin símbolos): no rompen las comillas del SQL.
for value in "$MSSQL_SA_PASSWORD" "$DDA_ADMIN_PASSWORD" "$DDA_ANALISTA_PASSWORD" "$DDA_APP_PASSWORD"; do
  [[ "$value" =~ ^[A-Za-z0-9]{16,}$ ]] || { echo "Contraseña con formato inesperado" >&2; exit 1; }
done
SQLCMDPASSWORD="$SEED_SA_PASSWORD" "${SQLCMD[@]}" -i /dev/stdin >/dev/null <<SQL
ALTER LOGIN dda_admin WITH PASSWORD = N'$DDA_ADMIN_PASSWORD'; ALTER LOGIN dda_admin ENABLE;
ALTER LOGIN analista WITH PASSWORD = N'$DDA_ANALISTA_PASSWORD'; ALTER LOGIN analista ENABLE;
ALTER LOGIN dda_app WITH PASSWORD = N'$DDA_APP_PASSWORD'; ALTER LOGIN dda_app ENABLE;
ALTER LOGIN sa WITH PASSWORD = N'$MSSQL_SA_PASSWORD';
SQL
echo ">> SQL Server listo (logins dda_admin, analista, dda_app)"
unset SEED_SA_PASSWORD
wait "$pid"
