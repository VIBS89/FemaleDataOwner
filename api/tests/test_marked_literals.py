"""F17 CA1, OP-02 CA5 y OP-06 CA1 y CA4 · Prueba de literales marcados de punta a punta.

Cien preguntas, cada una con un literal distinto y reconocible (un documento, una cuenta, un código, un correo, un
número). Se preguntan por la API, se votan, algunas se escalan y un responsable responde. Después se busca el literal
en todo lo que la aplicación guarda: solo puede estar donde vive el texto de las preguntas (D2), es decir, en la
auditoría y en las dudas escaladas. Ni en el catálogo, ni en el conocimiento, ni en las confirmaciones, ni en los
votos, ni en los logs, ni en el índice en memoria.

Corre en los dos almacenamientos: archivos (desarrollo) y la BD `DiscoveryDataAgent` real (necesita `DISCOVERY_DATA_AGENT_TEST_DB`).
"""

import re
import unicodedata

import pytest
from fastapi.testclient import TestClient

from discovery_data_agent.curation import normalize_question
from discovery_data_agent_api.connector import DemoConnector
from discovery_data_agent_api.main import create_app

from test_api import FIXTURE, build, login, settings  # noqa: F401  (fixtures de la API)

# Todo literal de esta prueba lleva una de las dos marcas. Se busca también transformado: en minúsculas, sin guiones y
# recortado a los 6 caracteres del stemmer (`773100`, `cta773`), por si alguien guardara las palabras de la pregunta.
MARKED = re.compile(r"acme|7731\d\d|cta773", re.I)
SQL_MARKED = "{c} LIKE '%acme%' OR {c} LIKE '%7731[0-9][0-9]%' OR {c} LIKE '%cta773%'"
N = 100
BASES = [
    "¿Dónde está el DUI del cliente {}?",
    "¿Dónde está el saldo de la cuenta {}?",
    "¿Dónde está el límite de crédito de la tarjeta {}?",
    "¿Dónde está el correo electrónico del cliente {}?",
    "¿Dónde están los días de mora del préstamo {}?",
]
SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
FORMS = [
    lambda i: f"ACME-TEST-{i:03d}",  # código (el ejemplo de F17)
    lambda i: f"7731{i:04d}-5",  # documento con dígito verificador
    lambda i: f"CTA7731{i:06d}",  # número de cuenta alfanumérico
    lambda i: f"marca{i}@acme-test.example",  # correo
    lambda i: f"7731{i:04d}",  # número suelto
    # Formas que una lista de formatos concretos deja pasar (revisión de seguridad del 2026-11-17)
    lambda i: f"ACME{i:03d}",  # alfanumérico corto: código de cliente, placa
    lambda i: f"7731{i:04d}".translate(SUPERSCRIPT),  # dígitos en superíndice: NFKD los convierte en dígitos corrientes
    lambda i: f"ACME–TEST–{i:03d}",  # raya en vez de guion
    lambda i: f"ACME_TEST_{i:03d}-",  # guion bajo y guion final
    lambda i: f"ａｃｍｅ７７３１{i:04d}",  # ancho completo
]


def literal(i: int) -> str:
    return FORMS[i % len(FORMS)](i)


