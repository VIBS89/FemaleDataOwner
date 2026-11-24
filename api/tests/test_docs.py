"""Documentación interna en la web: manual, wiki y arquitectura, solo lectura y solo para `data_admin` (F11, OP-04).

Lo que se sirve es una lista fija: `docs/manual-desarrollo.md`, `docs/wiki/**/*.md`, `docs/architecture/README.md` y los
diagramas `docs/architecture/*.html`. Nada más de `docs/` (PRD, specs, backlog) ni de fuera, por ningún camino.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converdata_api.connector import DemoConnector
from converdata_api.main import create_app
from converdata_api.settings import INSTALL_ROOT, ApiSettings

from test_api import FIXTURE, build, login, make_client, ready, settings  # noqa: F401  (fixtures de la API)

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def served_pages() -> set[str]:
    """Lo que el visor debe servir según la lista fija, calculado aparte del código de la API."""
    pages = {"manual-desarrollo.md", "architecture/README.md"}
    pages |= {p.relative_to(DOCS).as_posix() for p in (DOCS / "wiki").rglob("*.md")}
    return pages


def served_diagrams() -> set[str]:
    return {p.relative_to(DOCS).as_posix() for p in (DOCS / "architecture").glob("*.html")}


def other_role(ready, user: str) -> TestClient:
    client = make_client_for(ready)
    login(client, user=user)
    return client


def make_client_for(ready) -> TestClient:
    return TestClient(ready.app)


def doc_reads(ready) -> list[dict]:
    return ready.get("/admin/audit", params={"kind": "doc_read", "limit": 500}).json()["items"]


# --- quién puede leer -----------------------------------------------------------------------------------
def test_la_documentacion_es_solo_para_administradores_de_datos(ready):
    """Explica controles de seguridad y su deuda: `data_admin` sí; consumidor y responsable, 403 auditado; sin sesión, 401."""
    page = {"path": "wiki/README.md"}
    diagram = {"path": "architecture/c4-contexto.html"}
    assert ready.get("/admin/docs").status_code == 200
    assert ready.get("/admin/docs/page", params=page).status_code == 200
    assert ready.get("/admin/docs/diagram", params=diagram).status_code == 200
    for user in ("analista", "responsable"):
        client = other_role(ready, user)
        assert client.get("/admin/docs").status_code == 403
        assert client.get("/admin/docs/page", params=page).status_code == 403
        assert client.get("/admin/docs/diagram", params=diagram).status_code == 403
    denied = ready.get("/admin/audit", params={"kind": "access_denied", "limit": 100}).json()["items"]
    routes = {(r["user_id"], r["route"]) for r in denied}
    assert {("analista", "/admin/docs/page"), ("responsable", "/admin/docs/diagram")} <= routes
    anonymous = make_client_for(ready)
    for url, params in (("/admin/docs", None), ("/admin/docs/page", page), ("/admin/docs/diagram", diagram)):
        assert anonymous.get(url, params=params).status_code == 401
    assert [r["user_id"] for r in doc_reads(ready)] == ["demo", "demo"]  # solo las lecturas entregadas


# --- índice ---------------------------------------------------------------------------------------------
def test_el_indice_lista_exactamente_las_paginas_y_diagramas_existentes(ready):
    body = ready.get("/admin/docs")
    assert body.status_code == 200 and body.headers["cache-control"] == "no-store"
    index = body.json()
    assert {p["path"] for p in index["pages"]} == served_pages()
    assert {d["path"] for d in index["diagrams"]} == served_diagrams()
    assert len(index["pages"]) == len(served_pages())  # sin repetidos
    assert index["pages"][0]["path"] == "manual-desarrollo.md"
    for page in index["pages"]:
        first = (DOCS / page["path"]).read_text(encoding="utf-8").splitlines()[0]
        assert first == f"# {page['title']}", page
        assert page["section"] == ("" if "/" not in page["path"] else page["path"].rsplit("/", 1)[0])
    for diagram in index["diagrams"]:
        assert diagram["title"] and "<" not in diagram["title"]
    assert "PRD.md" not in body.text and "specs/" not in body.text and "backlog" not in body.text


# --- páginas --------------------------------------------------------------------------------------------
def test_cada_pagina_del_indice_se_lee_entera_y_queda_auditada(ready):
    paths = [p["path"] for p in ready.get("/admin/docs").json()["pages"]]
    for path in paths:
        r = ready.get("/admin/docs/page", params={"path": path})
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["path"] == path and body["updated_at"]
        assert body["markdown"] == (DOCS / path).read_bytes().decode("utf-8")  # tal cual, también CRLF
    assert sorted(r["path"] for r in doc_reads(ready)) == sorted(paths)
    assert {r["doc"] for r in doc_reads(ready)} == {"page"}


def test_una_pagina_que_falta_da_404_limpio_y_no_cuenta_como_lectura(ready, settings, tmp_path):
    missing = ready.get("/admin/docs/page", params={"path": "wiki/no-existe.md"})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Esa página no está en la documentación de este servidor"}
    settings.docs_dir = tmp_path / "sin-docs"  # instalación sin documentación: índice vacío, 404 en todo
    assert ready.get("/admin/docs").json() == {"pages": [], "diagrams": []}
    assert ready.get("/admin/docs/page", params={"path": "wiki/README.md"}).status_code == 404
    assert ready.get("/admin/docs/diagram", params={"path": "architecture/c4-contexto.html"}).status_code == 404
    assert ready.get("/admin/manual").status_code == 404
    assert ready.get("/admin/docs/page").status_code == 422  # sin `path`
    assert doc_reads(ready) == []


TRAVERSALS = [
    "../README.md", "..\\README.md", "../.env", "../config/models.yaml", "wiki/../../README.md", "wiki/../PRD.md",
    "wiki/../manual-desarrollo.md", "./wiki/README.md", "wiki//README.md", "wiki\\README.md", "wiki/README.md/",
    "/etc/passwd", "C:\\Windows\\win.ini", "C:/Windows/win.ini", "\\\\servidor\\recurso\\a.md", "//servidor/a.md",
    str(DOCS / "wiki" / "README.md"), (DOCS / "wiki" / "README.md").as_posix(), "file:///etc/passwd",
    "%2e%2e/README.md", "%2e%2e%2fREADME.md", "wiki/%2e%2e/PRD.md", "%252e%252e/README.md", "%c0%ae%c0%ae/README.md",
    "wiki/README.md%00", "wiki/README.md\x00.html", "wiki/README.md.", "wiki/README.md ", "wiki/README.md::$DATA",
    "WIKI/README.md", "wiki/readme.md", "wiki/README.MD", "ｗiki/README.md", "wiki/README．md", "wiki/README\u2024md",
    "PRD.md", "PLAN-desarrollo.md", "calidad-bancaria.md", "specs/comun/F11-audit.md", "backlog/on-premise.md",
    "architecture/capas-backend.md", "architecture/c4-contexto.archify.json", "architecture/c4-contexto.html",
    "wiki", "wiki/", "", ".", "wiki/componentes",
]


@pytest.mark.parametrize("path", TRAVERSALS)
def test_ninguna_ruta_fuera_de_la_lista_se_sirve(ready, path):
    """Recorrido de directorios, rutas absolutas, UNC, codificaciones, mayúsculas, nombres alternativos de Windows y
    documentos de `docs/` que no son de la wiki: 404 igual que lo inexistente, y nada en la auditoría."""
    assert ready.get("/admin/docs/page", params={"path": path}).status_code == 404, path
    diagram = path.replace(".md", ".html") if path.endswith(".md") else path
    if diagram not in served_diagrams():
        assert ready.get("/admin/docs/diagram", params={"path": diagram}).status_code == 404, diagram
    assert doc_reads(ready) == []


def test_un_diagrama_no_se_sirve_como_pagina_ni_una_pagina_como_diagrama(ready):
    assert ready.get("/admin/docs/page", params={"path": "architecture/c4-contexto.html"}).status_code == 404
    assert ready.get("/admin/docs/diagram", params={"path": "architecture/README.md"}).status_code == 404
    assert ready.get("/admin/docs/diagram", params={"path": "manual-desarrollo.md"}).status_code == 404


def test_los_enlaces_simbolicos_y_las_uniones_no_sacan_de_la_carpeta(ready, settings, tmp_path):
    """Un archivo o carpeta enlazada dentro de `wiki/` que apunta fuera no aparece en el índice ni se lee."""
    docs = tmp_path / "docs"
    (docs / "wiki").mkdir(parents=True)
    (docs / "architecture").mkdir()
    (docs / "manual-desarrollo.md").write_text("# Manual\n", encoding="utf-8")
    (docs / "wiki" / "README.md").write_text("# Wiki\n", encoding="utf-8")
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto.md").write_text("# Secreto\n", encoding="utf-8")
    (outside / "secreto.html").write_text("<title>Secreto</title>", encoding="utf-8")
    links = []
    for link, target, is_dir in (("wiki/enlace.md", outside / "secreto.md", False), ("wiki/carpeta", outside, True),
                                 ("architecture/enlace.html", outside / "secreto.html", False)):
        try:
            os.symlink(target, docs / link, target_is_directory=is_dir)
            links.append(link)
        except (OSError, NotImplementedError):
            pass
    if sys.platform == "win32":  # una unión de NTFS no necesita privilegios: siempre se prueba en Windows
        import _winapi

        _winapi.CreateJunction(str(outside), str(docs / "wiki" / "union"))
        links.append("wiki/union")
    if not links:
        pytest.skip("este sistema no permite crear enlaces simbólicos ni uniones")
    settings.docs_dir = docs
    index = ready.get("/admin/docs").json()
    assert {p["path"] for p in index["pages"]} == {"manual-desarrollo.md", "wiki/README.md"}
    assert index["diagrams"] == []
    for path in ("wiki/enlace.md", "wiki/carpeta/secreto.md", "wiki/union/secreto.md"):
        assert ready.get("/admin/docs/page", params={"path": path}).status_code == 404, path
    assert ready.get("/admin/docs/diagram", params={"path": "architecture/enlace.html"}).status_code == 404
    assert doc_reads(ready) == []


def test_la_documentacion_no_se_entrega_sin_auditoria(ready, monkeypatch):
    """Fail-closed (F11): si la lectura no se puede registrar, ni la página ni el diagrama salen."""
    def broken(*args, **kwargs):
        raise OSError("auditoría no disponible")

    monkeypatch.setattr(type(ready.app.state.runtime.audit), "event", broken)
    quiet = TestClient(ready.app, raise_server_exceptions=False, cookies=ready.cookies)
    page = quiet.get("/admin/docs/page", params={"path": "wiki/deuda-tecnica.md"})
    assert page.status_code == 500 and "DT-04" not in page.text
    diagram = quiet.get("/admin/docs/diagram", params={"path": "architecture/c4-contexto.html"})
    assert diagram.status_code == 500 and "<svg" not in diagram.text


# --- diagramas ------------------------------------------------------------------------------------------
def test_un_diagrama_se_entrega_como_datos_y_auditado(ready):
    """El HTML de Archify trae scripts en línea. Va como texto dentro de JSON y nunca como `text/html`: si alguien abre
    la ruta directamente, el navegador no lo ejecuta en el origen de la web. Solo los `.html` de `docs/architecture/`."""
    r = ready.get("/admin/docs/diagram", params={"path": "architecture/permisos-heredados.html"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    body = r.json()
    assert body["html"] == (DOCS / "architecture" / "permisos-heredados.html").read_bytes().decode("utf-8")
    assert body["path"] == "architecture/permisos-heredados.html" and body["title"] and body["updated_at"]
    assert [(row["path"], row["doc"]) for row in doc_reads(ready)] == [("architecture/permisos-heredados.html", "diagram")]


# --- enlaces --------------------------------------------------------------------------------------------
def heading_slug(text: str) -> str:
    """El mismo `slug` de `web/src/components/markdown.tsx`: minúsculas, sin acentos, lo demás a guiones."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", text))


