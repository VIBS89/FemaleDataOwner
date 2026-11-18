# F1 — Catalog Builder (ingesta y mapeo) · común

> Revisado el 2026-11-16 (PRD §13, decisiones 9–16).
>
> Infraestructura de ingesta por entorno: **cloud native** → [CN-02](../cloud-native/CN-02-catalogo-memoria.md) · **on-premise** → [OP-02](../on-premise/OP-02-catalogo-memoria.md)

## Historia de usuario
Como **administrador de datos**, quiero que ConverData recorra todas las bases SQL Server configuradas y genere un
catálogo descriptivo, para que los agentes entiendan la estructura sin consultarla en cada pregunta.

## Ambientes y servidores (campos adicionales en `config/databases.yaml`)
La propuesta exige indicar **base de datos, ambiente y servidor** de cada recomendación. El inventario de servidores de F18
(`config/databases.yaml`) se amplía con el ambiente de cada instancia:
```yaml
servers:
  - id: SRVPRDSQL01             # se muestra al usuario como `alias`, nunca el host ni la cadena de conexión
    host: sqlprd01.corp.local
    alias: "SQL Producción Canales"
    environment: produccion     # produccion | qa | desarrollo | dr | otro
    platform: sqlserver         # sqlserver; otras plataformas vía MetadataConnector (F23)
    is_reference: true          # ambiente de referencia para descripciones y búsquedas
    databases: [VBank_ING, Onboarding]
  - id: SRVQASQL01
    host: sqlqa01.corp.local
    alias: "SQL QA Canales"
    environment: qa
    platform: sqlserver
    databases: [VBank_ING]
```
- **Id físico**: `<environment>:<server>.<db>.<schema>.<objeto>` (ej. `produccion:SRVPRDSQL01.VBank_ING.dbo.Users`).
- **`asset_key` lógico**: `<db>.<schema>.<objeto>[.<columna>]`. Agrupa el mismo objeto en todos los ambientes; las descripciones,
  reglas y dueños se asocian al `asset_key`, no a cada copia.
- Si el `schema_hash` de un objeto difiere entre ambientes, el YAML lleva `drift: [{environment, detail}]` (F22 lo muestra como aviso).
- Las búsquedas por defecto priorizan el ambiente con `is_reference: true`.

## Fuentes (las mismas en ambos entornos)
1. **`converdata-discovery`** ([F18](F18-discovery-mcp.md)): MCP propio Apache-2.0 con el login de metadatos. Expone inventario, columnas, FKs, dependencias (también entre BDs), firmas de SPs, estadísticas, Query Store y clasificación de sensibilidad. Cubre, entre otras, estas vistas de catálogo:
   - FKs: `sys.foreign_keys` + `sys.foreign_key_columns`
   - Descripciones: `sys.extended_properties` (`MS_Description`)
   - Stored procedures y parámetros: `sys.procedures` + `sys.parameters`
   - Vistas: `sys.views` + `sys.sql_expression_dependencies`
   - Conteo aproximado de filas: `sys.dm_db_partition_stats`
   - Índices y PKs: `sys.indexes` + `sys.index_columns`
2. **Muestras en memoria** (herramienta `get_sample_rows` de `converdata-discovery`, solo en modo biblioteca y contra la réplica): `SELECT TOP (5)` por tabla y `SELECT DISTINCT TOP (50)` en columnas de baja cardinalidad, sin columnas `pii` ni clasificadas como sensibles. **Solo se usan para que el LLM genere descripciones y se descartan; nunca se escriben** (F17).

> **Estado al 2026-11-17 (Fuentes):** `converdata-discovery` es una biblioteca (`SqlServerMetadata`, `src/converdata/metadata/sqlserver.py`), no un MCP, y el código no lee valores de datos: no existen `get_sample_rows` ni las muestras en memoria. Se cuentan filas con `sys.partitions` (no `sys.dm_db_partition_stats`) y no se resuelven `sys.synonyms` (solo tablas, vistas y procedimientos). Ver [F18](F18-discovery-mcp.md) y [brechas funcionales](../../wiki/brechas-funcionales.md).

## Enriquecimiento con LLM
Lo hace el Catalog Builder (comando batch en Python que corre y termina, separado del servicio interactivo, con llamadas directas por lotes al rol `planner` de F16; on-premise lo lanza el Programador de tareas de Windows, OP-02). Para cada tabla y columna sin `MS_Description` genera:
- `description` (español, una o dos frases)
- `synonyms[]` (términos de negocio)
- `domain` (por ejemplo ventas, inventario, RRHH)
- `pii: bool` (heurística más LLM)

Todo se marca como `generated: true` hasta que un humano lo revise.

Las fuentes de conocimiento no estructurales (diccionarios de datos, documentación, paquetes SSIS, jobs de SQL Agent y reglas de negocio)
se ingieren con F23 y se vinculan a este catálogo por `asset_key`.

> **Estado al 2026-11-17 (Enriquecimiento):** el LLM (`LlmEnricher`, rol `planner`, lotes de 6 tablas, `src/converdata/flows/catalog_build.py`) solo propone `description` y `synonyms` de tablas y columnas. `domain` sale del nombre de la BD (`domain_of`) y `pii` de una expresión regular sobre el nombre de la columna y de `sys.sensitivity_classifications` (`src/converdata/builder/catalog_builder.py`); ninguno lo decide el LLM. Sin `--models` el Builder no enriquece.

