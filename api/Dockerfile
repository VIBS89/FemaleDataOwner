# ConverData-API: FastAPI + DiscoverFlow + CatalogBuildFlow, con el driver ODBC 18 para leer los metadatos de SQL Server.
# Se construye desde la raíz de DataAgent:  docker build -f api/Dockerfile .
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 ACCEPT_EULA=Y

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends msodbcsql18 \
 && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# Proveedores del gateway de LLM opcionales: --build-arg EXTRAS=api,bedrock
ARG EXTRAS=api
RUN pip install ".[${EXTRAS}]"
COPY api ./api
COPY config ./config
# Solo para CONVERDATA_DEMO=1 (servidor simulado con metadatos de prueba; sin valores de datos)
COPY tests/fixtures/bancos ./tests/fixtures/bancos

RUN useradd --create-home --uid 10001 converdata && mkdir -p /app/data && chown converdata /app/data
USER converdata
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
# Un solo worker: el SessionVault vive en memoria del proceso (OP-03).
CMD ["uvicorn", "converdata_api.main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
