/* BD de trabajo ConverData — OP-02, OP-05. SQL Server 2016 o posterior (PRD §13, decisión 10).

   Solo tablas normales y temporales: sin VECTOR, Full-Text ni tablas de grafo. La búsqueda es un índice léxico en la
   memoria de ConverData-API, que se reconstruye desde estas tablas (decisión 9).
   El catálogo nunca guarda valores de datos (F1, F17). Las preguntas (D2) solo viven en `audit`, `golden` y `curation`.

   Lo aplica `converdata db migrate`, que parte el archivo por lotes `GO`, lo ejecuta en una transacción y lo registra en
   `dbo.schema_version`. No editar un script ya aplicado: los cambios van en un script nuevo (OP-07 §Migraciones). */

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

/* ---------- catalog ---------- */

/* Inventario de servidores (F1, F18). `host` no se muestra nunca al usuario; aquí no hay credenciales. */
CREATE TABLE catalog.server (
    server_id      nvarchar(100) NOT NULL CONSTRAINT pk_server PRIMARY KEY,
    alias          nvarchar(200) NOT NULL,
    environment    nvarchar(20)  NOT NULL,
    platform       nvarchar(20)  NOT NULL CONSTRAINT df_server_platform DEFAULT 'sqlserver',
    is_reference   bit           NOT NULL CONSTRAINT df_server_ref DEFAULT 0,
    config_json    nvarchar(max) NOT NULL CONSTRAINT ck_server_json CHECK (ISJSON(config_json) = 1)
);
GO

/* Una fila por copia física (ambiente + servidor). Tabla temporal: historial de cada cambio (RF-34). */
CREATE TABLE catalog.object (
    physical_id        nvarchar(400) NOT NULL CONSTRAINT pk_object PRIMARY KEY,   -- <env>:<server>.<db>.<schema>.<obj>
    asset_key          nvarchar(400) NOT NULL,                                    -- <db>.<schema>.<obj>
    environment        nvarchar(20)  NOT NULL,
    server_id          nvarchar(100) NOT NULL,
    kind               nvarchar(10)  NOT NULL CONSTRAINT ck_object_kind CHECK (kind IN ('table','view','procedure')),
    database_name      sysname       NOT NULL,
    schema_name        sysname       NOT NULL,
    object_name        sysname       NOT NULL,
    description        nvarchar(max) NULL,
    description_source nvarchar(20)  NOT NULL
        CONSTRAINT ck_object_source CHECK (description_source IN ('human','data_dictionary','ms_description','document','generated')),
    reviewed           bit           NOT NULL CONSTRAINT df_object_reviewed DEFAULT 0,
    domain             nvarchar(100) NULL,
    synonyms_json      nvarchar(max) NOT NULL CONSTRAINT ck_object_syn CHECK (ISJSON(synonyms_json) = 1),
    row_count          bigint        NULL,
    primary_key_json   nvarchar(max) NOT NULL CONSTRAINT ck_object_pk CHECK (ISJSON(primary_key_json) = 1),
    parameters_json    nvarchar(max) NOT NULL CONSTRAINT ck_object_par CHECK (ISJSON(parameters_json) = 1),
    drift_json         nvarchar(max) NOT NULL CONSTRAINT ck_object_drift CHECK (ISJSON(drift_json) = 1),
    schema_hash        varchar(80)   NULL,
    deprecated         bit           NOT NULL CONSTRAINT df_object_deprecated DEFAULT 0,
    modified_by        nvarchar(128) NOT NULL,                                    -- quién escribió esta versión
    valid_from         datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to           datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = catalog.object_history));
GO
CREATE INDEX ix_object_asset ON catalog.object (asset_key);
GO

