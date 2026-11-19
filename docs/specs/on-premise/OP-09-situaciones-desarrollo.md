# OP-09 — Situaciones de desarrollo y adaptadores intercambiables · on-premise

> Completa el entorno **dev** de [OP-07](OP-07-instalacion-operacion.md#entornos). Specs relacionadas: [OP-02](OP-02-catalogo-memoria.md)
> almacén · [OP-05](OP-05-auditoria-observabilidad.md) auditoría · [F16](../comun/F16-llm-providers.md) gateway de LLM · [F25](../comun/F25-success-metrics.md) evaluación.
> Plan de trabajo que la usa: [sesiones de desarrollo con goals](../../backlog/sesiones-goals.md).

## Objetivo
Que cualquier persona (o sesión de Claude Code) pueda avanzar el backlog on-premise **con la infraestructura que tenga a mano**, sin esperar a
la instancia SQL Server 2025 (⚠️ S5), a la cuenta AWS (⚠️ S4) ni al Windows Server del piloto, y que lo hecho en una situación siga válido en la
siguiente sin reescribirlo.

## Situaciones de desarrollo
| ID | Situación | Qué hay | Qué se puede cerrar | Qué no se puede cerrar |
|---|---|---|---|---|
| **SD-1** | Sin infraestructura | Python 3.12, Node 20; almacenamiento en archivos y memoria; LLM desactivado (flujo determinista) o `fake` | Lógica de dominio y aplicación, puertos, adaptadores de archivos, API, web, MCP, tests de contrato contra *fakes*, DDL escrito, scripts PowerShell con análisis estático | Nada que dependa de T-SQL real, Bedrock ni IIS |
| **SD-2** | LLM local | SD-1 + Ollama (`bge-m3` y un modelo de chat) o NIM con datos de prueba (`environment: local`, F16) | Medición de embeddings (HU-34), calidad del DiscoverFlow con LLM, latencia relativa | Latencia y coste reales con Bedrock |
| **SD-3** | SQL Server 2025 local | SD-1 + SQL Server 2025 Developer (instalado o en contenedor) con Full-Text | DDL aplicado, `SqlServerVectorStore`, catálogo con historial temporal, auditoría fail-closed, permisos de roles, logins SQL de prueba | Grupos de AD, gMSA, DPAPI |
| **SD-4** | Bedrock real | SD-1 + cuenta AWS con Bedrock e IAM Roles Anywhere (o credenciales temporales de desarrollo) | HU-35, HU-36 con Guardrails, p50/p95 y coste por pregunta | — |
| **SD-5** | Windows Server de QA | Servidor con IIS, AD, SQL Server 2025 de QA | Scripts `deploy/windows/` 01–10, OP-07 CA1–CA7, OP-08 CA1–CA7, HU-37, HU-38, HU-39 | — |

Las situaciones se combinan (por ejemplo SD-2 + SD-3). **SD-1 es la base obligatoria**: toda historia tiene que quedar en verde en SD-1 antes de
probarse en otra situación, salvo que la historia sea solo de infraestructura (HU-37 a HU-39).

### SQL Server 2025 en contenedor (SD-3)
- Imagen de Microsoft `mcr.microsoft.com/mssql/server:2025-latest` con `ACCEPT_EULA=Y` y `MSSQL_PID=Developer`. La imagen base **no trae
  Full-Text Search**: hace falta una imagen derivada con el paquete `mssql-server-fts` (`deploy/dev/sqlserver/Dockerfile`, ⚠️ propuesto) o una
  instalación Developer en Windows.
- `deploy/dev/sqlserver/init.sql` crea la BD `ConverData`, aplica `db/converdata/*.sql` en orden y crea dos logins de prueba
  (`cd_analista`, con acceso a `VBank_ING`; `cd_rrhh`, con acceso a `RRHH`) para los CA de visibilidad (OP-03 CA1, F14).
- Las contraseñas de los logins de prueba van en `.env` (ignorado por git), nunca en el repo.

## Selección de adaptadores
El código ya separa puertos y adaptadores (`AuditSink`, `VectorStore`, `MetadataSource`, `ObjectLister`, [capas del backend](../../architecture/capas-backend.md)).
La situación se elige **solo por configuración**, sin cambiar código:

| Variable | Valores | Por defecto | Efecto |
|---|---|---|---|
| `CONVERDATA_STORE` | `files` · `sqlserver` | `files` | Catálogo, conocimiento, curación y golden: YAML/JSON en `CONVERDATA_DATA_ROOT` y `CONVERDATA_CURATION_DIR`, o BD `ConverData` |
| `CONVERDATA_AUDIT` | `files` · `sqlserver` | igual que `CONVERDATA_STORE` | `FileAuditSink` o `SqlServerAuditSink` (OP-05) |
| `CONVERDATA_DB` | Cadena ODBC **sin contraseña** (`Trusted_Connection=yes` o gMSA; en SD-3, `UID` y la contraseña en `CONVERDATA_DB_PASSWORD` desde `.env`) | — | Conexión a la BD `ConverData`; obligatoria si algún adaptador es `sqlserver` |
| `CONVERDATA_MODELS` | Ruta a `models.yaml` | sin LLM | Gateway de F16; sin archivo, flujo determinista |
| `CONVERDATA_ENV` | `dev` · `qa` · `prod` | `dev` | Fuera de `dev`: prohíbe `files`, Ollama, NIM, `CONVERDATA_DEMO=1`, `audit.fail_open: true` y cookies sin `Secure` (el arranque falla con un mensaje claro) |

`src/converdata/bootstrap.py` es el **único** lugar que lee estas variables y ensambla los adaptadores (HU-09). Ningún módulo de dominio ni
de aplicación importa `pyodbc` (lo comprueba `tests/test_architecture.py`).

### Puertos que faltan
| Puerto | Hoy | Necesario para |
|---|---|---|
| `CatalogStore` (lectura y escritura del catálogo con historial) | `catalog/store.py` lee YAML | HU-06, HU-09 |
| `CurationStore` (descripciones humanas, reglas, solicitudes, owners) | Archivos en `api/converdata_api/curation.py`, sin puerto | HU-28 a HU-31 en BD |
| `GoldenStore` (confirmaciones y plantillas anonimizadas) | YAML desde el feedback | HU-29 en BD |
| `Notifier` (Database Mail, Teams) | Webhook opcional en la API | HU-30 |

Cada puerto nuevo nace con **un adaptador de archivos y una batería de tests de contrato** que después corre también contra el adaptador
`sqlserver`; así las sesiones que no tienen SQL Server avanzan con el de archivos y no se rompe nada al cambiar.

## Tests por situación
| Marca de pytest | Situación | Se omite si… |
|---|---|---|
| (ninguna) | SD-1 | nunca: es la suite que exigen los hooks (`pytest` antes de `git commit`) |
| `llm_local` | SD-2 | no responde `OLLAMA_HOST` ni hay `NVIDIA_API_KEY` |
| `sqlserver` | SD-3 | no hay `CONVERDATA_TEST_DB` |
| `bedrock` | SD-4 | no hay credenciales de AWS ni `CONVERDATA_MODELS` con proveedor `bedrock` |
| `windows_server` | SD-5 | no se ejecuta en un Windows Server con IIS (`10-verificar.ps1` llama a estos tests) |

Las marcas se registran en `[tool.pytest.ini_options] markers` de `pyproject.toml`; un test con marca y sin su situación queda **omitido con
el motivo** (`pytest.skip`), nunca en verde silencioso. Los scripts PowerShell se verifican en SD-1 con `Invoke-ScriptAnalyzer` (PSScriptAnalyzer)
y Pester con `-WhatIf`, y en SD-5 de verdad.

## Datos de prueba
- BancosSQL (`tests/fixtures/`) y AdventureWorks son los únicos datos fuera de `qa`/`prod`. `BancosSQL.zip` sale del árbol de git o pasa a Git LFS (riesgo 7 del reparto).
- Literales marcados (un DUI y un número de cuenta ficticios) sembrados en los fixtures para los tests de fuga de OP-05 CA3, OP-06 CA3 y F23 CA3.

## Criterios de aceptación
1. Con un clon limpio y solo SD-1, `pip install -e .[dev,api]`, `python -m pytest -q` y, en `web/`, `npm ci` y `npx tsc --noEmit` terminan sin errores
   y los tests de SD-2 a SD-5 aparecen como omitidos con su motivo.
2. Cambiar `CONVERDATA_STORE` y `CONVERDATA_AUDIT` de `files` a `sqlserver` en SD-3 no exige cambios de código y los tests de contrato de
   cada puerto pasan con los dos adaptadores.
3. Con `CONVERDATA_ENV=qa` y `CONVERDATA_STORE=files`, `CONVERDATA_DEMO=1` u Ollama configurado, el servicio no arranca y el mensaje dice qué variable corregir.
4. Ningún archivo del repo contiene contraseñas de los logins de prueba ni claves de AWS o NVIDIA (búsqueda de patrones en CI y en el hook de commit).
5. `tests/test_architecture.py` falla si un módulo de las capas de dominio o aplicación ([capas del backend](../../architecture/capas-backend.md))
   importa `pyodbc`, `boto3`, `fastapi` o un adaptador concreto.
