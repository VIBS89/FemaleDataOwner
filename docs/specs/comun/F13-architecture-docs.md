# F13 — Arquitectura documentada (Archify)

## Objetivo
Mantener tres diagramas interactivos y versionados que expliquen la solución, generados con el fork de
[Archify](https://github.com/tt-a1i/archify) incluido en `tools/archify` (ver `tools/archify/FORK.md`).

## Vistas
| Archivo | Modo | Qué explica |
|---|---|---|
| `docs/architecture/cloud-native-architecture.html` | Architecture | **Arquitectura cloud native en AWS**: Cognito, WAF/ALB, ECS (Chainlit + BFF), AgentCore Runtime y Gateway, Bedrock, OpenSearch Serverless, Secrets Manager/KMS, S3 (catálogo sin muestras), Catalog Builder + sql-to-mcp, y VPN/DX hacia SQL Server on-prem (datos + `ConverData_Audit`) (CN-01 a CN-06) |
| `docs/architecture/onpremise-architecture.html` | Architecture | **Arquitectura on-premise**: docker compose dentro de la red corporativa (converdata-app con AskFlow + converdata-mcp, ChromaDB, auditoría SQLite, sql-to-mcp) con Bedrock como único servicio externo (OP-01 a OP-06) |
| `docs/architecture/permisos-heredados.html` | Sequence | **Permisos de BD heredados**: el login SQL del usuario determina qué ve el catálogo, con qué login se ejecuta cada consulta y cómo se deniega un acceso fuera de permisos (F14) |

Las fuentes de cada diagrama (`*.archify.json`) se guardan junto al HTML, así que se pueden regenerar:
```bash
node tools/archify/bin/archify.mjs finalize <architecture|sequence> docs/architecture/<x>.archify.json docs/architecture/<x>.html --quality showcase --json
```
Los recibos de validación que genera `finalize` (`*.finalize*.json`, `*.browser-check.json`, `*.delivery.json`) son temporales y están en `.gitignore`.

## Descripción por componente
Cada componente o participante tiene un campo `description` (extensión del fork) que explica **qué hace y cómo ayuda en la arquitectura**, con referencia a sus specs (F#). Aparece en la ficha del componente al hacer clic.

## Criterios de aceptación
1. Las tres vistas abren sin conexión a internet en un navegador.
2. Cada componente corresponde a un módulo de `src/converdata/`, a un servicio de `docker-compose.yml` o a un recurso de la IaC de AWS.
3. Los diagramas se regeneran cuando cambia la arquitectura (checklist del PR).
