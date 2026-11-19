/* Esquema semantic: capa semántica (F21, OP-02). Tablas normales con CHECK y versionado temporal.
   Solo definiciones (D3): las consultas verificadas llevan SQL con parámetros, sin literales de datos (F17). */

CREATE SCHEMA semantic;
GO

CREATE TABLE semantic.entity (
    name            nvarchar(200) NOT NULL CONSTRAINT pk_semantic_entity PRIMARY KEY,
    canonical_table nvarchar(400) NOT NULL,                  -- asset_key de la tabla canónica (estate.entity)
    key_column      sysname       NOT NULL,
    synonyms_json   nvarchar(max) NULL CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),
    valid_from      datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to        datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = semantic.entity_history));

CREATE TABLE semantic.dimension (
    name        nvarchar(200) NOT NULL CONSTRAINT pk_semantic_dimension PRIMARY KEY,
    expr        nvarchar(1000) NOT NULL,
    table_name  nvarchar(400) NOT NULL,
    dim_type    varchar(12)   NOT NULL DEFAULT 'categorical' CHECK (dim_type IN ('categorical','time')),
    grains_json nvarchar(max) NULL CHECK (grains_json IS NULL OR ISJSON(grains_json) = 1),   -- day, month, quarter, year
    valid_from  datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to    datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to),
    CONSTRAINT ck_semantic_dimension_grains CHECK (dim_type = 'time' OR grains_json IS NULL)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = semantic.dimension_history));

CREATE TABLE semantic.measure (
    name       nvarchar(200) NOT NULL CONSTRAINT pk_semantic_measure PRIMARY KEY,
    expr       nvarchar(1000) NOT NULL,
    table_name nvarchar(400) NOT NULL,
    valid_from datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to   datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = semantic.measure_history));

CREATE TABLE semantic.metric (
    name                   nvarchar(200) NOT NULL CONSTRAINT pk_semantic_metric PRIMARY KEY,
    label                  nvarchar(200) NOT NULL,
    metric_type            varchar(12)   NOT NULL CHECK (metric_type IN ('simple','ratio','derived','cumulative')),
    expr                   nvarchar(1000) NOT NULL,
    default_time_dimension nvarchar(200) NULL REFERENCES semantic.dimension(name),
    owner                  nvarchar(200) NOT NULL,           -- grupo funcional responsable (F24)
    certified              bit           NOT NULL DEFAULT 0, -- el arranque asistido propone con certified = 0
    procedure_name         nvarchar(400) NULL,               -- SP oficial que la resuelve (F6), opcional
    valid_from             datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to               datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = semantic.metric_history));

CREATE TABLE semantic.verified_query (
    name         nvarchar(200) NOT NULL CONSTRAINT pk_semantic_verified_query PRIMARY KEY,
    question     nvarchar(2000) NOT NULL,                    -- plantilla de la pregunta, anonimizada
    sql_template nvarchar(max) NOT NULL,                     -- con parámetros (@inicio, @fin), sin literales
    verified_by  nvarchar(200) NOT NULL,
    valid_from   datetime2 GENERATED ALWAYS AS ROW START HIDDEN NOT NULL,
    valid_to     datetime2 GENERATED ALWAYS AS ROW END HIDDEN NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = semantic.verified_query_history));
GO
