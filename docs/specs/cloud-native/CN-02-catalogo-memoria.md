# CN-02 — Catálogo e ingesta + memoria semántica · cloud native

> Implementa en AWS: [F1](../comun/F01-catalog-builder.md) y [F2](../comun/F02-semantic-memory.md)

## Ingesta
| Pieza | Servicio |
|---|---|
| Disparo | **EventBridge Scheduler** (nocturno) y **Step Functions** (bajo demanda) |
| Catalog Builder | Tarea **ECS Fargate** en subred privada; LLM vía Bedrock (VPC endpoint) |
| `converdata-discovery` (F18) | Biblioteca dentro de la tarea del Catalog Builder (o servicio ECS privado); login de metadatos y sal MinHash en Secrets Manager |
| Descubrimiento entre BDs (F19) | Misma tarea ECS, tras F1; el grafo `_estate/` y la capa semántica `_semantic/` (F21) se guardan en S3 junto al catálogo |
| Catálogo fuente | **S3 versionado** (`s3://converdata-catalog/`), cifrado KMS, **solo metadatos estructurales** |
| Indexación | El evento `s3:ObjectCreated` dispara el indexador, que rechaza YAML con valores y escribe en OpenSearch |
| Red hacia SQL Server | Transit Gateway + VPN/DX (CN-01); el firewall on-prem abre el 1433 solo a la subred del Catalog Builder |

## Memoria semántica: `OpenSearchStore`
- Colección **OpenSearch Serverless** de tipo *vector search*, con endpoint VPC y cifrado KMS.
- Un índice por colección lógica (`tables`, `columns`, `glossary`, `golden_sql`) con un campo `knn_vector` (dimensión según el rol `embed`) y los metadatos como `keyword`.
- Búsqueda **híbrida**: k-NN y BM25 combinados con un `search_pipeline` de normalización. El filtro de permisos es un `terms` sobre `id` (pre-filtro).
- `golden_sql` contiene solo plantillas anonimizadas; el original vive en `ConverData_Audit` on-prem (CN-05).

## Criterios de aceptación
1. Un cambio de esquema on-prem aparece en OpenSearch tras el siguiente ciclo nocturno sin intervención manual.
2. Un YAML con valores subido a S3 es rechazado por el indexador y genera una alarma.
3. Los tests de contrato de `VectorStore` pasan contra `OpenSearchStore`.
