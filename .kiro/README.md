# Kiro en Discovery Data Agent

Configuración del proyecto para trabajar con [Kiro](https://kiro.dev) y Spec-Driven Development.

| Carpeta | Qué contiene |
|---|---|
| `steering/` | Contexto que Kiro carga siempre: producto, tecnología y estructura |
| `specs/discovery-flow/` | DiscoverFlow: requisitos (EARS), diseño y tareas |
| `specs/knowledge-curation/` | Curación del conocimiento y escalamiento al responsable |
| `specs/aws-deployment/` | Despliegue en AWS con Bedrock |
| `settings/mcp.json` | Servidores MCP: el propio `discovery-data-agent`, Playwright y context7 |

Las specs de Kiro resumen y enlazan las specs detalladas de `docs/specs/` (F22, F24 y CN-01), que siguen siendo la referencia
completa. Las tareas marcadas con `[x]` ya están implementadas y probadas; las abiertas son el trabajo siguiente.
Estas specs se pasaron al formato de Kiro el 2026-11-24, a partir de las specs que el equipo ya mantenía en `docs/specs/`.
