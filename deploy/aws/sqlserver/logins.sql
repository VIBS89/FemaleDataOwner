/* Logins del entorno de pruebas. Se crean deshabilitados y con una contraseña aleatoria: iniciar.sh pone la real
   (de Secrets Manager) y los habilita al arrancar.

   dda_admin  administrador de datos (DISCOVERY_DATA_AGENT_ADMINS): ve las cinco bases.
   analista   consumidor: solo BancaCuentasDebito y BancaPrestamos, para mostrar que el descubrimiento respeta permisos.
   dda_app    cuenta de servicio de la API: dueña de la BD DiscoveryDataAgent (catálogo, curación, auditoría).
   demo       como dda_admin, con la contraseña fija `demo` para mostrar la solución. Queda deshabilitado salvo que la
              tarea arranque con DDA_DEMO_LOGIN=1 (variable `sql_demo_login` del .tfvars). */
SET NOCOUNT ON;
DECLARE @tmp nvarchar(64) = CONVERT(nvarchar(64), NEWID()) + N'aA1!';
DECLARE @sql nvarchar(max);
SET @sql = N'CREATE LOGIN dda_admin WITH PASSWORD = ''' + @tmp + N''', CHECK_POLICY = OFF;
CREATE LOGIN analista WITH PASSWORD = ''' + @tmp + N''', CHECK_POLICY = OFF;
CREATE LOGIN dda_app WITH PASSWORD = ''' + @tmp + N''', CHECK_POLICY = OFF;
CREATE LOGIN demo WITH PASSWORD = ''' + @tmp + N''', CHECK_POLICY = OFF;
ALTER LOGIN dda_admin DISABLE; ALTER LOGIN analista DISABLE; ALTER LOGIN dda_app DISABLE; ALTER LOGIN demo DISABLE;';
EXEC (@sql);
GO
GRANT VIEW ANY DEFINITION TO dda_admin;
GRANT VIEW SERVER STATE TO dda_admin;
GRANT VIEW ANY DEFINITION TO demo;
GRANT VIEW SERVER STATE TO demo;
GO
CREATE DATABASE DiscoveryDataAgent;
GO
ALTER AUTHORIZATION ON DATABASE::DiscoveryDataAgent TO dda_app;
GO
/* Usuarios en las bases de prueba: lectura y metadatos (VIEW DEFINITION, VIEW DATABASE STATE). */
DECLARE @db sysname, @sql nvarchar(max);
DECLARE bases CURSOR LOCAL FAST_FORWARD FOR
  SELECT name FROM sys.databases WHERE name LIKE N'Banca%';
OPEN bases;
FETCH NEXT FROM bases INTO @db;
WHILE @@FETCH_STATUS = 0
BEGIN
  SET @sql = N'USE ' + QUOTENAME(@db) + N';
    CREATE USER dda_admin FOR LOGIN dda_admin;
    ALTER ROLE db_datareader ADD MEMBER dda_admin;
    GRANT VIEW DEFINITION, VIEW DATABASE STATE TO dda_admin;
    CREATE USER demo FOR LOGIN demo;
    ALTER ROLE db_datareader ADD MEMBER demo;
    GRANT VIEW DEFINITION, VIEW DATABASE STATE TO demo;';
  IF @db IN (N'BancaCuentasDebito', N'BancaPrestamos')
    SET @sql += N'
    CREATE USER analista FOR LOGIN analista;
    ALTER ROLE db_datareader ADD MEMBER analista;
    GRANT VIEW DEFINITION TO analista;';
  EXEC (@sql);
  FETCH NEXT FROM bases INTO @db;
END
CLOSE bases;
DEALLOCATE bases;
GO
