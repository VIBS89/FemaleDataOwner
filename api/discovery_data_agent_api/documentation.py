"""Documentación interna que la web muestra a `data_admin`: el manual, la wiki y la arquitectura, solo lectura.

Lo que se sirve es una lista fija calculada recorriendo la carpeta, nunca una ruta que arme quien llama: la ruta pedida
se busca tal cual entre las del índice. Así no hay `..`, rutas absolutas, mayúsculas, barras invertidas, codificaciones
ni nombres alternativos de Windows (`README.md.`, `README.md::$DATA`) que valgan. Los enlaces simbólicos y las uniones
de NTFS se descartan al recorrer, y antes de leer se comprueba otra vez que el archivo real sigue dentro de la carpeta.
"""

from __future__ import annotations

import datetime as dt
import html
import os
import re
from dataclasses import dataclass
from pathlib import Path

MANUAL = "manual-desarrollo.md"
ARCHITECTURE = "architecture/README.md"
WIKI = "wiki"
DIAGRAMS = "architecture"
MAX_PAGE_BYTES = 1024 * 1024  # la página más larga de hoy no llega a 40 KB
MAX_DIAGRAM_BYTES = 4 * 1024 * 1024  # un diagrama de Archify ronda 0,9 MB (fuentes y SVG en línea)


class DocumentNotFound(LookupError):
    """La ruta no está en el índice, o el archivo dejó de poder leerse. Se responde igual en los dos casos."""


@dataclass(frozen=True)
class Document:
    path: str  # relativa a la carpeta de documentación, con `/`
    title: str
    section: str  # carpeta de la página: "", "wiki", "wiki/componentes", "architecture"


@dataclass(frozen=True)
class Content:
    path: str
    title: str
    body: bytes
    updated_at: str


class DocumentationLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)

    # --- índice ---------------------------------------------------------------------------------------------
    def pages(self) -> list[Document]:
        """Manual, README de la wiki y el resto de la wiki por carpeta, y la arquitectura."""
        found = [p for p in (MANUAL, *self._walk(WIKI, ".md"), ARCHITECTURE) if self._file(p, MAX_PAGE_BYTES)]
        order = {MANUAL: (0,), ARCHITECTURE: (3,)}
        found.sort(key=lambda p: order.get(p, (1 if p.count("/") == 1 else 2, p != f"{WIKI}/README.md", p)))
        return [Document(p, self._page_title(p), p.rpartition("/")[0]) for p in found]

    def diagrams(self) -> list[Document]:
        found = sorted(p for p in self._walk(DIAGRAMS, ".html", recursive=False) if self._file(p, MAX_DIAGRAM_BYTES))
        return [Document(p, self._diagram_title(p), DIAGRAMS) for p in found]

    # --- lectura --------------------------------------------------------------------------------------------
    def page(self, path: str) -> Content:
        return self._read(path, {d.path: d for d in self.pages()}, MAX_PAGE_BYTES)

    def diagram(self, path: str) -> Content:
        return self._read(path, {d.path: d for d in self.diagrams()}, MAX_DIAGRAM_BYTES)

    def _read(self, path: str, allowed: dict[str, Document], limit: int) -> Content:
        document = allowed.get(path) if isinstance(path, str) else None
        if document is None:
            raise DocumentNotFound(path)
        file = self._file(document.path, limit)
        if file is None:
            raise DocumentNotFound(path)
        try:
            body = file.read_bytes()
            modified = file.stat().st_mtime
            if len(body) > limit:
                raise DocumentNotFound(path)
            body.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise DocumentNotFound(path) from error
        updated = dt.datetime.fromtimestamp(modified, dt.timezone.utc).isoformat(timespec="seconds")
        return Content(document.path, document.title, body, updated)

    # --- recorrido seguro -----------------------------------------------------------------------------------
    def _walk(self, folder: str, suffix: str, recursive: bool = True) -> list[str]:
        """Archivos `*suffix` bajo `folder`, sin seguir enlaces simbólicos ni uniones (ni de carpetas ni de archivos)."""
        base = self.root / folder
        if not self._real_dir(base):
            return []
        out = []
        for current, dirs, files in os.walk(base, followlinks=False):
            here = Path(current)
            dirs[:] = sorted(d for d in dirs if recursive and self._real_dir(here / d))
            for name in sorted(files):
                if name.endswith(suffix) and name == name.strip() and not name.startswith("."):
                    out.append((here / name).relative_to(self.root).as_posix())
            if not recursive:
                break
        return out

    def _real_dir(self, path: Path) -> bool:
        return path.is_dir() and not path.is_symlink() and not _is_junction(path) and self._inside(path)

    def _file(self, relative: str, limit: int) -> Path | None:
        """El archivo de `relative` si es un archivo normal, dentro de la carpeta (resuelto, con sus carpetas) y no más
        grande que `limit`."""
        path = self.root / relative
        try:
            if not path.is_file() or path.is_symlink() or not self._inside(path):
                return None
            return path if path.stat().st_size <= limit else None
        except (OSError, ValueError):
            return None

    def _inside(self, path: Path) -> bool:
        try:
            return path.resolve(strict=True).is_relative_to(self.root.resolve(strict=True))
        except (OSError, RuntimeError):
            return False

    # --- títulos --------------------------------------------------------------------------------------------
    def _page_title(self, relative: str) -> str:
        try:
            with (self.root / relative).open(encoding="utf-8") as f:
                first = f.readline(500).strip()
        except (OSError, UnicodeError):
            first = ""
        return first[2:].strip() if first.startswith("# ") else Path(relative).stem

    def _diagram_title(self, relative: str) -> str:
        try:
            with (self.root / relative).open(encoding="utf-8") as f:
                head = f.read(8192)
        except (OSError, UnicodeError):
            head = ""
        match = re.search(r"<title>([^<]{1,300})</title>", head)
        title = html.unescape(match.group(1)).strip() if match else ""
        return re.sub(r"\s*·\s*Diagrama$", "", title) or Path(relative).stem


def _is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)  # Python 3.12+
    try:
        return bool(is_junction()) if is_junction else False
    except OSError:
        return True
