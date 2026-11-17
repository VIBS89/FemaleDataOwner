# CN-05 — Auditoría y observabilidad · despliegue en AWS

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Despliegue posterior al piloto on-premise; nada está desplegado.
>
> Implementa en AWS: [F11](../comun/F11-audit.md) · equivalente on-premise: [OP-05](../on-premise/OP-05-auditoria-observabilidad.md)

## Auditoría: on-premise aunque la aplicación corra en AWS
- **Esquema `audit` de la BD `ConverData`**, en el SQL Server del banco: la misma BD y el mismo modelo de F11 que on-premise. No hay una BD de auditoría separada ni copia en AWS (PRD §13, decisión 10).
- La escribe `ConverData-API` por la VPN (TDS 1433) con un login de servicio de solo `INSERT` en `audit`, guardado en Secrets Manager ([CN-03](CN-03-identidad.md)).
- **Fail-closed** (F11): si no se puede escribir la auditoría, no se responde; `audit.fail_open` impide arrancar en qa y prod. Un corte de la VPN bloquea las respuestas.
- Se auditan además los accesos denegados, los bloqueos de login, la lectura de la auditoría, los cambios de inventario y las revocaciones de sesión.
- Lectura: `/admin/audit` (rol `data_admin`), en vivo contra la BD on-premise.
- Respaldo, retención (180 días) y purga: los del DBA para la BD `ConverData`, igual que on-premise.

Estado del código: con `CONVERDATA_DB` la API escribe la auditoría en el esquema `audit` de la BD `ConverData` (`SqlServerAuditSink`,
HU-20); los archivos JSONL con cadena de hashes (`CONVERDATA_AUDIT_DIR`) quedan solo para desarrollo. Este despliegue exige la BD,
porque la tarea no tiene disco persistente.

## Observabilidad: CloudWatch Logs, sin contenido
- Logs JSON de la tarea y del Builder en **CloudWatch Logs** (PRD §13, decisión 14): sin el texto de las preguntas, sin SQL y sin nombres de objetos que el usuario no pueda ver; de los errores, solo el tipo de excepción. Equivale a los logs rotados y al Visor de eventos on-premise (`CONVERDATA_EVENT_LOG=0` en el contenedor).
- Retención del grupo de logs: por confirmar. Cifrado con KMS.
- Contadores (peticiones, errores, p50/p95, bloqueos, tokens) en `/health/metrics`, solo para `data_admin`; cómo llevarlos a métricas de CloudWatch está por confirmar (filtros de métricas sobre los logs).
- Las métricas de F25 se calculan en la BD `ConverData`; a AWS solo llegan contadores.
- Pendiente: hoy el logger escribe en un archivo (`CONVERDATA_LOG_DIR`, obligatorio en qa y prod), no en la salida estándar que recoge CloudWatch.

## Alarmas
| Alarma | Condición | Severidad |
|---|---|---|
| Fallo de escritura de auditoría | Cualquier fallo (las respuestas quedan bloqueadas) | Crítica |
| VPN | Túnel caído | Crítica |
| Tarea | Destino del ALB no saludable (`/health`) o tarea reiniciada | Crítica |
| Errores | Tasa de 5xx del ALB > 5 % durante 5 min | Alta |
| Latencia | p95 del descubrimiento > 10 s durante 15 min | Alta |
| Bedrock | *Throttling* o errores > 5 % durante 5 min | Alta |
| Builder | La tarea nocturna termina con error o no corre | Alta |
| Certificado | Certificado del ALB a menos de 30 días de expirar | Media |

Los umbrales y el canal de aviso (correo o el monitoreo del banco) están por confirmar. Ninguna alarma incluye contenido.

## Criterios de aceptación
1. Cada pregunta deja exactamente un registro en el esquema `audit`, con los mismos candidatos que se mostraron.
2. Con la VPN cortada, las preguntas no reciben respuesta y se disparan las alarmas de VPN y de auditoría.
3. Una pregunta con un literal marcado no aparece en ningún grupo de logs ni en los access logs del ALB.
4. Un fallo provocado del Builder dispara su alarma.
5. Tras una sesión de prueba, en AWS no existe ningún registro de auditoría.
