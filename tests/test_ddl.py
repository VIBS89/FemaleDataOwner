"""DDL de la BD `ConverData` (HU-04, OP-02 §BD de trabajo, OP-05): comprobaciones estáticas sobre `db/converdata/*.sql`.

Prueban la **forma** y los permisos, no que SQL Server acepte el T-SQL: eso lo hacen los tests con marca `sqlserver` (SD-3).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

DB_DIR = Path(__file__).parents[1] / "db" / "converdata"
SCRIPT = re.compile(r"^(\d{3})_[a-z][a-z0-9_]*\.sql$")
TIPOS_DE_ARISTA = {
    "same_entity", "fk_declared", "view_join", "proc_join", "cross_db_reference",
    "query_store_join", "inferred_inclusion", "etl",
}


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


def test_hay_los_cuatro_scripts_de_s1(sql):
    assert [n.split("_", 1)[1] for n in sql][:4] == ["esquemas.sql", "estate.sql", "semantic.sql", "roles_y_version.sql"]


def test_cada_script_separa_lotes_con_go_y_termina_en_go(sql):
    for nombre, texto in sql.items():
        assert re.search(r"(?m)^\s*GO\s*$", texto), nombre
        assert re.search(r"(?m)^\s*GO\s*\Z", texto.rstrip() + "\n") or texto.rstrip().endswith("GO"), nombre


def test_ningun_script_destruye_datos_ni_lleva_contrasenas(todo):
    assert not re.search(r"\b(DROP\s+(TABLE|SCHEMA|DATABASE)|TRUNCATE)\b", todo, flags=re.IGNORECASE)
    assert not re.search(r"\b(PASSWORD|PWD)\b", todo, flags=re.IGNORECASE)


def test_estate_define_nodos_y_aristas_de_grafo(sql):
    texto = sql["002_estate.sql"]
    assert re.search(r"CREATE\s+SCHEMA\s+estate\b", texto, flags=re.IGNORECASE)
    assert len(re.findall(r"\bAS\s+NODE\b", texto, flags=re.IGNORECASE)) >= 2
    assert len(re.findall(r"\bAS\s+EDGE\b", texto, flags=re.IGNORECASE)) >= 1


def test_las_aristas_cubren_los_tipos_de_f19_con_confianza_entre_0_y_1(sql):
    relacion = _tablas(sql["002_estate.sql"], "estate")["relation"]
    assert TIPOS_DE_ARISTA == set(re.findall(r"'(\w+)'", re.search(r"kind[^,]*?IN\s*\((.*?)\)", relacion, re.DOTALL).group(1)))
    assert re.search(r"confidence[^,]*BETWEEN\s+0(\.0)?\s+AND\s+1(\.0)?", relacion, flags=re.IGNORECASE)
    assert re.search(r"\bevidence_json\b", relacion) and re.search(r"\breviewed\b", relacion)


def test_los_sketches_minhash_no_se_guardan(sql):
    """HU-07 / OP-02: los sketches solo viven en memoria durante el job."""
    assert not re.search(r"minhash|sketch", sql["002_estate.sql"], flags=re.IGNORECASE)


def test_semantic_define_el_modelo_de_f21_con_historial_temporal(sql):
    tablas = _tablas(sql["003_semantic.sql"], "semantic")
    assert {"entity", "dimension", "measure", "metric", "verified_query"} <= set(tablas)
    for nombre, definicion in tablas.items():
        assert "SYSTEM_VERSIONING = ON" in definicion, nombre
    assert re.search(r"\bcertified\b", tablas["metric"]) and re.search(r"\bowner\b", tablas["metric"])


def test_las_tablas_de_metadatos_no_tienen_columnas_para_valores_de_datos(todo):
    """OP-02 CA5: fuera de audit, golden y curation no hay valores ni literales."""
    for esquema in ("catalog", "estate", "knowledge", "semantic"):
        for nombre, definicion in _tablas(todo, esquema).items():
            columnas = re.findall(r"(?m)^\s*\[?(\w+)\]?\s+(?:nvarchar|varchar|int|bigint|bit|datetime2|sysname|uniqueidentifier|VECTOR|char)",
                                  definicion, flags=re.IGNORECASE)
            prohibidas = [c for c in columnas if re.search(r"sample|literal|row_value|cell", c, flags=re.IGNORECASE)]
            assert not prohibidas, f"{esquema}.{nombre}: {prohibidas}"


def test_hay_tabla_de_version_con_los_scripts_aplicados(sql):
    texto = sql["004_roles_y_version.sql"]
    assert re.search(r"CREATE\s+TABLE\s+dbo\.schema_version", texto, flags=re.IGNORECASE)
    for columna in ("script", "applied_at", "checksum"):
        assert columna in texto


def test_converdata_app_no_puede_actualizar_ni_borrar_la_auditoria(todo):
    deniega = [p for v, p, o in _permisos(todo)["converdata_app"] if v == "DENY" and o == "schema::audit"]
    assert any({"UPDATE", "DELETE"} <= permisos for permisos in deniega)


def test_converdata_app_solo_lee_el_grafo_y_la_capa_semantica(todo):
    sobre = {o: p for v, p, o in _permisos(todo)["converdata_app"] if v == "GRANT"}
    assert sobre["schema::estate"] == {"SELECT"}
    assert sobre["schema::semantic"] == {"SELECT"}


def test_el_auditor_solo_tiene_select_en_audit(todo):
    permisos = _permisos(todo)["auditor"]
    assert permisos, "falta el rol auditor"
    assert all(v == "GRANT" and p == {"SELECT"} and o == "schema::audit" for v, p, o in permisos)
    assert re.search(r"CREATE\s+ROLE\s+auditor\b", todo, flags=re.IGNORECASE)


def test_el_builder_escribe_catalog_estate_y_knowledge_y_no_toca_audit(todo):
    permisos = _permisos(todo)["converdata_builder"]
    escribe = {o for v, p, o in permisos if v == "GRANT" and {"INSERT", "UPDATE", "DELETE"} <= p}
    assert {"schema::catalog", "schema::estate", "schema::knowledge"} <= escribe
    assert not [o for v, p, o in permisos if v == "GRANT" and "audit" in o]
    denegado = [p for v, p, o in permisos if v == "DENY" and o == "schema::audit"]
    assert denegado and {"INSERT", "UPDATE", "DELETE", "SELECT"} <= denegado[0]
    assert re.search(r"CREATE\s+ROLE\s+converdata_builder\b", todo, flags=re.IGNORECASE)
