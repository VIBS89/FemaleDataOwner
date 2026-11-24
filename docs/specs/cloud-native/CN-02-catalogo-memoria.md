# CN-02 — Catálogo e ingesta + memoria · despliegue en AWS

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16). Despliegue posterior al piloto on-premise; nada está desplegado.
>
> Implementa en AWS: [F1](../comun/F01-catalog-builder.md), [F2](../comun/F02-semantic-memory.md) y [F23](../comun/F23-knowledge-sources.md) · equivalente on-premise: [OP-02](../on-premise/OP-02-catalogo-memoria.md)

## Ingesta
| Pieza | En AWS | Equivalente on-premise |
|---|---|---|
| Disparo | **EventBridge Scheduler**, cada noche, con `RunTask`; no hay nada encendido entre ejecuciones (PRD §13, decisión 12) | Programador de tareas de Windows |
| Builder | Tarea ECS Fargate con **la misma imagen de la API** y el comando `discovery-data-agent catalog build`; corre y termina | El mismo comando en el servidor |
| Login de metadatos | Secrets Manager, inyectado como las variables de entorno que nombra el inventario (`metadata_user_env`, `metadata_password_env`); solo en la tarea del Builder ([CN-03](CN-03-identidad.md)) | DPAPI |
| Lectura de metadatos | Consultas fijas a `sys.*` por la VPN (TDS 1433); nunca valores de columnas | Igual, sin VPN |
| Destino | **BD `DiscoveryDataAgent` en el SQL Server del banco**, por la VPN: esquemas `catalog` (con historial), `knowledge` y `curation`. Nada se escribe en AWS (PRD §13, decisión 10) | La misma BD |
| Fuentes de conocimiento (F23) | Diccionarios, documentos y reglas de la red del banco, leídos por la VPN. Implementado: diccionario en CSV (HU-25) y reglas; documentos (HU-26) y linaje SSIS (HU-27) pendientes. Cómo lee la tarea una carpeta compartida (SMB): por confirmar | Las mismas fuentes |
| Redacción de datos personales | En la memoria del Builder, antes de escribir; el original no se copia ni pasa a disco. Hoy el detector cubre cinco patrones (DUI, NIT, correo, teléfono, tarjeta) | Igual |
| Descripciones con LLM (opcional) | `--models`: el mismo modelo de Bedrock por el VPC endpoint | Bedrock por el proxy corporativo |

Estado del código (2026-11-17): `discovery-data-agent catalog build --db` parte del catálogo publicado en la BD `DiscoveryDataAgent`, toma de ella el
inventario de servidores, trabaja en un directorio temporal y publica el resultado, así que la tarea no necesita disco persistente.
No se ha probado en una tarea de Fargate.

## Memoria: índice léxico en la tarea
- Al arrancar, `DiscoveryDataAgent-API` carga el catálogo y el conocimiento de la BD `DiscoveryDataAgent` en un **índice BM25 en memoria** y busca solo entre los objetos que el usuario puede ver (PRD §13, decisión 9).
- Sin embeddings ni índice vectorial: no hay ningún almacén de búsqueda que desplegar, respaldar o proteger en AWS.
- El índice se pierde al parar la tarea y se reconstruye al arrancar.
- **Refresco tras el Builder**: on-premise la API recarga el catálogo cuando ella lanza la construcción (`POST /admin/catalog/build`). Con el Builder en otra tarea, la API recarga sola cuando cambia la versión del catálogo en la BD: lo comprueba al atender una petición, como mucho cada 15 s (`AgentRuntime.refresh` en `api/discovery_data_agent_api/runtime.py`; `api/tests/test_catalog_db.py::test_la_api_carga_lo_que_publica_el_builder_sin_reiniciar`).

## Criterios de aceptación
1. Un cambio de esquema on-premise aparece en las respuestas tras el siguiente ciclo nocturno, sin intervención manual.
2. La tarea del Builder termina sola; su código de salida es distinto de 0 si falla y eso dispara una alarma ([CN-05](CN-05-auditoria-observabilidad.md)).
3. Después de una ejecución del Builder no queda en AWS ningún archivo ni objeto con catálogo o conocimiento.
4. Un documento con un DUI y un número de cuenta de prueba no deja esos literales en la BD `DiscoveryDataAgent` ni en los logs.
5. El login de metadatos no está disponible en la tarea de la API.
6. `discovery-data-agent eval gate` aprueba contra el catálogo cargado en qa.
