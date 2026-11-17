"""Migraciones de la BD `ConverData` (OP-07 §Migraciones, HU-04).

Scripts numerados `db/converdata/NNN_<descripcion>.sql`, aplicados en orden y solo hacia adelante. Cada script corre
entero en una transacción junto con su fila de `dbo.schema_version`: o queda aplicado y registrado, o no cambia nada.
Un script ya aplicado no se puede editar (se compara su SHA-256); los cambios van en un script nuevo.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from converdata.storage.connection import Connect

DEFAULT_DIR = Path("db/converdata")
FILE_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")
GO_RE = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)

CREATE_VERSION_TABLE = """
IF OBJECT_ID('dbo.schema_version', 'U') IS NULL
    CREATE TABLE dbo.schema_version (
        version    int           NOT NULL CONSTRAINT pk_schema_version PRIMARY KEY,
        name       nvarchar(200) NOT NULL,
        checksum   char(64)      NOT NULL,
        applied_at datetime2     NOT NULL CONSTRAINT df_schema_version_at DEFAULT SYSUTCDATETIME(),
        applied_by nvarchar(128) NOT NULL CONSTRAINT df_schema_version_by DEFAULT ORIGINAL_LOGIN()
    );
"""


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        # Insensible al fin de línea: el mismo script da el mismo hash en Windows y en Linux.
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()

    def batches(self) -> list[str]:
        return [b.strip() for b in GO_RE.split(self.sql) if b.strip()]


def discover(directory: str | Path = DEFAULT_DIR) -> list[Migration]:
    directory = Path(directory)
    if not directory.is_dir():
        raise MigrationError(f"No existe el directorio de migraciones: {directory}")
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = FILE_RE.match(path.name)
        if not match:
            raise MigrationError(f"Nombre de migración inválido: {path.name} (se espera NNN_descripcion.sql)")
        found.append(Migration(int(match.group(1)), match.group(2), path))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"Las migraciones deben numerarse 001, 002, … sin huecos ni repetidos: {versions}")
    return found


def applied(connect: Connect) -> dict[int, str]:
    """Versión → checksum de lo ya aplicado (vacío si la BD es nueva)."""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT OBJECT_ID('dbo.schema_version', 'U')")
        if cur.fetchone()[0] is None:
            return {}
        cur.execute("SELECT version, checksum FROM dbo.schema_version ORDER BY version")
        return {int(v): c for v, c in cur.fetchall()}
    finally:
        conn.close()


def pending(connect: Connect, directory: str | Path = DEFAULT_DIR) -> list[Migration]:
    done = applied(connect)
    migrations = discover(directory)
    for m in migrations:
        if m.version in done and done[m.version] != m.checksum:
            raise MigrationError(
                f"La migración {m.path.name} cambió después de aplicarse; los cambios van en un script nuevo")
    unknown = sorted(set(done) - {m.version for m in migrations})
    if unknown:
        raise MigrationError(f"La BD tiene migraciones que este código no conoce: {unknown} (¿versión antigua de la aplicación?)")
    return [m for m in migrations if m.version not in done]


def migrate(connect: Connect, directory: str | Path = DEFAULT_DIR) -> list[Migration]:
    """Aplica lo pendiente y devuelve lo aplicado. Volver a ejecutarla sin cambios no hace nada."""
    todo = pending(connect, directory)
    for migration in todo:
        conn = connect()
        try:
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute(CREATE_VERSION_TABLE)
            for batch in migration.batches():
                cur.execute(batch)
            cur.execute("INSERT INTO dbo.schema_version (version, name, checksum) VALUES (?, ?, ?)",
                        migration.version, migration.name, migration.checksum)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise MigrationError(f"Falló {migration.path.name}; no se aplicó nada de ese script: {exc}") from exc
        finally:
            conn.close()
    return todo