def question(i: int) -> str:
    # 5 bases × 10 formas: cada base se pregunta con todas las formas de literal.
    return BASES[(i // len(FORMS)) % len(BASES)].format(literal(i))


def marks(text: str) -> list[str]:
    """Marcas en un texto, también si el literal se guardó normalizado (NFKC convierte superíndices y ancho completo)."""
    return MARKED.findall(unicodedata.normalize("NFKC", text))


def test_los_cien_literales_son_distintos_y_todos_llevan_la_marca():
    literals = [literal(i) for i in range(N)]
    assert len(set(literals)) == N and all(marks(x) for x in literals)
    assert len({question(i) for i in range(N)}) == N


@pytest.fixture(params=["archivos", pytest.param("sqlserver", marks=pytest.mark.sqlserver)])
def storage(request, settings, tmp_path):  # noqa: F811
    settings.rate_limit_per_minute = 10_000  # la prueba hace cientos de llamadas con tres usuarios
    settings.log_dir, settings.event_log = tmp_path / "logs", False
    if request.param == "sqlserver":
        settings.db = request.getfixturevalue("empty_catalog_db")
        conn = request.getfixturevalue("db_connect")()
        conn.cursor().execute(
            "DELETE FROM catalog.inventory_server; DELETE FROM curation.steward; DELETE FROM curation.request; "
            "DELETE FROM curation.vote; DELETE FROM golden.golden_discovery_original; DELETE FROM knowledge.golden_discovery")
        conn.commit()
        conn.close()
    return request.param


def run_the_hundred(settings):  # noqa: F811
    """Devuelve (app, cuántas preguntas tuvieron candidato y voto, cuántas se escalaron, cuántas respondió el responsable)."""
    admin = TestClient(create_app(settings, DemoConnector(FIXTURE)))
    login(admin, host="demo-sql", alias="SQL demo")
    assert build(admin)["status"] == "ok"
    users = [admin]
    for name in ("analista", "responsable"):
        client = TestClient(admin.app)
        login(client, user=name)
        users.append(client)
    voted = escalated = answered = 0
    for i in range(N):
        client = users[i % len(users)]
        # El literal va también en el historial de la conversación, que el flujo recibe con cada pregunta.
        history = [question(i - 1)] if i % 4 == 1 else []
        r = client.post("/discover", json={"question": question(i), "history": history})
        assert r.status_code == 200, r.text
        env = r.json()
        candidates = env["discovery"]["candidates"]
        if candidates:
            verdict = "reject" if i % 7 == 0 else "confirm"
            vote = client.post("/discover/feedback", json={"trace_id": env["trace_id"], "verdict": verdict,
                                                           "asset_key": candidates[0]["asset_key"]})
            assert vote.status_code == 200, vote.text
            voted += 1
        if i % 5 == 0:  # la nota también es texto libre del usuario
            req = client.post("/curation/requests", json={"trace_id": env["trace_id"], "note": f"Urge, es {literal(i)}"})
            assert req.status_code == 200, req.text
            escalated += 1
            if i % 10 == 0 and candidates:  # el responsable elige un activo: su respuesta entra al índice
                answer = admin.post(f"/curation/requests/{req.json()['id']}/answer",
                                    json={"kind": "asset", "asset_key": candidates[0]["asset_key"]})
                assert answer.status_code == 200, answer.text
                answered += 1
    admin.app.state.runtime.drain()
    return admin.app, voted, escalated, answered


def files_with_marks(root) -> dict[str, int]:
    found = {}
    for path in root.rglob("*"):
        if path.is_file():
            hits = len(marks(path.read_text(encoding="utf-8", errors="replace")))
            if hits:
                found[path.relative_to(root).as_posix()] = hits
    return found


NOT_TEXT = ("int", "bigint", "smallint", "tinyint", "bit", "float", "real", "decimal", "numeric", "money",
            "date", "datetime", "datetime2", "smalldatetime", "time", "datetimeoffset", "uniqueidentifier")


def columns_with_marks(connect) -> dict[str, int]:
    """Filas con algún literal marcado, por columna, en todas las tablas de la BD (historial incluido). Se revisa toda
    columna que no sea un número, una fecha o un identificador, convertida a texto: una columna nueva de otro tipo
    (xml, binario) no queda fuera de la búsqueda sin que nadie lo decida."""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS ORDER BY 1, 2, 3")
        found = {}
        for schema, table, column, data_type in cur.fetchall():
            if data_type in NOT_TEXT:
                continue
            binary = data_type in ("varbinary", "binary", "image")
            value = (f"CONVERT(nvarchar(max), CONVERT(varbinary(max), [{column}]))" if binary
                     else f"CONVERT(nvarchar(max), [{column}])") + " COLLATE Latin1_General_CI_AI"
            cur.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}] WHERE {SQL_MARKED.format(c=value)}")
            hits = cur.fetchone()[0]
            if hits:
                found[f"{schema}.{table}.{column}"] = hits
        return found
    finally:
        conn.close()


def test_el_literal_de_una_pregunta_solo_queda_donde_viven_las_preguntas(storage, settings, tmp_path, request):  # noqa: F811
    app, voted, escalated, answered = run_the_hundred(settings)
    # La prueba ejercita de verdad los caminos que escriben: votos, dudas escaladas y respuestas del responsable.
    assert voted >= 80 and escalated == 20 and answered >= 8

    # 1. El índice en memoria y lo aprendido: plantillas sin el literal.
    runtime = app.state.runtime
    knowledge = runtime.service.deps.knowledge
    assert len(knowledge.golden) >= 5, "las preguntas con literales distintos deben agruparse en pocas confirmaciones"
    learned = " ".join(g.template for g in knowledge.golden) + " ".join(i.text for i in knowledge.all_items())
    assert not marks(learned), marks(learned)[:5]
    described = " ".join(f"{o.description} {' '.join(str(c.description) for c in o.columns)}"
                         for o in runtime.service.deps.catalog.objects)
    assert not marks(described)
    # Las plantillas solo tienen las palabras de las cinco preguntas base: ninguna palabra de un literal.
    assert {w for g in knowledge.golden for w in g.template.split()} <= {w for b in BASES for w in normalize_question(b.format("")).split()}

    # 2. El disco del servidor de aplicación (catálogo, curación, logs, temporales del build).
    on_disk = files_with_marks(tmp_path)
    if storage == "archivos":
        allowed = {name for name in on_disk if name.startswith("audit/") or name == "curation/requests.json"}
        assert set(on_disk) == allowed, sorted(set(on_disk) - allowed)
        assert sum(hits for name, hits in on_disk.items() if name.startswith("audit/")) >= N  # control: ahí sí están
        assert on_disk["curation/requests.json"] >= escalated
        assert (tmp_path / "curation" / "feedback.jsonl").is_file()  # los votos existen, y sin el literal
        assert (tmp_path / "logs").is_dir() and any((tmp_path / "logs").iterdir())
        return
    assert on_disk == {}, on_disk  # con BD el servidor no guarda preguntas en ningún archivo, tampoco en los logs

    # 3. La BD `DiscoveryDataAgent`: solo en la auditoría y en las dudas escaladas.
    found = columns_with_marks(request.getfixturevalue("db_connect"))
    assert set(found) == {"audit.audit_question.question", "curation.request.question", "curation.request.note"}, found
    assert found["audit.audit_question.question"] >= N  # control: la búsqueda sí encuentra lo que está
    assert found["curation.request.question"] == escalated and found["curation.request.note"] == escalated
