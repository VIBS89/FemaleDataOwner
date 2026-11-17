# ConverData-API: FastAPI + DiscoverFlow + CatalogBuildFlow, con el driver ODBC 18 para leer los metadatos de SQL Server.
# Se construye desde la raíz de DataAgent:  docker build -f api/Dockerfile .
# Imagen base fijada por digest (la etiqueta puede cambiar de contenido). Se actualiza con Dependabot o a mano:
#   docker buildx imagetools inspect python:3.12-slim-bookworm
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 ACCEPT_EULA=Y

# La clave con la que Microsoft firma su repositorio se acepta solo si es exactamente la esperada (una sola clave, con
# esta huella): `gpg --show-keys microsoft.asc`.
ARG MICROSOFT_KEY_FINGERPRINT=BC528686B50D79E339D3721CEB3E94ADBE1229CF
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc -o /tmp/microsoft.asc \
 && [ "$(gpg --show-keys --with-colons /tmp/microsoft.asc | grep -c '^pub:')" = "1" ] \
 && gpg --show-keys --with-colons /tmp/microsoft.asc | grep -q "^fpr:::::::::${MICROSOFT_KEY_FINGERPRINT}:" \
 && gpg --dearmor -o /usr/share/keyrings/microsoft.gpg /tmp/microsoft.asc && rm /tmp/microsoft.asc \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends msodbcsql18 \
 && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Dependencias con versión y hash fijados (requirements/README.md). `runtime.lock` trae la API, el MCP, SQL Server y
# Bedrock; para NVIDIA NIM u Ollama (solo desarrollo): --build-arg REQUIREMENTS=requirements/dev.lock
ARG REQUIREMENTS=requirements/runtime.lock
COPY requirements ./requirements
# `--only-binary`: solo paquetes ya compilados. Compilar uno desde su código descargaría sus herramientas de
# construcción sin hash.
RUN pip install --require-hashes --only-binary :all: -r requirements/build.lock \
 && pip install --require-hashes --only-binary :all: -r ${REQUIREMENTS}
COPY pyproject.toml README.md ./
COPY src ./src
# El paquete se instala sin resolver ni descargar nada más: todo lo que necesita ya está instalado y verificado.
RUN pip install --no-deps --no-build-isolation --no-index .
COPY api ./api
COPY config ./config
# Migraciones de la BD ConverData: `converdata db migrate` desde la misma imagen
COPY db ./db
# Solo para CONVERDATA_DEMO=1 (servidor simulado con metadatos de prueba; sin valores de datos)
COPY tests/fixtures/bancos ./tests/fixtures/bancos

RUN useradd --create-home --uid 10001 converdata && mkdir -p /app/data && chown converdata /app/data
USER converdata
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
# Un solo worker: el SessionVault vive en memoria del proceso (OP-03).
CMD ["uvicorn", "converdata_api.main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