CREATE TABLE catalog.[column] (
    physical_id        nvarchar(400) NOT NULL CONSTRAINT fk_column_object REFERENCES catalog.object(physical_id),
    column_name        sysname       NOT NULL,
    ordinal            int           NOT NULL,
    data_type          nvarchar(128) NOT NULL,
    nullable           bit           NOT NULL,
    description        nvarchar(max) NULL,
    description_source nvarchar(20)  NOT NULL
        CONSTRAINT ck_column_source CHECK (description_source IN ('human','data_dictionary','ms_description','document','generated')),
    reviewed           bit           NOT NULL CONSTRAINT df_column_reviewed DEFAULT 0,
    synonyms_json      nvarchar(max) NOT NULL CONSTRAINT ck_column_syn CHECK (ISJSON(synonyms_json) = 1),
    low_cardinality    bit           NOT NULL CONSTRAINT df_column_lowcard DEFAULT 0,
    pii                bit           NOT NULL CONSTRAINT df_column_pii DEFAULT 0,
    modified_by        nvarchar(128) NOT NULL,
    valid_from         datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to           datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to),
    CONSTRAINT pk_column PRIMARY KEY (physical_id, column_name)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = catalog.column_history));
GO

CREATE TABLE catalog.foreign_key (
    physical_id      nvarchar(400) NOT NULL CONSTRAINT fk_fk_object REFERENCES catalog.object(physical_id),
    ordinal          int           NOT NULL,
    columns_json     nvarchar(max) NOT NULL CONSTRAINT ck_fk_cols CHECK (ISJSON(columns_json) = 1),
    ref_asset        nvarchar(400) NOT NULL,
    ref_columns_json nvarchar(max) NOT NULL CONSTRAINT ck_fk_ref CHECK (ISJSON(ref_columns_json) = 1),
    CONSTRAINT pk_foreign_key PRIMARY KEY (physical_id, ordinal)
);
GO

/* Cada publicación del catálogo o del conocimiento sube la versión; ConverData-API la consulta para recargar su índice. */
CREATE TABLE catalog.catalog_version (
    version       bigint IDENTITY CONSTRAINT pk_catalog_version PRIMARY KEY,
    published_at  datetime2     NOT NULL CONSTRAINT df_version_at DEFAULT SYSUTCDATETIME(),
    published_by  nvarchar(128) NOT NULL,
    reason        nvarchar(60)  NOT NULL,          -- build | curation | dictionary | feedback | import
    objects       int           NULL,
    columns       int           NULL
);
GO

/* ---------- knowledge: fragmentos ya redactados, reglas, linaje, entidades y golden discovery (F19, F23, F24) ---------- */
CREATE TABLE knowledge.item (
    item_id      nvarchar(300) NOT NULL CONSTRAINT pk_item PRIMARY KEY,
    kind         varchar(20)   NOT NULL
        CONSTRAINT ck_item_kind CHECK (kind IN ('glossary','business_rule','document','annotation','etl','data_dictionary')),
    content      nvarchar(max) NOT NULL,             -- redactado antes de escribir (F23)
    source       nvarchar(400) NOT NULL,
    domain       nvarchar(100) NULL,
    linked_assets_json  nvarchar(max) NOT NULL CONSTRAINT ck_item_links CHECK (ISJSON(linked_assets_json) = 1),
    allowed_groups_json nvarchar(max) NULL CONSTRAINT ck_item_groups CHECK (allowed_groups_json IS NULL OR ISJSON(allowed_groups_json) = 1),
    reviewed     bit           NOT NULL CONSTRAINT df_item_reviewed DEFAULT 0,
    redacted     bit           NOT NULL CONSTRAINT df_item_redacted DEFAULT 0,
    modified_by  nvarchar(128) NOT NULL,
    valid_from   datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to     datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = knowledge.item_history));
GO

CREATE TABLE knowledge.business_rule (
    rule_id      nvarchar(100) NOT NULL CONSTRAINT pk_rule PRIMARY KEY,
    content      nvarchar(max) NOT NULL,
    domain       nvarchar(100) NULL,
    applies_to_json nvarchar(max) NOT NULL CONSTRAINT ck_rule_assets CHECK (ISJSON(applies_to_json) = 1),
    source       nvarchar(400) NULL,
    owner        nvarchar(200) NULL,
    reviewed     bit           NOT NULL CONSTRAINT df_rule_reviewed DEFAULT 0,
    modified_by  nvarchar(128) NOT NULL,
    valid_from   datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to     datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = knowledge.business_rule_history));
GO