## Salida: `<catálogo>/<environment>/<server>/<db>/<schema>.<table>.yaml`
Este es el **formato lógico** de un objeto del catálogo. Se persiste en las tablas del esquema `catalog` de la BD `ConverData`
([OP-02](../on-premise/OP-02-catalogo-memoria.md)), que sigue on-premise también en el despliegue en AWS (PRD §13, decisión 14).
El YAML es el formato de desarrollo, el área de trabajo del Builder y el de exportación (`converdata catalog export`); las reglas sobre
"el YAML" aplican a ambos formatos.
```yaml
id: produccion:SRV01.Ventas.dbo.Pedido
asset_key: Ventas.dbo.Pedido
environment: produccion
server: SRV01
kind: table            # table | view | procedure
database: Ventas
schema: dbo
name: Pedido
description: "Encabezado de pedidos de clientes."
description_source: ms_description   # human | data_dictionary | ms_description | document | generated
reviewed: false
domain: ventas         # el dominio determina los responsables (config/owners.yaml, F24)
synonyms: [orden, venta, compra]
row_count: 1250340
primary_key: [PedidoID]
columns:
  - name: PedidoID
    type: int
    nullable: false
    description: "Identificador del pedido."
  - name: Estado
    type: varchar(20)
    description: "Estado del pedido (abierto, cerrado o cancelado)."
    low_cardinality: true
    pii: false
foreign_keys:
  - columns: [ClienteID]
    ref: Ventas.dbo.Cliente      # asset_key: una FK siempre apunta a la misma BD y ambiente
    ref_columns: [ClienteID]
schema_hash: "sha256:…"
```
> **Estado al 2026-11-17 (Salida):**
> - `drift` no se escribe en el YAML: el aviso se calcula al responder, comparando el `schema_hash` de las copias entre ambientes (`drift_of` en `src/converdata/discovery/engine.py`).
> - `low_cardinality` existe en el modelo pero ningún paso lo calcula (no hay muestras).
> - Un objeto eliminado en la BD se borra del catálogo; no se marca `deprecated: true` (`write_output`; con la BD, la baja queda en el historial).
> - `_database.yaml` no se genera; el cargador solo ignora los archivos que empiezan por `_`.
> - Los procedimientos llevan `parameters` (con `direction` y `has_default`) pero no `result_shape`.
> - `domain` sale del nombre de la BD, no de `config/owners.yaml`; los responsables viven en `curation.steward`.

Para un procedimiento, la salida incluye `parameters[{name, type, direction, has_default}]` y `result_shape` (si se conoce). Los procedimientos **no** se ejecutan durante la ingesta.

Además se genera `_database.yaml` por BD con el resumen, los dominios detectados y el hash global.

## Comandos
- `converdata catalog build [--database Ventas] [--no-llm]`: ingesta completa.
- `converdata catalog refresh`: compara `schema_hash` por objeto y procesa solo lo que cambió. Los objetos eliminados se marcan como `deprecated: true` y salen del índice.
- `converdata catalog review --unreviewed`: lista los objetos pendientes de revisión humana.

Estado: hoy existe `converdata catalog build --config <inventario> --out <dir> [--models <models.yaml>] [--db]`, que también sirve de
refresco (con `--db` parte del catálogo publicado en la BD `ConverData` y publica el resultado; con `--db` y sin `--config` toma el
inventario de la BD, y sin `--out` usa un directorio temporal), `converdata catalog publish` y
`converdata catalog export`, y el mismo caso de uso (`converdata.application.catalog_refresh`) bajo demanda desde Administración (`POST /admin/catalog/build`). `refresh` incremental, `review` y las opciones
`--database` y `--no-llm` están pendientes; la revisión se hace en la vista Curación (F24).

## Reglas
- Nunca sobrescribe campos con `description_source: human`.
- **El YAML nunca contiene valores de datos** (`sample_values` prohibido). El indexador rechaza cualquier YAML que lo tenga.
- Concurrencia limitada (4 tablas en paralelo) y timeout de 30 s por consulta de muestra.

> **Estado al 2026-11-17 (Reglas):** no hay concurrencia de 4 tablas ni consultas de muestra; el timeout de 30 s es por consulta de metadatos y el LLM recibe lotes de 6 tablas (no de 20, como dice "Casos límite"). Si un servidor falla, la ingesta sigue con los demás y conserva lo que ya había de ese servidor (`kept_from_failed`).
- El login de metadatos necesita `VIEW DEFINITION` y el `SELECT` mínimo para las muestras; nunca escritura.

## Criterios de aceptación
1. Contra AdventureWorks, `build` produce un YAML por tabla, vista y SP, con FKs correctas (verificado con `sys.foreign_keys`).
2. Un segundo `refresh` sin cambios en la BD no llama al LLM ni reescribe archivos.
3. Si se añade una columna en la BD, `refresh` solo regenera ese YAML.
4. Ningún YAML contiene valores de datos (test automatizado).
5. Si un servidor no responde, la ingesta continúa con los demás y deja un aviso en el log.
6. Tras F1 se ejecuta el pipeline de descubrimiento entre BDs ([F19](F19-multi-db-discovery.md)).

## Casos límite
- Nombres con espacios o caracteres especiales: se citan siempre con `[]`.
- Sinónimos de SQL Server (`sys.synonyms`): se resuelven a su objeto base.
- Tablas temporales del sistema y esquemas `sys`/`INFORMATION_SCHEMA`: se excluyen.
- Más de 1 000 columnas en total en una BD: el enriquecimiento con LLM se hace por lotes de 20 tablas.
