#!/usr/bin/env bash
# Al construir la imagen: arranca SQL Server, ejecuta los scripts de BancosSQL y logins.sql, y lo apaga limpio.
set -euo pipefail
SQLCMD=(/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SEED_SA_PASSWORD" -C -b)

MSSQL_SA_PASSWORD="$SEED_SA_PASSWORD" /opt/mssql/bin/sqlservr >/tmp/sqlservr.log 2>&1 &
for _ in $(seq 1 90); do
  "${SQLCMD[@]}" -Q "SELECT 1" >/dev/null 2>&1 && break
  sleep 2
done
"${SQLCMD[@]}" -Q "SELECT 1" >/dev/null || { cat /tmp/sqlservr.log; exit 1; }

for script in /seed/bancos/0[1-9]_*.sql; do
  echo ">> $(basename "$script")"
  "${SQLCMD[@]}" -i "$script" >/dev/null
done
"${SQLCMD[@]}" -i /seed/logins.sql
"${SQLCMD[@]}" -Q "SHUTDOWN" >/dev/null || true
wait || true
