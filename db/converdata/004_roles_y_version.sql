/* Roles de HU-04 y control de versiones del DDL. Los roles se asignan a las gMSA/grupos de AD en el despliegue (OP-07), nunca aquí. */

/* Qué scripts se aplicaron y con qué contenido. El ejecutor de despliegue (deploy/dev, OP-07) completa `checksum`. */
CREATE TABLE dbo.schema_version (
    script     nvarchar(200) NOT NULL CONSTRAINT pk_schema_version PRIMARY KEY,
    applied_at datetime2     NOT NULL DEFAULT SYSUTCDATETIME(),
    checksum   varchar(64)   NULL
);
INSERT INTO dbo.schema_version (script) VALUES
    ('001_esquemas.sql'), ('002_estate.sql'), ('003_semantic.sql'), ('004_roles_y_version.sql');
GO

/* ConverData-API: lectura del grafo y de la capa semántica (los permisos sobre catalog, knowledge, audit y curation están en 001). */
GRANT SELECT ON SCHEMA::estate    TO converdata_app;
GRANT SELECT ON SCHEMA::semantic  TO converdata_app;
GO

/* Servicio ConverData-Builder (gMSA propia): escribe el catálogo, el grafo y el conocimiento; no toca la auditoría (F11). */
CREATE ROLE converdata_builder;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::catalog   TO converdata_builder;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::estate    TO converdata_builder;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::knowledge TO converdata_builder;
DENY  SELECT, INSERT, UPDATE, DELETE ON SCHEMA::audit     TO converdata_builder;
GO

/* Auditor (OP-05): consulta la auditoría y nada más. */
CREATE ROLE auditor;
GRANT SELECT ON SCHEMA::audit TO auditor;
GO