def markdown_links(text: str) -> list[str]:
    prose = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    prose = re.sub(r"`[^`]*`", "", prose)
    return re.findall(r"\]\(([^)\s]+)\)", prose)


def anchors(text: str) -> set[str]:
    prose = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    return {heading_slug(re.sub(r"[`*]", "", m)) for m in re.findall(r"^#{1,4}\s+(.*)$", prose, flags=re.M)}


def test_los_enlaces_relativos_de_la_documentacion_llevan_a_algo_que_existe():
    """Recorre los archivos reales. Un enlace a otra página o a un diagrama servidos se sigue dentro del visor y su
    ancla existe; uno a un documento que el visor no sirve (PRD, specs, backlog…) debe existir en el repositorio y la
    web lo muestra como ruta, sin enlace."""
    pages, diagrams = served_pages(), served_diagrams()
    inside, outside, broken = 0, set(), []
    for page in sorted(pages):
        source = DOCS / page
        for href in markdown_links(source.read_text(encoding="utf-8")):
            if re.match(r"^[a-z][a-z0-9+.-]*:", href, flags=re.I):
                assert href.startswith("https://"), (page, href)  # nada de javascript:, file:, data:
                continue
            target, _, anchor = href.partition("#")
            resolved = (source.parent / target).resolve() if target else source.resolve()
            try:
                rel = resolved.relative_to(DOCS.resolve()).as_posix()
            except ValueError:
                rel = None
            if rel in pages:
                inside += 1
                if anchor and heading_slug(anchor) not in anchors((DOCS / rel).read_text(encoding="utf-8")):
                    broken.append((page, href, "ancla"))
            elif rel in diagrams:
                inside += 1
                assert not anchor, (page, href)
            elif resolved.exists():
                assert resolved.is_relative_to(ROOT), (page, href)
                outside.add(resolved.relative_to(ROOT).as_posix())
            else:
                broken.append((page, href, "no existe"))
    assert broken == []
    assert inside > 80
    assert not any(o.startswith(("docs/wiki/", "docs/architecture/README.md")) for o in outside)
    assert {"docs/PRD.md", "docs/calidad-bancaria.md"} <= outside  # se muestran como ruta, no se sirven