/* Aristas `etl` a nivel de tabla. El grafo del patrimonio se arma en memoria con estas filas y las FKs (F19). */
CREATE TABLE knowledge.lineage_edge (
    edge_id      int IDENTITY  CONSTRAINT pk_lineage PRIMARY KEY,
    from_asset   nvarchar(400) NOT NULL,
    to_asset     nvarchar(400) NOT NULL,
    via_kind     varchar(20)   NOT NULL CONSTRAINT ck_lineage_kind CHECK (via_kind IN ('ssis','agent_job','procedure','view')),
    via_name     nvarchar(300) NOT NULL,
    via_job      nvarchar(300) NULL,
    via_schedule nvarchar(200) NULL,
    edge_level   varchar(10)   NOT NULL CONSTRAINT ck_lineage_level CHECK (edge_level IN ('table','column'))
);
GO

/* Entidades de negocio: dónde vive un concepto entre BDs (aristas `same_entity`). */
CREATE TABLE knowledge.business_entity (
    entity_name  nvarchar(200) NOT NULL CONSTRAINT pk_entity PRIMARY KEY,
    synonyms_json nvarchar(max) NOT NULL CONSTRAINT ck_entity_syn CHECK (ISJSON(synonyms_json) = 1),
    definition   nvarchar(max) NULL,
    tables_json  nvarchar(max) NOT NULL CONSTRAINT ck_entity_tables CHECK (ISJSON(tables_json) = 1),
    canonical    nvarchar(400) NULL,
    domain       nvarchar(100) NULL
);
GO

/* Preguntas confirmadas (F24). `template` es hoy la pregunta normalizada (minúsculas, sin tildes ni puntuación), no una
   plantilla anonimizada: es D2, y por eso el Builder no la lee ni se exporta. La API no guarda una confirmación cuya
   pregunta parezca contener datos personales. */
CREATE TABLE knowledge.golden_discovery (
    golden_id       nvarchar(100) NOT NULL CONSTRAINT pk_golden_discovery PRIMARY KEY,
    template        nvarchar(2000) NOT NULL,
    asset_keys_json nvarchar(max) NOT NULL CONSTRAINT ck_golden_assets CHECK (ISJSON(asset_keys_json) = 1),
    confirmed_by    varchar(10)   NOT NULL CONSTRAINT ck_golden_by CHECK (confirmed_by IN ('steward','users')),
    confirmations   int           NOT NULL CONSTRAINT df_golden_conf DEFAULT 1,
    rejected        bit           NOT NULL CONSTRAINT df_golden_rej DEFAULT 0,
    created_at      datetime2     NOT NULL CONSTRAINT df_golden_at DEFAULT SYSUTCDATETIME()
);
GO

/* ---------- golden y curation: contienen preguntas (D2) ---------- */
CREATE TABLE golden.golden_discovery_original (
    golden_id   nvarchar(100) NOT NULL CONSTRAINT pk_golden_original PRIMARY KEY
        CONSTRAINT fk_golden_original REFERENCES knowledge.golden_discovery(golden_id) ON DELETE CASCADE,
    question    nvarchar(2000) NOT NULL,
    created_at  datetime2 NOT NULL CONSTRAINT df_golden_orig_at DEFAULT SYSUTCDATETIME()
);
GO

/* Responsables por dominio (F24). `assets_json`: patrones de asset_key del dominio. */
CREATE TABLE curation.owners (
    domain          nvarchar(100) NOT NULL CONSTRAINT pk_owners PRIMARY KEY,
    assets_json     nvarchar(max) NOT NULL CONSTRAINT ck_owners_assets CHECK (ISJSON(assets_json) = 1),
    business_owner  nvarchar(200) NULL,
    business_group  nvarchar(200) NULL,
    technical_owner nvarchar(200) NULL,
    technical_group nvarchar(200) NULL
);
GO

/* ---------- audit (F11): solo se inserta; la purga es un procedimiento con su propio rol ---------- */
CREATE TABLE audit.audit_question (
    trace_id   uniqueidentifier NOT NULL CONSTRAINT pk_audit_question PRIMARY KEY NONCLUSTERED,
    ts         datetime2     NOT NULL CONSTRAINT df_question_ts DEFAULT SYSUTCDATETIME(),
    user_id    nvarchar(128) NOT NULL,
    client     varchar(20)   NOT NULL,
    flow       varchar(10)   NOT NULL CONSTRAINT ck_question_flow CHECK (flow IN ('discover','ask')),
    question   nvarchar(2000) NOT NULL,
    intent     varchar(30)   NULL,
    databases_json nvarchar(max) NULL,
    status     varchar(25)   NOT NULL,
    confidence float         NULL,
    total_ms   int           NULL
);
GO
CREATE CLUSTERED INDEX cx_audit_question_ts ON audit.audit_question (ts);
CREATE INDEX ix_audit_question_user ON audit.audit_question (user_id, ts);
GO

