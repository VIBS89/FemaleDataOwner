# F13 — Arquitectura documentada (Archify)

## Objetivo
Mantener ocho diagramas interactivos y versionados que expliquen la solución, y un documento que los ordena con el modelo C4
([`docs/architecture/README.md`](../../architecture/README.md)). Se generan con el fork de
[Archify](https://github.com/tt-a1i/archify) incluido en `tools/archify` (ver `tools/archify/FORK.md`).

## Vistas
| Archivo | Tipo (`diagram_type`) | Qué explica |
|---|---|---|
| `docs/architecture/c4-contexto.html` | `architecture` | **C4 nivel 1, contexto**: quién usa ConverData y con qué sistemas habla |
| `docs/architecture/cloud-native-architecture.html` | `architecture` | **Despliegue mínimo en AWS (posterior al piloto)**: ALB interno con ACM, una tarea de ECS Fargate con los contenedores web (Next.js) y `ConverData-API` (DiscoverFlow + MCP), Builder como tarea lanzada por EventBridge Scheduler, Bedrock por VPC endpoint, Secrets Manager para secretos de servicio, CloudWatch Logs sin contenido y Site-to-Site VPN hacia la red del banco, donde quedan SQL Server, la BD `ConverData` y las fuentes de conocimiento. No incluye AgentCore, OpenSearch, Cognito, WAF, S3 ni Transit Gateway (CN-01 a CN-06) |
| `docs/architecture/onpremise-architecture.html` | `architecture` | **Arquitectura on-premise, fase 1a**: Windows Server con IIS delante de dos procesos (web Next.js y `ConverData-API` con DiscoverFlow + MCP e índice léxico en memoria), Builder como comando lanzado por el Programador de tareas, BD `ConverData` en tablas normales (sin vectores, Full-Text ni grafo; SQL Server 2016+), fuentes de conocimiento y Bedrock como único servicio externo. Las fichas indican qué está construido y qué está pendiente (OP-01 a OP-07) |
| `docs/architecture/controles-calidad-bancaria.html` | `workflow` | **Controles de una petición y compuerta de calidad**: qué comprueba la API antes de responder y las siete suites de `converdata eval gate` ([calidad bancaria](../../calidad-bancaria.md)) |
| `docs/architecture/permisos-heredados.html` | `sequence` | **Permisos de BD heredados**: el login SQL del usuario determina qué ve el catálogo al descubrir (construido) y, en la fase 1b planificada, con qué login se ejecuta cada consulta y cómo se deniega un acceso fuera de permisos (F14) |
| `docs/architecture/c4-componentes-api.html` | `architecture` | **C4 nivel 3, componentes**: las piezas internas de `ConverData-API` |
| `docs/architecture/flujo-descubrimiento.html` | `workflow` | **Cómo se responde una pregunta**, paso a paso (F22) |
| `docs/architecture/modelo-datos-converdata.html` | `erd` | **Tablas de la BD `ConverData`** (esquemas `catalog`, `knowledge`, `audit`, `curation`; `db/converdata/`) |

Las fuentes de cada diagrama (`*.archify.json`) se guardan junto al HTML, así que se pueden regenerar:
```bash
node tools/archify/bin/archify.mjs finalize <architecture|workflow|sequence|erd> docs/architecture/<x>.archify.json docs/architecture/<x>.html --quality showcase --json
```
Los recibos de validación que genera `finalize` (`*.finalize*.json`, `*.browser-check.json`, `*.delivery.json`) son temporales y están en `.gitignore`.
Si `finalize` falla en `browser-check` con `evidence-path-conflict`, el recibo `*.browser-check.json` anterior corresponde a otro HTML: apartarlo y repetir.

## Descripción por componente
Cada componente o participante tiene un campo `description` (extensión del fork) que explica **qué hace y cómo ayuda en la arquitectura**, con referencia a sus specs (F#). Aparece en la ficha del componente al hacer clic.

## Criterios de aceptación
1. Los ocho diagramas abren sin conexión a internet en un navegador.
2. Cada componente corresponde a un módulo de `src/converdata/` o de `api/converdata_api/`, a un proceso (web Next.js, `ConverData-API`, comando del Builder lanzado por el Programador de tareas) o a un recurso de SQL Server (on-premise), o a un recurso de la IaC de AWS (cloud native). No hay servicios de Windows propios (PRD §13, decisiones 11 y 12).
3. Los diagramas se regeneran cuando cambia la arquitectura (checklist del PR).
