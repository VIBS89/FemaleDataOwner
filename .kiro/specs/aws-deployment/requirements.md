# Requisitos: Despliegue en AWS

Spec detallada: [docs/specs/cloud-native/CN-01-despliegue-aws.md](../../../docs/specs/cloud-native/CN-01-despliegue-aws.md).

## Introducción
Ejecutar en AWS el mismo código del piloto, con Amazon Bedrock como LLM, sin que el catálogo, las preguntas ni la auditoría se guarden
en AWS: AWS procesa y muestra; los datos se quedan en el SQL Server del banco.

## Requisito 1: Cómputo y entrada
#### Criterios de aceptación
1. The system SHALL correr la web y la API en una tarea de ECS Fargate con las imágenes de `docker compose`.
2. The system SHALL publicar `/` hacia la web y `/mcp` hacia la API detrás de un ALB con HTTPS; el resto de la API no se publica.
3. WHEN se despliega una versión THEN el sistema SHALL detener la tarea anterior antes de arrancar la nueva (un solo SessionVault).

## Requisito 2: LLM y red
#### Criterios de aceptación
1. The system SHALL invocar Amazon Bedrock por VPC endpoint con el rol de la tarea, sin claves y sin registro de invocaciones.
2. The system SHALL usar subredes privadas sin ruta a internet ni NAT; solo VPC endpoints y la VPN al puerto 1433 del banco.

## Requisito 3: Catálogo programado
#### Criterios de aceptación
1. WHEN llega la hora programada THEN EventBridge Scheduler SHALL lanzar el Builder, que extrae esquemas, los describe con IA y termina.
2. The system SHALL impedir que el rol de la API lea el login de metadatos del Builder.

## Requisito 4: Operación segura
#### Criterios de aceptación
1. The system SHALL guardar los secretos de servicio en Secrets Manager, nunca en el repositorio ni en el estado de Terraform.
2. The system SHALL cifrar los logs con KMS y enviar las alarmas a un tema SNS.
3. The system SHALL guardar las imágenes en ECR con etiquetas inmutables y análisis al subir.
4. IF `DISCOVERY_DATA_AGENT_ENV` es qa o prod y falta un ajuste seguro THEN la API SHALL negarse a arrancar.
