/* BD de trabajo ConverData (SQL Server 2025) — OP-02, OP-05.
   Esquemas: catalog, knowledge, golden, curation, audit (estate y semantic llegan con F19/F21).
   El catálogo nunca guarda valores de datos (F1, F17). */

CREATE SCHEMA catalog;
GO
CREATE SCHEMA knowledge;
GO
CREATE SCHEMA golden;
GO
CREATE SCHEMA curation;
GO
CREATE SCHEMA audit;
GO

/* ---------- catalog: una fila por copia física (ambiente + servidor) ---------- */
CREATE TABLE catalog.object (
    physical_id        nvarchar(400) NOT NULL PRIMARY KEY,   -- <env>:<server>.<db>.<schema>.<obj>
    asset_key          nvarchar(400) NOT NULL,               -- <db>.<schema>.<obj>
    environment        nvarchar(20)  NOT NULL,
    server_id          nvarchar(100) NOT NULL,
    kind               nvarchar(10)  NOT NULL CHECK (kind IN ('table','view','procedure')),
    database_name      sysname       NOT NULL,
    schema_name        sysname       NOT NULL,
    object_name        sysname       NOT NULL,
    description        nvarchar(2000) NULL,
    description_source nvarchar(20)  NOT NULL
        CHECK (description_source IN ('human','data_dictionary','ms_description','document','generated')),
    reviewed           bit           NOT NULL DEFAULT 0,
    reviewed_by_group  nvarchar(200) NULL,
    domain             nvarchar(100) NULL,
    synonyms_json      nvarchar(max) NULL CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),
    row_count          bigint        NULL,
    schema_hash        varchar(80)   NULL,
    deprecated         bit           NOT NULL DEFAULT 0,
    valid_from         datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to           datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = catalog.object_history));
CREATE INDEX ix_object_asset ON catalog.object (asset_key);
GO

CREATE TABLE catalog.[column] (
    physical_id        nvarchar(400) NOT NULL REFERENCES catalog.object(physical_id),
    column_name        sysname       NOT NULL,
    ordinal            int           NOT NULL,
    data_type          nvarchar(128) NOT NULL,
    nullable           bit           NOT NULL,
    description        nvarchar(2000) NULL,
    description_source nvarchar(20)  NOT NULL,
    reviewed           bit           NOT NULL DEFAULT 0,
    synonyms_json      nvarchar(max) NULL,
    low_cardinality    bit           NOT NULL DEFAULT 0,
    pii                bit           NOT NULL DEFAULT 0,
    valid_from         datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to           datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to),
    CONSTRAINT pk_column PRIMARY KEY (physical_id, column_name)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = catalog.column_history));
GO

CREATE TABLE catalog.foreign_key (
    physical_id  nvarchar(400) NOT NULL REFERENCES catalog.object(physical_id),
    fk_name      sysname       NOT NULL,
    columns_json nvarchar(max) NOT NULL,
    ref_asset    nvarchar(400) NOT NULL,
    ref_columns_json nvarchar(max) NOT NULL,
    CONSTRAINT pk_fk PRIMARY KEY (physical_id, fk_name)
);
GO

/* Documentos indexables por asset_key (un documento por activo lógico, no por ambiente; F2).
   access_ids: ids físicos que dan acceso (JSON), para el pre-filtro de visible_ids. */
CREATE TABLE catalog.search_doc (
    doc_id      int IDENTITY CONSTRAINT pk_search_doc PRIMARY KEY,
    collection  varchar(20)   NOT NULL CHECK (collection IN ('tables','columns')),
    asset_key   nvarchar(400) NOT NULL,
    database_name sysname     NOT NULL,
    content     nvarchar(4000) NOT NULL,
    access_ids  nvarchar(max) NOT NULL CHECK (ISJSON(access_ids) = 1),
    embedding   VECTOR(1024)  NULL,
    embed_model varchar(100)  NULL,
    CONSTRAINT uq_search_doc UNIQUE (collection, asset_key)
);
GO
CREATE TABLE catalog.search_doc_access (       -- forma relacional de access_ids, para filtrar con JOIN
    doc_id      int           NOT NULL REFERENCES catalog.search_doc(doc_id) ON DELETE CASCADE,
    physical_id nvarchar(400) NOT NULL,
    CONSTRAINT pk_search_doc_access PRIMARY KEY (doc_id, physical_id)
);
GO

