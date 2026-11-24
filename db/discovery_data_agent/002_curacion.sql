/* Curación e inventario en la BD — bloque C2 (HU-06, HU-09, HU-30 a HU-32; OP-02).

   Lo que DiscoveryDataAgent-API guardaba en archivos del servidor pasa a tablas: responsables por login, dudas escaladas,
   votos e inventario de servidores. Con esto el servidor de aplicación no guarda estado.
   Las preguntas (D2) solo viven en `audit`, `golden` y `curation`; el Builder no lee ninguno de los tres. */

/* Inventario de servidores que usa la API para conectarse (con `host`). `catalog.server` es la copia sin hosts que
   acompaña al catálogo. Cambiar un host redirige las credenciales de todos: tabla temporal, y el Builder solo la lee. */
CREATE TABLE catalog.inventory_server (
    server_id    nvarchar(100) NOT NULL CONSTRAINT pk_inventory_server PRIMARY KEY,
    position     int           NOT NULL,
    config_json  nvarchar(max) NOT NULL CONSTRAINT ck_inventory_json CHECK (ISJSON(config_json) = 1),
    modified_by  nvarchar(128) NOT NULL,
    valid_from   datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to     datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = catalog.inventory_server_history));
GO

/* Responsables (`steward`) por login SQL mientras no haya grupos de AD (HU-13). Da un rol: tabla temporal. */
CREATE TABLE curation.steward (
    login        nvarchar(128) NOT NULL CONSTRAINT pk_steward PRIMARY KEY,
    domains_json nvarchar(max) NOT NULL CONSTRAINT ck_steward_domains CHECK (ISJSON(domains_json) = 1),
    modified_by  nvarchar(128) NOT NULL,
    valid_from   datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to     datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = curation.steward_history));
GO

/* Dudas escaladas al responsable (F24 §Escalamiento). `question` es D2. Una por respuesta y usuario. */
CREATE TABLE curation.request (
    request_id   varchar(20)    NOT NULL CONSTRAINT pk_request PRIMARY KEY,
    seq          bigint IDENTITY NOT NULL,
    created_at   datetime2      NOT NULL,
    status       varchar(12)    NOT NULL CONSTRAINT ck_request_status CHECK (status IN ('open','answered','no_source')),
    user_id      nvarchar(128)  NOT NULL,
    trace_id     varchar(64)    NOT NULL,
    question     nvarchar(2000) NOT NULL,
    domain       nvarchar(100)  NOT NULL,
    shown_json   nvarchar(max)  NOT NULL CONSTRAINT ck_request_shown CHECK (ISJSON(shown_json) = 1),
    note         nvarchar(500)  NULL,
    simulated    bit            NOT NULL CONSTRAINT df_request_simulated DEFAULT 0,   -- historial del modo demo
    answer_json  nvarchar(max)  NULL CONSTRAINT ck_request_answer CHECK (answer_json IS NULL OR ISJSON(answer_json) = 1),
    CONSTRAINT uq_request_trace UNIQUE (trace_id, user_id)
);
GO
CREATE INDEX ix_request_seq ON curation.request (seq);
GO

/* Votos sobre los candidatos (F24). De aquí sale el recuento de cada confirmación; el voto también queda en la
   auditoría. `golden_id` identifica la pareja plantilla-activo. Sin texto libre: no lleva preguntas ni comentarios. */
CREATE TABLE curation.vote (
    id           bigint IDENTITY CONSTRAINT pk_vote PRIMARY KEY,
    ts           datetime2     NOT NULL CONSTRAINT df_vote_ts DEFAULT SYSUTCDATETIME(),
    golden_id    nvarchar(100) NOT NULL,
    user_id      nvarchar(128) NOT NULL,
    trace_id     varchar(64)   NOT NULL,
    asset_key    nvarchar(400) NOT NULL,
    verdict      varchar(12)   NOT NULL CONSTRAINT ck_vote_verdict CHECK (verdict IN ('confirm','reject')),
    steward      bit           NOT NULL
);
GO
CREATE INDEX ix_vote_golden ON curation.vote (golden_id, id);
GO

/* Desde esta versión `knowledge.golden_discovery.template` es una plantilla anónima (la pregunta sin literales) y el
   texto original va a `golden.golden_discovery_original`. No hay confirmaciones de usuarios anteriores que convertir:
   la BD todavía no se ha desplegado con preguntas reales. */

/* La purga por retención (OP-05) alcanza también a lo que guarda preguntas fuera de la auditoría: las dudas escaladas
   y el texto original de las confirmaciones. Los votos y las plantillas no llevan texto libre y se conservan. */
ALTER PROCEDURE audit.usp_purge
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
    DECLARE @questions int, @events int, @requests int, @originals int;
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
        DELETE FROM curation.request WHERE created_at < @cutoff;
        SET @requests = @@ROWCOUNT;
        DELETE FROM golden.golden_discovery_original WHERE created_at < @cutoff;
        SET @originals = @@ROWCOUNT;
        INSERT INTO audit.audit_event (kind, user_id, data_json)
        VALUES ('audit_purged', ORIGINAL_LOGIN(),
                CONCAT('{"keep_days":', @keep_days, ',"questions":', @questions, ',"events":', @events,
                       ',"requests":', @requests, ',"originals":', @originals, '}'));
    COMMIT TRANSACTION;
    SELECT @questions AS questions, @events AS events, @cutoff AS cutoff, @requests AS requests, @originals AS originals;
END;
GO

/* ---------- permisos ---------- */
-- Los nuevos objetos de `curation` y `catalog` heredan los permisos de esquema de 001. Se añade lo que falta:
-- la API no puede reescribir el historial de responsables ni cambiar o borrar un voto o un original ya escritos,
-- y el Builder lee el inventario pero no lo cambia.
DENY ALTER ON SCHEMA::curation TO discovery_data_agent_app;
DENY UPDATE, DELETE ON OBJECT::curation.vote TO discovery_data_agent_app;
DENY UPDATE, DELETE ON OBJECT::golden.golden_discovery_original TO discovery_data_agent_app;
DENY INSERT, UPDATE, DELETE ON OBJECT::catalog.inventory_server TO discovery_data_agent_builder;
GO
