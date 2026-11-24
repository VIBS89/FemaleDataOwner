# Diseño: Despliegue en AWS

## Topología
```mermaid
flowchart LR
  U[Usuarios del banco] --> ALB
  M[Agentes por MCP] --> ALB
  subgraph AWS[VPC privada sin internet]
    ALB[ALB HTTPS] -->|/| WEB[Web Next.js]
    ALB -->|/mcp| API[API FastAPI + LangGraph]
    WEB --> API
    API --> BR[Amazon Bedrock · VPC endpoint]
    EB[EventBridge Scheduler] --> BU[Builder en Fargate]
    BU --> BR
    SM[Secrets Manager] -.-> API
    API -.-> CW[CloudWatch Logs + alarmas SNS]
  end
  API -->|VPN 1433| SQL[(SQL Server del banco)]
  BU -->|VPN 1433| SQL
```

## Infraestructura como código
`deploy/aws/terraform/`, un archivo por tema (red, VPN, seguridad, ALB, ECS, alarmas) y un `.tfvars` por entorno (`demo`, `qa`, `prod`).
Todo se opera con `bash deploy/aws/despliegue.sh <comando> <entorno>`: `bootstrap`, `plan`, `apply`, `deploy`, `rollback`, `logs`,
`secret`, `validate`, `destroy`.

## Servicios de AWS
ECS Fargate, Elastic Load Balancing (ALB), Amazon Bedrock, EventBridge Scheduler, ECR, Secrets Manager, CloudWatch, SNS, KMS y VPC
(endpoints y Site-to-Site VPN).

## Pruebas
`bash deploy/aws/despliegue.sh validate`: `terraform validate` y planes de prueba con el proveedor simulado (`terraform/tests/`).
