# Dependencias de Python fijadas

`pyproject.toml` declara las dependencias con rangos (`>=`). Lo que se instala en la imagen y en la CI sale de estos
archivos, con la versión exacta y el hash de cada paquete (`pip install --require-hashes`): una dependencia nueva o
alterada no entra sin que alguien regenere y revise el bloqueo.

| Archivo | Qué trae | Dónde se usa |
|---|---|---|
| `runtime.lock` | Extras `api`, `mcp`, `sqlserver` y `bedrock` | Imagen de ConverData-API (`api/Dockerfile`), análisis de vulnerabilidades y SBOM |
| `dev.lock` | Todos los extras (`dev`, `nim`, `ollama` incluidos) | CI y desarrollo |
| `build.lock` | `setuptools`, para construir el paquete sin descargar nada sin fijar | Imagen y CI |
| `tools.lock` | `pip-audit` y `cyclonedx-bom` con sus dependencias | Trabajo `cadena-de-suministro` de la CI |

Son bloqueos universales: valen para Linux y Windows, con marcadores por plataforma.

## Regenerar
Tras cambiar una dependencia en `pyproject.toml`, o para tomar versiones nuevas:
```bash
pip install uv==0.13.9
uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes --no-header \
    --extra api --extra mcp --extra sqlserver --extra bedrock -o requirements/runtime.lock
uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes --no-header \
    --all-extras -o requirements/dev.lock
echo "setuptools>=69" | uv pip compile - --universal --python-version 3.12 --generate-hashes --no-header \
    -o requirements/build.lock
printf 'pip-audit==2.10.1\ncyclonedx-bom==8.0.1\n' | uv pip compile - --universal --python-version 3.12 \
    --generate-hashes --no-header -o requirements/tools.lock
```
Añadir `--upgrade` para subir versiones. Después: instalar `dev.lock` en un entorno limpio, correr `pytest -q` y
`converdata eval gate`, y `pip-audit -r requirements/runtime.lock --require-hashes --disable-pip`.

`tests/test_supply_chain.py` falla si una dependencia de `pyproject.toml` no está en el bloqueo, si falta un hash, o si
una imagen o una acción de la CI deja de estar fijada.

## Instalar en desarrollo
```bash
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes --only-binary :all: -r requirements/build.lock -r requirements/dev.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation --no-index -e .
```
`--only-binary :all:` evita compilar un paquete desde su código (lo que descargaría herramientas sin hash) y
`--no-build-isolation --no-index` hace que el propio proyecto se instale con el `setuptools` ya verificado, sin red.

## Lo que no cubre
- Los paquetes del sistema de la imagen (`msodbcsql18`, `unixodbc`) se instalan del repositorio firmado de Debian y de
  Microsoft, sin versión fijada. La clave de Microsoft se acepta solo si su huella es la esperada (`api/Dockerfile`).
- Las vulnerabilidades nuevas en lo ya fijado se detectan con el análisis semanal de la CI; actualizar el bloqueo de
  Python sigue siendo manual (Dependabot cubre imágenes, acciones y npm).
- No hay firma de imágenes ni análisis de la imagen ya construida.
