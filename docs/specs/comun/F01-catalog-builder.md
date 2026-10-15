# F1 — Catalog Builder (ingesta y mapeo) · común

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
1. **sql-to-mcp / AnythingMCP** (HTTP `:4000/mcp`, login de metadatos): `mssql_list_tables`, `mssql_describe_table`, `mssql_find_columns`.
2. **Consultas directas a `sys.*`** (mismo login de metadatos), para lo que sql-to-mcp no expone:
   - FKs: `sys.foreign_keys` + `sys.foreign_key_columns`
   - Descripciones: `sys.extended_properties` (`MS_Description`)
   - Stored procedures y parámetros: `sys.procedures` + `sys.parameters`
   - Vistas: `sys.views` + `sys.sql_expression_dependencies`
   - Conteo aproximado de filas: `sys.dm_db_partition_stats`
   - Índices y PKs: `sys.indexes` + `sys.index_columns`
3. **Muestras en memoria**: `SELECT TOP (5)` por tabla y `SELECT DISTINCT TOP (50)` en columnas de baja cardinalidad. **Solo se usan para que el LLM genere descripciones y se descartan; nunca se escriben** (F17).

## Enriquecimiento con LLM
Lo hace el CatalogBuilder Crew con el rol `planner` de F16. Para cada tabla y columna sin `MS_Description` genera:
- `description` (español, una o dos frases)
- `synonyms[]` (términos de negocio)
- `domain` (por ejemplo ventas, inventario, RRHH)
- `pii: bool` (heurística más LLM)

Todo se marca como `generated: true` hasta que un humano lo revise.

Las fuentes de conocimiento no estructurales (diccionarios de datos, documentación, paquetes SSIS, jobs de SQL Agent y reglas de negocio)
se ingieren con F23 y se vinculan a este catálogo por `asset_key`.

## Salida: `<catálogo>/<environment>/<server>/<db>/<schema>.<table>.yaml`
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
    ref: SRV01.Ventas.dbo.Cliente
    ref_columns: [ClienteID]
schema_hash: "sha256:…"
```
Para un procedimiento, la salida incluye `parameters[{name, type, direction, has_default}]` y `result_shape` (si se conoce). Los procedimientos **no** se ejecutan durante la ingesta.

Además se genera `_database.yaml` por BD con el resumen, los dominios detectados y el hash global.

## Comandos
- `converdata catalog build [--db Ventas] [--no-llm]`: ingesta completa.
- `converdata catalog refresh`: compara `schema_hash` por objeto y procesa solo lo que cambió. Los objetos eliminados se marcan como `deprecated: true` y salen del índice.
- `converdata catalog review --unreviewed`: lista los objetos pendientes de revisión humana.

## Reglas
- Nunca sobrescribe campos con `description_source: human`.
- **El YAML nunca contiene valores de datos** (`sample_values` prohibido). El indexador rechaza cualquier YAML que lo tenga.
- Concurrencia limitada (4 tablas en paralelo) y timeout de 30 s por consulta de muestra.
- El login de metadatos necesita `VIEW DEFINITION` y el `SELECT` mínimo para las muestras; nunca escritura.

## Criterios de aceptación
1. Contra AdventureWorks, `build` produce un YAML por tabla, vista y SP, con FKs correctas (verificado con `sys.foreign_keys`).
2. Un segundo `refresh` sin cambios en la BD no llama al LLM ni reescribe archivos.
3. Si se añade una columna en la BD, `refresh` solo regenera ese YAML.
4. Ningún YAML contiene valores de datos (test automatizado).
5. Si sql-to-mcp no está disponible, la ingesta continúa solo con `sys.*` y deja un aviso en el log.

## Casos límite
- Nombres con espacios o caracteres especiales: se citan siempre con `[]`.
- Sinónimos de SQL Server (`sys.synonyms`): se resuelven a su objeto base.
- Tablas temporales del sistema y esquemas `sys`/`INFORMATION_SCHEMA`: se excluyen.
- Más de 1 000 columnas en total en una BD: el enriquecimiento con LLM se hace por lotes de 20 tablas.
