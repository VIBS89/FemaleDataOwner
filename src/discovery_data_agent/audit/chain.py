"""Cadena de hashes de la auditoría en archivos JSONL (F11, OP-05): evidencia de manipulación.

Cada fila lleva `prev` (hash de la fila anterior del mismo archivo) y `hash` = SHA-256 de `prev` + la fila canónica.
La primera fila de un archivo nuevo enlaza con el último hash del archivo del día anterior (`prev_file`), de modo que
tampoco se puede quitar un día completo sin que se note. Editar, borrar, insertar o reordenar filas rompe la cadena.

Límite conocido: quien pueda escribir el archivo puede truncar las últimas filas del último día. Por eso el hash de
cabeza (`head`) que devuelve `verify_directory` se exporta periódicamente fuera del servidor (SIEM o WORM): ver
docs/calidad-bancaria.md. En la BD `DiscoveryDataAgent` el control equivalente es el permiso de solo `INSERT` en `audit`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

GENESIS = "0" * 64
FILE_GLOB = "audit-*.jsonl"


def canonical(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def seal(row: dict, prev: str) -> dict:
    """Devuelve la fila lista para escribir, con `prev` y `hash`. La fila debe ser JSON puro (ya normalizada)."""
    body = {k: v for k, v in row.items() if k != "hash"}
    body["prev"] = prev
    body["hash"] = hashlib.sha256((prev + "\n" + canonical(body)).encode("utf-8")).hexdigest()
    return body


def normalize(row: dict) -> dict:
    """La misma forma que tendrá al releerla del archivo (fechas y otros tipos pasan a texto)."""
    return json.loads(json.dumps(row, ensure_ascii=False, default=str))


def last_hash(path: Path) -> str | None:
    """Hash de la última fila encadenada del archivo; None si no existe o no tiene filas encadenadas."""
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            value = json.loads(line).get("hash")
        except (json.JSONDecodeError, AttributeError):
            continue
        if value:
            return value
    return None


def previous_file(path: Path) -> Path | None:
    """El archivo de auditoría del día anterior más cercano que exista."""
    earlier = sorted(p for p in path.parent.glob(FILE_GLOB) if p.name < path.name)
    return earlier[-1] if earlier else None


@dataclass
class FileCheck:
    name: str
    rows: int = 0
    legacy: int = 0  # filas anteriores a la cadena (sin hash), solo al inicio del archivo
    head: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ChainReport:
    files: list[FileCheck]

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.files)

    @property
    def head(self) -> str | None:
        heads = [f.head for f in self.files if f.head]
        return heads[-1] if heads else None

    def render(self) -> str:
        lines = []
        for f in self.files:
            mark = "OK " if f.ok else "ERR"
            legacy = f" · {f.legacy} sin cadena (anteriores)" if f.legacy else ""
            lines.append(f"{mark} {f.name}: {f.rows} filas{legacy} · cabeza {f.head or '—'}")
            lines += [f"      {e}" for e in f.errors]
        total = sum(f.rows for f in self.files)
        lines.append(f"{'Cadena íntegra' if self.ok else 'CADENA ROTA'}: {len(self.files)} archivos, {total} filas, "
                     f"cabeza {self.head or '—'}")
        return "\n".join(lines)


def verify_file(path: Path, heads: dict[str, set[str]] | None = None) -> FileCheck:
    """`heads`: hashes de las filas de los archivos anteriores ya verificados (nombre → conjunto)."""
    check = FileCheck(path.name)
    seen: set[str] = set()
    prev: str | None = None  # None hasta la primera fila encadenada
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            check.errors.append(f"línea {n}: no es JSON válido")
            continue
        if not isinstance(row, dict) or "hash" not in row:
            if prev is None:
                check.legacy += 1
            else:
                check.errors.append(f"línea {n}: fila sin hash dentro de la cadena (insertada)")
            continue
        check.rows += 1
        if prev is None:  # primera fila encadenada: enlaza con el día anterior
            link = row.get("prev_file")
            if link and heads is not None:
                if link.get("name") not in heads:
                    check.errors.append(f"línea {n}: falta el archivo anterior {link.get('name')}")
                elif link.get("hash") not in heads[link["name"]]:  # puede haber crecido después, no perder esa fila
                    check.errors.append(f"línea {n}: el archivo anterior {link['name']} ya no contiene la fila enlazada")
            expected_prev = GENESIS  # si no, se borraron filas del inicio del archivo
        else:
            expected_prev = prev
        if row.get("prev") != expected_prev:
            check.errors.append(f"línea {n}: no enlaza con la fila anterior (borrada o reordenada)")
        if seal(row, row.get("prev") or GENESIS)["hash"] != row["hash"]:
            check.errors.append(f"línea {n}: el contenido no coincide con su hash (modificada)")
        prev = row["hash"]
        seen.add(prev)
    check.head = prev
    if heads is not None:
        heads[path.name] = seen
    return check


def verify_directory(directory: str | Path) -> ChainReport:
    files = sorted(Path(directory).glob(FILE_GLOB))
    heads: dict[str, set[str]] = {}
    return ChainReport([verify_file(path, heads) for path in files])
