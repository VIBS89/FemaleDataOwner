# SQL Server 2022 Express con las cinco bases de prueba de BancosSQL ya cargadas: el "servidor del banco" del entorno
# de AWS de pruebas, como un contenedor más de la tarea (sin RDS: Express no tiene licencia de pago). También aloja la
# BD de trabajo DiscoveryDataAgent, que la API migra al arrancar.
#
# La construye `despliegue.sh deploy` en una carpeta temporal con este archivo, cargar.sh, iniciar.sh, logins.sql y
# los scripts de BancosSQL.zip en bancos/. Datos 100 % ficticios. Las contraseñas reales no están en la imagen:
# iniciar.sh las pone al arrancar con las variables que inyecta ECS desde Secrets Manager.
ARG BASE=mcr.microsoft.com/mssql/server:2022-latest@sha256:4525e3efac9f3e241cb003bb2ff2a82818b502f37e12049d788b1a9fa7e13b7f

FROM ${BASE} AS carga
ENV ACCEPT_EULA=Y MSSQL_PID=Express
# Contraseña de usar y tirar para la carga; iniciar.sh la sustituye en el primer arranque.
ENV SEED_SA_PASSWORD=Carga.Semilla-2026x
COPY --chown=mssql:mssql bancos/ /seed/bancos/
COPY --chown=mssql:mssql cargar.sh logins.sql /seed/
RUN bash /seed/cargar.sh

FROM ${BASE}
ENV ACCEPT_EULA=Y MSSQL_PID=Express SEED_SA_PASSWORD=Carga.Semilla-2026x
COPY --from=carga --chown=mssql:mssql /var/opt/mssql /var/opt/mssql
COPY --chown=mssql:mssql iniciar.sh /seed/iniciar.sh
EXPOSE 1433
ENTRYPOINT ["bash", "/seed/iniciar.sh"]
