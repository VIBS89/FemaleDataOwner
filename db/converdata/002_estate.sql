/* Esquema estate: grafo del patrimonio de datos entre BDs y servidores (F19, OP-02).
   Tablas de grafo (AS NODE / AS EDGE) consultables con MATCH y SHORTEST_PATH.
   - Los sketches MinHash NO se guardan: solo viven en memoria durante el job (OP-02, HU-07). Se guarda la arista y su confianza.
   - Las tablas de grafo de SQL Server no admiten SYSTEM_VERSIONING: la trazabilidad de la revisión humana va en
     reviewed_by / updated_at de cada fila (la validación en SQL Server real es el CA de HU-05/HU-07 en SD-3). */

CREATE SCHEMA estate;
GO

/* Concepto de negocio (Cliente, Producto, Pedido) y su tabla canónica. */
CREATE TABLE estate.entity (
    name                nvarchar(200)  NOT NULL,
    definition          nvarchar(2000) NULL,
    domain              nvarchar(100)  NULL,
    synonyms_json       nvarchar(max)  NULL CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),
    canonical_asset_key nvarchar(400)  NULL,                 -- <db>.<schema>.<obj>
    reviewed            bit            NOT NULL DEFAULT 0,
    reviewed_by         nvarchar(200)  NULL,
    updated_at          datetime2      NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_estate_entity_name UNIQUE (name)
) AS NODE;

/* Tabla lógica (todas sus copias por ambiente comparten asset_key; el detalle físico vive en catalog.object). */
CREATE TABLE estate.table_ref (
    asset_key     nvarchar(400) NOT NULL,                    -- <db>.<schema>.<obj>
    database_name sysname       NOT NULL,
    schema_name   sysname       NOT NULL,
    object_name   sysname       NOT NULL,
    updated_at    datetime2     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_estate_table_ref_asset UNIQUE (asset_key)
) AS NODE;
GO

/* Una sola tabla de aristas con el tipo en `kind` (F19): MATCH filtra por tipo y SHORTEST_PATH atraviesa todos. */
CREATE TABLE estate.relation (
    kind          varchar(24)   NOT NULL
        CHECK (kind IN ('same_entity','fk_declared','view_join','proc_join','cross_db_reference',
                        'query_store_join','inferred_inclusion','etl')),
    confidence    decimal(3,2)  NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_json nvarchar(max) NOT NULL CHECK (ISJSON(evidence_json) = 1),   -- evidencias; nunca valores de datos
    via_json      nvarchar(max) NULL CHECK (via_json IS NULL OR ISJSON(via_json) = 1),  -- etl: paquete SSIS, job o SP
    reviewed      bit           NOT NULL DEFAULT 0,
    reviewed_by   nvarchar(200) NULL,
    updated_at    datetime2     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT ec_estate_relation CONNECTION (estate.entity TO estate.table_ref, estate.table_ref TO estate.table_ref)
) AS EDGE;
GO