# --- instalación ----------------------------------------------------------------------------------------
def test_la_documentacion_se_encuentra_aunque_la_api_arranque_desde_otra_carpeta(monkeypatch, tmp_path):
    """Causa de "no veo el manual": la ruta por defecto era relativa al directorio de trabajo. Arrancando desde `api/`
    (o desde cualquier otra carpeta) el manual daba 404 y el modo demo no encontraba sus servidores simulados."""
    for name in ("CONVERDATA_DOCS", "CONVERDATA_DEMO_FIXTURE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    defaults = ApiSettings.from_env()
    assert INSTALL_ROOT == ROOT
    assert defaults.docs_dir == DOCS and defaults.docs_dir.is_absolute()
    assert all(f.is_absolute() and (f / "config" / "databases.yaml").is_file() for f in defaults.demo_fixtures)
    assert ApiSettings().docs_dir == DOCS
    monkeypatch.setenv("CONVERDATA_DOCS", "docs")  # una ruta relativa en la variable también es de la instalación
    assert ApiSettings.from_env().docs_dir == DOCS

    settings = ApiSettings(data_root=tmp_path / "catalog", inventory_path=tmp_path / "inventory.yaml",
                           audit_dir=tmp_path / "audit", curation_dir=tmp_path / "curation", demo=True,
                           demo_fixtures=[FIXTURE], demo_preload_inventory=False, allow_windows_auth=False)
    client = TestClient(create_app(settings, DemoConnector(FIXTURE)))
    login(client, host="demo-sql", alias="SQL demo")
    assert client.get("/admin/manual").json()["markdown"].startswith("# Manual de desarrollo de ConverData")
    assert client.get("/admin/docs/page", params={"path": "wiki/componentes/web.md"}).status_code == 200


def test_la_imagen_de_la_api_trae_lo_que_el_visor_sirve_y_nada_mas_de_docs():
    """`.dockerignore` deja fuera `docs/` salvo la lista fija, y el Dockerfile copia exactamente esa lista."""
    ignore = [line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    reincluded = sorted(line[1:] for line in ignore if line.startswith("!docs"))
    assert "docs/*" in ignore
    assert reincluded == ["docs/architecture/*.html", "docs/architecture/README.md", "docs/manual-desarrollo.md",
                          "docs/wiki"]
    dockerfile = (ROOT / "api" / "Dockerfile").read_text(encoding="utf-8")
    copies = sorted(re.findall(r"^COPY (docs/\S*) ", dockerfile, flags=re.M))
    assert copies == ["docs/architecture/*.html", "docs/architecture/README.md", "docs/manual-desarrollo.md",
                      "docs/wiki"]
    assert not re.search(r"^COPY docs[ /]*\s", dockerfile, flags=re.M)  # nunca la carpeta entera


def test_la_web_alcanza_la_documentacion_por_su_proxy_y_aisla_los_diagramas():
    """La web solo habla con la API por su proxy: `/admin/docs*` debe pasar. El diagrama se pinta en un `iframe` con
    `srcdoc` y `sandbox` sin `allow-same-origin`: origen opaco, sin la cookie de sesión ni acceso a la página."""
    web = ROOT / "web" / "src"
    proxy = (web / "app" / "api" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    allowed = set(re.findall(r'"(\w+)"', re.search(r"const ALLOWED = \[([^\]]*)\]", proxy).group(1)))
    assert "admin" in allowed
    client = (web / "lib" / "api.ts").read_text(encoding="utf-8")
    for route in ('"/admin/docs"', "/admin/docs/page?path=", "/admin/docs/diagram?path="):
        assert route in client, route
    viewer = (web / "components" / "docs-viewer.tsx").read_text(encoding="utf-8")
    assert 'sandbox="allow-scripts allow-downloads"' in viewer and "srcDoc=" in viewer
    assert "allow-same-origin" not in viewer and "allow-top-navigation" not in viewer
    assert "dangerouslySetInnerHTML" not in viewer + (web / "components" / "markdown.tsx").read_text(encoding="utf-8")
