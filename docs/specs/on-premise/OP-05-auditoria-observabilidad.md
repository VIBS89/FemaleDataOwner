# OP-05 — Auditoría y observabilidad · on-premise

> Implementa en local: [F11](../comun/F11-audit.md)

## Auditoría
- **SQLite** en `./data/audit.db` (volumen del contenedor), con el modelo de tablas de F11.
- Si la organización lo prefiere, se puede apuntar a `ConverData_Audit` en SQL Server cambiando la cadena de conexión (SQLAlchemy); el modelo es el mismo.
- Fail-closed como en F11; en dev puede usarse `audit.fail_open: true`.
- Copia de seguridad: incluir `./data/` en el respaldo del servidor.
- El scorecard (precisión, calibración, latencia, coste, 👍) se calcula con consultas sobre `audit.db`.

## Observabilidad
- Logs JSON (structlog) en consola y en `./data/logs/`, con la misma lista blanca D5 de F17.
- Trazas de LLM opcionales con **Langfuse autoalojado** en el mismo `docker compose`, con el contenido de los prompts desactivado.

## Criterios de aceptación
1. Cada pregunta deja exactamente un registro en `audit.db`.
2. El scorecard se genera con un comando (`converdata report scorecard`) desde `audit.db`.
3. Los archivos de log no contienen preguntas, SQL ni filas.