CREATE TABLE audit.audit_step (
    id         bigint IDENTITY CONSTRAINT pk_audit_step PRIMARY KEY,
    trace_id   uniqueidentifier NOT NULL CONSTRAINT fk_step_question REFERENCES audit.audit_question(trace_id),
    step       varchar(20)   NOT NULL,
    attempt    int           NOT NULL,
    started_at datetime2     NOT NULL,
    duration_ms int          NOT NULL,
    model      nvarchar(200) NULL,
    ok         bit           NOT NULL,
    error      nvarchar(400) NULL,
    detail     nvarchar(200) NULL
);
GO
CREATE INDEX ix_audit_step_trace ON audit.audit_step (trace_id);
GO

CREATE TABLE audit.audit_discovery (
    id          bigint IDENTITY CONSTRAINT pk_audit_discovery PRIMARY KEY,
    trace_id    uniqueidentifier NOT NULL CONSTRAINT fk_discovery_question REFERENCES audit.audit_question(trace_id),
    rank        int           NULL,
    asset_key   nvarchar(850) NOT NULL,              -- las relaciones se guardan como "<origen>-><destino>"
    environment nvarchar(20)  NULL,
    confidence  float         NULL,
    description_source varchar(20) NULL,
    kind        varchar(12)   NOT NULL CONSTRAINT ck_discovery_kind CHECK (kind IN ('candidate','alternative','related'))
);
GO
CREATE INDEX ix_audit_discovery_trace ON audit.audit_discovery (trace_id);
GO

CREATE TABLE audit.audit_discovery_feedback (
    id          bigint IDENTITY CONSTRAINT pk_audit_feedback PRIMARY KEY,
    trace_id    uniqueidentifier NOT NULL CONSTRAINT fk_feedback_question REFERENCES audit.audit_question(trace_id),
    ts          datetime2     NOT NULL CONSTRAINT df_feedback_ts DEFAULT SYSUTCDATETIME(),
    user_id     nvarchar(128) NULL,
    asset_key   nvarchar(400) NOT NULL,
    verdict     varchar(12)   NOT NULL CONSTRAINT ck_feedback_verdict CHECK (verdict IN ('confirm','reject','correct_is')),
    correct_asset_key nvarchar(400) NULL,
    actor_role  varchar(10)   NOT NULL CONSTRAINT ck_feedback_role CHECK (actor_role IN ('consumer','steward')),
    time_to_verdict_ms int    NULL
);
GO
CREATE INDEX ix_audit_feedback_trace ON audit.audit_discovery_feedback (trace_id);
GO

/* Eventos de la API que no son preguntas: inicios de sesión, accesos denegados, cambios de curación e inventario,
   lecturas de la auditoría, construcciones del catálogo. `data_json` nunca lleva contraseñas ni tokens. */
CREATE TABLE audit.audit_event (
    id         bigint IDENTITY CONSTRAINT pk_audit_event PRIMARY KEY NONCLUSTERED,
    ts         datetime2     NOT NULL CONSTRAINT df_event_ts DEFAULT SYSUTCDATETIME(),
    kind       varchar(60)   NOT NULL,
    user_id    nvarchar(128) NULL,
    trace_id   uniqueidentifier NULL,
    data_json  nvarchar(max) NOT NULL CONSTRAINT ck_event_json CHECK (ISJSON(data_json) = 1)
);
GO
CREATE CLUSTERED INDEX cx_audit_event_ts ON audit.audit_event (ts);
CREATE INDEX ix_audit_event_kind ON audit.audit_event (kind, ts);
GO

/* Purga por retención (OP-05: 180 días). Corre como el dueño del esquema, así quien la ejecuta no necesita DELETE en
   `audit`; se niega a borrar algo más reciente que 180 días y deja constancia de lo borrado. */