/* ---------- knowledge: fragmentos redactados, reglas, linaje y golden discovery (F23, F24) ---------- */
CREATE TABLE knowledge.item (
    item_id      nvarchar(200) NOT NULL CONSTRAINT pk_item PRIMARY KEY,
    kind         varchar(20)   NOT NULL
        CHECK (kind IN ('glossary','business_rule','document','annotation','etl','data_dictionary')),
    content      nvarchar(4000) NOT NULL,            -- ya redactado (Presidio) antes de escribir
    source       nvarchar(400) NOT NULL,
    domain       nvarchar(100) NULL,
    linked_assets_json nvarchar(max) NOT NULL CHECK (ISJSON(linked_assets_json) = 1),
    allowed_groups_json nvarchar(max) NULL,           -- NULL = sin ACL de origen
    reviewed     bit           NOT NULL DEFAULT 0,
    redacted     bit           NOT NULL DEFAULT 0,
    source_hash  varchar(80)   NULL,
    embedding    VECTOR(1024)  NULL,
    embed_model  varchar(100)  NULL,
    valid_from   datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to     datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = knowledge.item_history));
GO
CREATE TABLE knowledge.item_asset (               -- linked_assets en forma relacional (filtro F14: todos visibles)
    item_id     nvarchar(200) NOT NULL REFERENCES knowledge.item(item_id),
    asset_key   nvarchar(400) NOT NULL,
    table_key   nvarchar(400) NOT NULL,              -- <db>.<schema>.<tabla>, para el filtro de visibilidad
    method      varchar(10)   NOT NULL,
    score       float         NOT NULL,
    CONSTRAINT pk_item_asset PRIMARY KEY (item_id, asset_key)
);
GO
CREATE TABLE knowledge.golden_discovery (          -- plantillas anonimizadas (D4)
    golden_id      nvarchar(100) NOT NULL CONSTRAINT pk_golden_discovery PRIMARY KEY,
    template       nvarchar(1000) NOT NULL,
    asset_keys_json nvarchar(max) NOT NULL CHECK (ISJSON(asset_keys_json) = 1),
    confirmed_by   varchar(10)   NOT NULL CHECK (confirmed_by IN ('steward','users')),
    confirmations  int           NOT NULL DEFAULT 1,
    rejected       bit           NOT NULL DEFAULT 0,
    embedding      VECTOR(1024)  NULL,
    created_at     datetime2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

/* Full-Text en español sobre los textos indexables (componente léxico de la búsqueda híbrida). */
CREATE FULLTEXT CATALOG ft_converdata AS DEFAULT;
GO
CREATE FULLTEXT INDEX ON catalog.search_doc (content LANGUAGE 3082) KEY INDEX pk_search_doc WITH CHANGE_TRACKING AUTO;
CREATE FULLTEXT INDEX ON knowledge.item (content LANGUAGE 3082) KEY INDEX pk_item WITH CHANGE_TRACKING AUTO;
CREATE FULLTEXT INDEX ON knowledge.golden_discovery (template LANGUAGE 3082) KEY INDEX pk_golden_discovery WITH CHANGE_TRACKING AUTO;
GO

/* ---------- golden y curation: contienen D2 (preguntas), solo on-premise ---------- */
CREATE TABLE golden.golden_discovery_original (
    golden_id   nvarchar(100) NOT NULL PRIMARY KEY REFERENCES knowledge.golden_discovery(golden_id),
    question    nvarchar(2000) NOT NULL,
    created_at  datetime2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE curation.owners (
    domain          nvarchar(100) NOT NULL PRIMARY KEY,
    assets_json     nvarchar(max) NOT NULL,
    business_owner  nvarchar(200) NULL, business_group  nvarchar(200) NULL,
    technical_owner nvarchar(200) NULL, technical_group nvarchar(200) NULL
);
CREATE TABLE curation.user_directory (
    sql_login   sysname       NOT NULL PRIMARY KEY,
    ad_account  nvarchar(200) NOT NULL,
    user_group  nvarchar(50)  NULL          -- perfil para las métricas de F25
);
CREATE TABLE curation.curation_request (
    id              uniqueidentifier NOT NULL PRIMARY KEY DEFAULT NEWID(),
    trace_id        uniqueidentifier NOT NULL,
    ts              datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
    domain          nvarchar(100) NULL,
    assigned_group  nvarchar(200) NULL,
    question        nvarchar(2000) NOT NULL,
    status          varchar(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','no_source','closed')),
    answer_kind     varchar(20) NULL,
    answered_at     datetime2 NULL,
    answered_by_group nvarchar(200) NULL
);
GO

/* ---------- audit (F11): el escritor solo tiene INSERT ---------- */
CREATE TABLE audit.audit_question (
    trace_id   uniqueidentifier NOT NULL PRIMARY KEY,
    ts         datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
    user_id    sysname NOT NULL, sql_login sysname NULL, user_group nvarchar(50) NULL,
    client     varchar(5) NOT NULL CHECK (client IN ('ui','api','mcp','cli')),
    flow       varchar(10) NOT NULL CHECK (flow IN ('discover','ask')),
    question   nvarchar(2000) NOT NULL, rewritten_question nvarchar(2000) NULL,
    intent     varchar(20) NULL, databases_json nvarchar(max) NULL,
    status     varchar(25) NOT NULL, confidence float NULL, total_ms int NULL
);
CREATE TABLE audit.audit_step (
    id         bigint IDENTITY PRIMARY KEY,
    trace_id   uniqueidentifier NOT NULL REFERENCES audit.audit_question(trace_id),
    step       varchar(20) NOT NULL, attempt int NOT NULL, started_at datetime2 NOT NULL, duration_ms int NOT NULL,
    model      nvarchar(200) NULL, prompt_tokens int NULL, completion_tokens int NULL,
    ok         bit NOT NULL, error nvarchar(400) NULL
);
CREATE TABLE audit.audit_discovery (
    id          bigint IDENTITY PRIMARY KEY,
    trace_id    uniqueidentifier NOT NULL REFERENCES audit.audit_question(trace_id),
    rank        int NULL, asset_key nvarchar(800) NOT NULL, environment nvarchar(20) NULL,
    confidence  float NULL, description_source varchar(20) NULL,
    kind        varchar(12) NOT NULL CHECK (kind IN ('candidate','alternative','related'))
);
CREATE TABLE audit.audit_discovery_feedback (
    id          bigint IDENTITY PRIMARY KEY,
    trace_id    uniqueidentifier NOT NULL REFERENCES audit.audit_question(trace_id),
    ts          datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
    asset_key   nvarchar(400) NOT NULL,
    verdict     varchar(12) NOT NULL CHECK (verdict IN ('confirm','reject','correct_is')),
    correct_asset_key nvarchar(400) NULL,
    actor_role  varchar(10) NOT NULL CHECK (actor_role IN ('consumer','steward')),
    time_to_verdict_ms int NULL
);
GO

/* Rol del servicio ConverData-API (gMSA): F11 permisos del escritor. */
CREATE ROLE converdata_app;
GRANT SELECT ON SCHEMA::catalog   TO converdata_app;
GRANT SELECT ON SCHEMA::knowledge TO converdata_app;
GRANT INSERT ON SCHEMA::audit     TO converdata_app;
GRANT SELECT, INSERT, UPDATE ON knowledge.golden_discovery TO converdata_app;
GRANT SELECT, INSERT, UPDATE ON curation.curation_request  TO converdata_app;
GRANT SELECT ON curation.owners TO converdata_app;
GRANT SELECT ON curation.user_directory TO converdata_app;
DENY UPDATE, DELETE ON SCHEMA::audit TO converdata_app;
GO
