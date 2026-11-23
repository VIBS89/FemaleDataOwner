"""DDL de la BD `ConverData` (HU-04, OP-02 §BD de trabajo, OP-05): comprobaciones estáticas sobre `db/converdata/*.sql`.

Prueban la **forma** y los permisos, no que SQL Server acepte el T-SQL: eso lo hacen los tests con marca `sqlserver` (SD-3)
de `test_storage_migrations.py`, que también comprueban los roles, `dbo.schema_version` y la ausencia de tablas de grafo.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

DB_DIR = Path(__file__).parents[1] / "db" / "converdata"
SCRIPT = re.compile(r"^(\d{3})_[a-z][a-z0-9_]*\.sql$")


def _sin_comentarios(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def _scripts() -> dict[str, str]:
    return {p.name: _sin_comentarios(p.read_text(encoding="utf-8")) for p in sorted(DB_DIR.glob("*.sql"))}


@pytest.fixture(scope="module")
def sql() -> dict[str, str]:
    return _scripts()


@pytest.fixture(scope="module")
def todo(sql) -> str:
    return "\n".join(sql.values())


def _permisos(todo: str) -> dict[str, list[tuple[str, set[str], str]]]:
    """rol → [(GRANT|DENY, {permisos}, objetivo)]."""
    por_rol = defaultdict(list)
    for verbo, permisos, objetivo, rol in re.findall(
        r"\b(GRANT|DENY)\s+([A-Z ,]+?)\s+ON\s+([\w:.\[\]]+)\s+TO\s+(\w+)", todo, flags=re.IGNORECASE
    ):
        por_rol[rol.lower()].append((verbo.upper(), {p.strip().upper() for p in permisos.split(",")}, objetivo.lower()))
    return por_rol


def _tablas(sql_texto: str, esquema: str) -> dict[str, str]:
    """nombre → texto de la sentencia CREATE TABLE del esquema."""
    out = {}
    for m in re.finditer(rf"CREATE\s+TABLE\s+{esquema}\.(\[?\w+\]?)(.*?)(?=\bGO\b|\bCREATE\s+TABLE\b|\Z)", sql_texto,
                         flags=re.IGNORECASE | re.DOTALL):
        out[m.group(1).strip("[]").lower()] = m.group(0)
    return out


def test_los_scripts_estan_numerados_sin_huecos_desde_001(sql):
    numeros = [int(SCRIPT.match(nombre).group(1)) for nombre in sql]
    assert numeros == list(range(1, len(numeros) + 1)), sql.keys()


def test_cada_script_separa_lotes_con_go_y_termina_en_go(sql):
    for nombre, texto in sql.items():
        assert re.search(r"(?m)^\s*GO\s*$", texto), nombre
        assert re.search(r"(?m)^\s*GO\s*\Z", texto.rstrip() + "\n") or texto.rstrip().endswith("GO"), nombre


def test_ningun_script_destruye_datos_ni_lleva_contrasenas(todo):
    assert not re.search(r"\b(DROP\s+(TABLE|SCHEMA|DATABASE)|TRUNCATE)\b", todo, flags=re.IGNORECASE)
    assert not re.search(r"\b(PASSWORD|PWD)\b", todo, flags=re.IGNORECASE)


def test_las_tablas_de_metadatos_no_tienen_columnas_para_valores_de_datos(todo):
    """OP-02 CA5: fuera de audit, golden y curation no hay valores ni literales."""
    for esquema in ("catalog", "knowledge"):
        for nombre, definicion in _tablas(todo, esquema).items():
            columnas = re.findall(r"(?m)^\s*\[?(\w+)\]?\s+(?:nvarchar|varchar|int|bigint|bit|datetime2|sysname|uniqueidentifier|char)",
                                  definicion, flags=re.IGNORECASE)
            prohibidas = [c for c in columnas if re.search(r"sample|literal|row_value|cell", c, flags=re.IGNORECASE)]
            assert not prohibidas, f"{esquema}.{nombre}: {prohibidas}"


def test_converdata_app_no_puede_actualizar_ni_borrar_la_auditoria(todo):
    deniega = [p for v, p, o in _permisos(todo)["converdata_app"] if v == "DENY" and o == "schema::audit"]
    assert any({"UPDATE", "DELETE"} <= permisos for permisos in deniega)
