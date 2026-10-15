# ConverData

Agente de descubrimiento de datos en lenguaje natural sobre SQL Server: **CrewAI**, **Amazon Bedrock** y MCPs propios bajo Apache-2.0 (**converdata-mcp** y **converdata-discovery**). Dos despliegues con la misma lógica: **on-premise** (MVP) y **cloud native** en AWS Bedrock AgentCore.

- Features y contrato de respuesta: [docs/features.md](docs/features.md)
- Trazabilidad con la propuesta "Enterprise Data Discovery Agent" (Banco Atlántida): [docs/propuesta-trazabilidad.md](docs/propuesta-trazabilidad.md)
- Specs: [comunes](docs/specs/comun/) · [cloud native](docs/specs/cloud-native/) · [on-premise](docs/specs/on-premise/)
- Arquitectura (Archify, fork en `tools/archify`):
  - [Cloud native en AWS](docs/architecture/cloud-native-architecture.html)
  - [On-premise](docs/architecture/onpremise-architecture.html)
  - [Permisos de BD heredados](docs/architecture/permisos-heredados.html)

## Estado
Fase 1: solo especificación y arquitectura (sin código de la solución todavía).