CREATE PROCEDURE audit.usp_purge
    @keep_days int = 180
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @keep_days IS NULL OR @keep_days < 180
    BEGIN
        ;THROW 51000, 'La retención mínima de la auditoría es de 180 días (OP-05).', 1;
    END;
    DECLARE @cutoff datetime2 = DATEADD(DAY, -@keep_days, SYSUTCDATETIME());
    DECLARE @questions int, @events int;
    BEGIN TRANSACTION;
        DELETE f FROM audit.audit_discovery_feedback f
            JOIN audit.audit_question q ON q.trace_id = f.trace_id WHERE q.ts < @cutoff;
        DELETE d FROM audit.audit_discovery d
            JOIN audit.audit_question q ON q.trace_id = d.trace_id WHERE q.ts < @cutoff;
        DELETE s FROM audit.audit_step s
            JOIN audit.audit_question q ON q.trace_id = s.trace_id WHERE q.ts < @cutoff;
        DELETE FROM audit.audit_question WHERE ts < @cutoff;
        SET @questions = @@ROWCOUNT;
        DELETE FROM audit.audit_event WHERE ts < @cutoff AND kind <> 'audit_purged';  -- las constancias de purga no se purgan
        SET @events = @@ROWCOUNT;
        INSERT INTO audit.audit_event (kind, user_id, data_json)
        VALUES ('audit_purged', ORIGINAL_LOGIN(),
                CONCAT('{"keep_days":', @keep_days, ',"questions":', @questions, ',"events":', @events, '}'));
    COMMIT TRANSACTION;
    SELECT @questions AS questions, @events AS events, @cutoff AS cutoff;
END;
GO

/* ---------- roles ---------- */

/* ConverData-API. Lee y escribe catálogo, conocimiento y curación (curación y refresco bajo demanda desde
   Administración); en `audit` inserta y lee, pero no puede modificar ni borrar. */
CREATE ROLE converdata_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::catalog   TO converdata_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::knowledge TO converdata_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::golden    TO converdata_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::curation  TO converdata_app;
GRANT SELECT, INSERT ON SCHEMA::audit TO converdata_app;
DENY UPDATE, DELETE, ALTER ON SCHEMA::audit TO converdata_app;
DENY EXECUTE ON OBJECT::audit.usp_purge TO converdata_app;
-- Sin ALTER no se puede apagar el versionado temporal para reescribir el historial; la versión solo avanza.
DENY ALTER ON SCHEMA::catalog   TO converdata_app;
DENY ALTER ON SCHEMA::knowledge TO converdata_app;
DENY UPDATE, DELETE ON OBJECT::catalog.catalog_version TO converdata_app;
GO

/* Builder (tarea programada): escribe solo lo que deriva de los metadatos (catálogo, entidades y linaje) y deja
   constancia de sus ejecuciones. No lee preguntas ni confirmaciones, y no puede tocar lo que curan las personas
   (fragmentos, reglas, confirmaciones, responsables). */
CREATE ROLE converdata_builder;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::catalog TO converdata_builder;
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::knowledge.business_entity TO converdata_builder;
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::knowledge.lineage_edge    TO converdata_builder;
GRANT INSERT ON OBJECT::audit.audit_event TO converdata_builder;
DENY SELECT, INSERT, UPDATE, DELETE ON OBJECT::knowledge.golden_discovery TO converdata_builder;
DENY SELECT, INSERT, UPDATE, DELETE ON OBJECT::knowledge.item             TO converdata_builder;
DENY SELECT, INSERT, UPDATE, DELETE ON OBJECT::knowledge.business_rule    TO converdata_builder;
DENY SELECT, UPDATE, DELETE ON SCHEMA::audit TO converdata_builder;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::golden   TO converdata_builder;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::curation TO converdata_builder;
DENY ALTER ON SCHEMA::catalog   TO converdata_builder;
DENY ALTER ON SCHEMA::knowledge TO converdata_builder;
DENY UPDATE, DELETE ON OBJECT::catalog.catalog_version TO converdata_builder;
GO

/* Auditor: solo lectura de la auditoría. */
CREATE ROLE converdata_auditor;
GRANT SELECT ON SCHEMA::audit TO converdata_auditor;
GO

/* Mantenimiento (tarea programada de purga): solo puede ejecutar la purga. */
CREATE ROLE converdata_maintenance;
GRANT EXECUTE ON OBJECT::audit.usp_purge TO converdata_maintenance;
GO
