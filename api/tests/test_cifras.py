"""Cifras agregadas en la API (primer corte del AskFlow): apagadas por defecto, sin ejecutor en modo demo y, encendidas con
un conector que abre conexiones de datos, la respuesta de `POST /discover` trae `figure`.

El conector con datos es un doble (sin SQL Server): registra el SQL que recibe y contesta totales fijos.
"""

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from discovery_data_agent.discovery import figures
from discovery_data_agent_api import runtime as runtime_module
from discovery_data_agent_api.connector import DemoConnector
from discovery_data_agent_api.main import create_app
from discovery_data_agent_api.settings import ApiSettings

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "bancos"
TOTAL = 4321
REGISTROS = 5000  # `n` del total: por encima del umbral de celdas pequeñas
TAIL = " OPTION (MAXDOP 1)"
SQL_TOTAL = f"SELECT COUNT_BIG(*) AS valor, COUNT_BIG(*) AS n FROM [BancaPrestamos].[dbo].[Prestamos]{TAIL}"
JOIN = ("[BancaPrestamos].[dbo].[Prestamos] AS f JOIN [BancaPrestamos].[dbo].[Clientes] AS d "
        "ON f.[ClienteID] = d.[ClienteID]")
SQL_UNION_CARDINALIDAD = f"SELECT COUNT_BIG(DISTINCT d.[Segmento]) AS valor FROM {JOIN}{TAIL}"
SQL_UNION_GRUPOS = (f"SELECT TOP (25) d.[Segmento] AS grupo, SUM(CAST(f.[SaldoCapital] AS decimal(38, 4))) AS valor, "
                    f"COUNT_BIG(*) AS n FROM {JOIN} GROUP BY d.[Segmento] ORDER BY valor DESC{TAIL}")
SQL_SET = "SET LOCK_TIMEOUT 5000; SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;"


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, sql):
        owner = self.conn.owner
        if sql.startswith("SET "):  # ajustes de la sesion de solo lectura: no son la consulta de la cifra
            self.conn.settings.append(sql)
            self.conn.sequence.append("set")
            return
        self.conn.sequence.append("query")
        owner.queries.append((self.conn.database, sql))
        owner.order.append("query")
        if "AS grupo" in sql:
            self.rows = list(owner.groups)
        elif " AS n " not in sql:
            self.rows = [(4,)]  # cardinalidad
        else:
            self.rows = [(owner.total, REGISTROS)]
        if owner.gate is not None:
            owner.entered.release()
            owner.gate.wait(10)
        if owner.fail:
            raise PermissionError("The SELECT permission was denied on the object 'Prestamos'")

    def fetchmany(self, n):
        self.conn.fetch_sizes.append(n)
        return (self.rows * 200)[:n] if owner_many(self.conn) else self.rows[:n]


def owner_many(conn) -> bool:
    return conn.owner.many_rows


class _Connection:
    def __init__(self, owner, database):
        self.owner, self.database, self.timeout, self.closed = owner, database, None, False
        self.settings, self.rolled_back, self.autocommit = [], 0, True
        self.sequence: list[str] = []
        self.fetch_sizes: list[int] = []

    def rollback(self):
        self.rolled_back += 1

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True
        self.owner.closed += 1


class ConnectorConDatos(DemoConnector):
    """El conector demo más `connect()`: lo que `figure_executor` necesita para abrir una conexión de datos."""

    def __init__(self, fixtures, fail=False):
        super().__init__(fixtures)
        self.queries: list[tuple[str, str]] = []
        self.connections: list[_Connection] = []
        self.closed = 0
        self.fail = fail
        self.total = TOTAL
        self.groups = [("A", 1, 40), ("B", 2, 30)]  # (etiqueta, valor, n)
        self.many_rows = False
        self.order: list[str] = []  # "audit" / "connect" / "query", en el orden en que ocurrieron
        self.gate: threading.Event | None = None  # si existe, la consulta espera a que se abra
        self.entered = threading.Semaphore(0)

    def connect(self, server, cred, database="master"):
        self.order.append("connect")
        conn = _Connection(self, database)
        self.connections.append(conn)
        return conn


@pytest.fixture
def settings(tmp_path):
    return ApiSettings(
        data_root=tmp_path / "catalog", inventory_path=tmp_path / "inventory.yaml", audit_dir=tmp_path / "audit",
        curation_dir=tmp_path / "curation", demo=True, demo_fixtures=[FIXTURE], demo_preload_inventory=False,
        allow_windows_auth=False,
    )


def _arranca(settings, connector):
    client = TestClient(create_app(settings, connector))
    r = client.post("/auth/login", json={"login": "demo", "password": "demo", "host": "demo-sql", "alias": "SQL demo"})
    assert r.status_code == 200, r.text
    assert client.post("/admin/catalog/build", json={"enrich": False}).status_code == 202
    for _ in range(200):
        job = client.get("/admin/catalog/build").json()
        if job["status"] != "running":
            assert job["status"] == "ok", job
            return client
        time.sleep(0.05)
    raise AssertionError("la construcción no terminó")


def _sesion(client):
    runtime = client.app.state.runtime
    sesiones = runtime.vault.sessions()
    assert sesiones
    return runtime, sesiones[0]


# --- Ajuste -------------------------------------------------------------------------------------------------------


def test_ask_flow_esta_apagado_por_defecto():
    assert ApiSettings().ask_flow is False


def test_ask_flow_se_enciende_con_la_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("DISCOVERY_DATA_AGENT_ASK_FLOW", "1")
    assert ApiSettings.from_env().ask_flow is True
    monkeypatch.delenv("DISCOVERY_DATA_AGENT_ASK_FLOW")
    assert ApiSettings.from_env().ask_flow is False


# --- figure_executor ------------------------------------------------------------------------------------------------


def test_sin_ask_flow_no_hay_ejecutor_aunque_el_conector_abra_conexiones(settings):
    client = _arranca(settings, ConnectorConDatos(FIXTURE))
    runtime, session = _sesion(client)
    assert settings.ask_flow is False
    assert runtime.figure_executor(session) is None


def test_en_modo_demo_no_hay_ejecutor_aunque_ask_flow_este_activo(settings):
    """El conector demo no abre conexiones de datos: no existe `connect`."""
    settings.ask_flow = True
    client = _arranca(settings, DemoConnector(FIXTURE))
    runtime, session = _sesion(client)
    assert not hasattr(runtime.connector, "connect")
    assert runtime.figure_executor(session) is None


def test_con_ask_flow_y_conector_con_datos_el_ejecutor_usa_la_credencial_de_la_sesion(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    runtime, session = _sesion(client)
    ejecutor = runtime.figure_executor(session)
    assert callable(ejecutor)
    server_id = session.servers[0]
    filas = ejecutor(server_id, "BancaPrestamos", SQL_TOTAL)
    assert filas == [(TOTAL, REGISTROS)]
    assert conector.queries[-1][0] == "BancaPrestamos"
    conexion = conector.connections[-1]
    assert conexion.closed and conexion.timeout and conexion.timeout > 0  # con tiempo límite y siempre cerrada


def test_el_ejecutor_rechaza_un_servidor_sin_credencial_en_la_sesion(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    runtime, session = _sesion(client)
    with pytest.raises(PermissionError):
        runtime.figure_executor(session)("OTRO_SERVIDOR", "BancaPrestamos", SQL_TOTAL)
    assert conector.connections == []
    assert runtime.audit.recent(kind="figure_query") == []  # sin credencial no se llegó ni a auditar


def _con_politica(settings, *, environment, figures):
    """Sesión demo cuyo servidor tiene el ambiente y el `figures` dados en el inventario."""
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    runtime, session = _sesion(client)
    server = runtime.inventory.server(session.servers[0])
    server.environment, server.figures = environment, figures
    return runtime, session, conector


@pytest.mark.parametrize("environment, figures, permitido", [
    ("produccion", None, False),   # producción exige declararlo
    ("produccion", True, True),
    ("produccion", False, False),
    ("desarrollo", None, True),    # otros ambientes: sí, salvo que se prohíba
    ("desarrollo", True, True),
    ("desarrollo", False, False),
    ("qa", None, True),
])
def test_politica_de_cifras_por_servidor(settings, environment, figures, permitido):
    runtime, session, conector = _con_politica(settings, environment=environment, figures=figures)
    ejecutor = runtime.figure_executor(session)
    if permitido:
        assert ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL) == [(TOTAL, REGISTROS)]
        assert len(runtime.audit.recent(kind="figure_query")) == 1
    else:
        with pytest.raises(PermissionError):
            ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
        assert conector.connections == [] and conector.queries == []
        assert runtime.audit.recent(kind="figure_query") == []


def test_servidor_no_autorizado_no_abre_conexion_ni_audita_aunque_se_reintente(settings):
    runtime, session, conector = _con_politica(settings, environment="produccion", figures=None)
    ejecutor = runtime.figure_executor(session)
    for _ in range(2):
        with pytest.raises(PermissionError):
            ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    assert conector.connections == [] and runtime.audit.recent(kind="figure_query") == []


def test_el_ejecutor_cierra_la_conexion_si_la_consulta_falla(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE, fail=True)
    client = _arranca(settings, conector)
    runtime, session = _sesion(client)
    with pytest.raises(PermissionError):
        runtime.figure_executor(session)(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    assert conector.closed == 1
    assert conector.connections[0].rolled_back == 1


# --- POST /discover -------------------------------------------------------------------------------------------------


def test_discover_apagado_no_trae_cifra_ni_consulta_datos(settings):
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    env = client.post("/discover", json={"question": "cuantos clientes tienen prestamos?"}).json()
    assert env["flow"] == "discover" and env.get("figure") is None
    assert conector.queries == []
    assert any("Todavía no calculo cifras" in a for a in env["assumptions"])


def test_discover_en_demo_con_ask_flow_no_trae_cifra(settings):
    settings.ask_flow = True
    client = _arranca(settings, DemoConnector(FIXTURE))
    env = client.post("/discover", json={"question": "cuantos clientes tienen prestamos?"}).json()
    assert env["flow"] == "discover" and env.get("figure") is None


def test_discover_con_ask_flow_y_conector_con_datos_trae_la_cifra(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    r = client.post("/discover", json={"question": "cuantos clientes tienen prestamos?"})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["flow"] == "ask"
    assert env["figure"]["value"] == TOTAL
    assert env["figure"]["operation"] == "COUNT_DISTINCT"
    assert "4,321" in env["answer_text"]
    assert [q[0] for q in conector.queries] == ["BancaPrestamos"]
    assert all(figures.ALLOWED_SQL.match(sql) for _, sql in conector.queries), conector.queries


def test_discover_stream_con_cifra_emite_compute_y_la_respuesta_trae_figure(settings):
    settings.ask_flow = True
    client = _arranca(settings, ConnectorConDatos(FIXTURE))
    with client.stream("POST", "/discover/stream", json={"question": "cuantos clientes tienen prestamos?"}) as r:
        assert r.status_code == 200
        texto = "".join(r.iter_text())
    assert "compute" in texto and '"figure"' in texto and str(TOTAL) in texto


def test_discover_si_el_servidor_niega_el_permiso_responde_sin_cifra_y_sin_el_mensaje(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE, fail=True)
    client = _arranca(settings, conector)
    r = client.post("/discover", json={"question": "cuantos clientes tienen prestamos?"})
    assert r.status_code == 200
    env = r.json()
    assert env["status"] == "ok" and env["flow"] == "discover" and env.get("figure") is None
    assert any("No pude calcular la cifra" in a for a in env["assumptions"])
    assert "SELECT permission was denied" not in r.text
    assert conector.closed == len(conector.connections) >= 1


def test_discover_un_analista_sin_acceso_a_leasing_no_provoca_sql_sobre_leasing(settings):
    """F14 con el flujo completo: el analista (solo BancaPrestamos y BancaCuentasDebito) pregunta por leasing."""
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)  # el admin construye el catálogo
    conector.queries.clear()
    analista = TestClient(client.app)
    r = analista.post("/auth/login", json={"login": "analista", "password": "demo"})
    assert r.status_code == 200, r.text
    r = analista.post("/discover", json={"question": "cuantos contratos de leasing hay"})
    assert r.status_code == 200 and "BancaLeasing" not in r.text
    assert not any(db == "BancaLeasing" or "BancaLeasing" in sql for db, sql in conector.queries), conector.queries
    r = analista.post("/discover", json={"question": "cuantos clientes tienen prestamos?"})
    assert r.json()["figure"]["value"] == TOTAL  # lo que sí ve, se calcula
    assert {db for db, _ in conector.queries} <= {"BancaPrestamos", "BancaCuentasDebito"}


# --- figure_executor: controles de seguridad ------------------------------------------------------------------------


def _ejecutor(settings, conector=None):
    settings.ask_flow = True
    conector = conector or ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    runtime, session = _sesion(client)
    conector.queries.clear()
    conector.order.clear()
    return client, runtime, session, conector, runtime.figure_executor(session)


FUERA_DE_PLANTILLA = [
    "SELECT * FROM [BancaPrestamos].[dbo].[Clientes]",
    "SELECT [DUI] FROM [BancaPrestamos].[dbo].[Clientes]" + TAIL,
    SQL_TOTAL + "; DROP TABLE [Prestamos]",
    SQL_TOTAL.replace(TAIL, ""),
    SQL_TOTAL + " -- x",
    "DELETE FROM [BancaPrestamos].[dbo].[Prestamos]",
    "SELECT COUNT_BIG(*) AS valor, COUNT_BIG(*) AS n FROM BancaPrestamos.dbo.Prestamos" + TAIL,
    "SELECT COUNT_BIG(*) AS valor FROM [BancaPrestamos].[dbo].[Prestamos]" + TAIL,  # la forma de antes: ya no existe
    "",
    # con unión: solo la plantilla exacta (alias f/d, una sola unión por llave, sin condiciones extra)
    SQL_UNION_GRUPOS.replace(" AS f JOIN", " AS f LEFT JOIN"),
    SQL_UNION_GRUPOS.replace(" AS d ON", " AS e ON"),
    SQL_UNION_GRUPOS.replace(" GROUP BY", " WHERE d.[Segmento] = 'x' GROUP BY"),
    SQL_UNION_GRUPOS.replace("f.[ClienteID] = d.[ClienteID]", "f.[ClienteID] = d.[ClienteID] OR 1 = 1"),
    SQL_UNION_GRUPOS.replace(" AS d ON", " AS d JOIN [BancaPrestamos].[dbo].[Garantias] AS g ON g.[PrestamoID] = f.[PrestamoID] AND"),
    SQL_UNION_GRUPOS.removesuffix(TAIL),
    SQL_UNION_GRUPOS.replace("d.[Segmento] AS grupo", "d.Segmento AS grupo"),
    SQL_UNION_GRUPOS.replace("GROUP BY d.[Segmento]", "GROUP BY d.[Segmento]; DROP TABLE [Clientes] --"),
    "SELECT TOP (25) d.[DUI] AS grupo, COUNT_BIG(*) AS valor, COUNT_BIG(*) AS n FROM " + JOIN + " GROUP BY d.[DUI]",
]


@pytest.mark.parametrize("sql", FUERA_DE_PLANTILLA)
def test_el_ejecutor_rechaza_un_sql_fuera_de_plantilla_sin_abrir_conexion(settings, sql):
    _, runtime, session, conector, ejecutor = _ejecutor(settings)
    with pytest.raises(ValueError):
        ejecutor(session.servers[0], "BancaPrestamos", sql)
    assert conector.connections == [] and conector.queries == []
    assert runtime.audit.recent(kind="figure_query") == [], "lo rechazado tampoco se audita como consulta"


def test_el_ejecutor_valida_el_sql_antes_que_la_credencial(settings):
    """Con un servidor sin credencial y un SQL libre el error es el de la plantilla: nada llega a la sesión."""
    _, _, session, conector, ejecutor = _ejecutor(settings)
    with pytest.raises(ValueError):
        ejecutor("OTRO_SERVIDOR", "BancaPrestamos", "DROP TABLE x")
    assert conector.connections == []


def test_la_sesion_es_de_solo_lectura_sin_bloqueos_y_siempre_se_revierte(settings):
    _, _, session, conector, ejecutor = _ejecutor(settings)
    ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    [conexion] = conector.connections
    assert conexion.settings == [SQL_SET]
    assert "LOCK_TIMEOUT 5000" in SQL_SET and "READ UNCOMMITTED" in SQL_SET
    assert conexion.sequence == ["set", "query"], "los ajustes de sesión van antes de la consulta"
    assert conexion.autocommit is False
    assert conexion.rolled_back == 1 and conexion.closed
    assert conexion.timeout == runtime_module.FIGURE_TIMEOUT_S


def test_el_tiempo_limite_de_la_consulta_es_el_declarado(settings):
    assert runtime_module.FIGURE_TIMEOUT_S == 15
    _, _, session, conector, ejecutor = _ejecutor(settings)
    ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    assert conector.connections[0].timeout == runtime_module.FIGURE_TIMEOUT_S


def test_el_ejecutor_nunca_trae_mas_de_figure_max_rows_filas(settings):
    conector = ConnectorConDatos(FIXTURE)
    conector.many_rows = True
    _, _, session, conector, ejecutor = _ejecutor(settings, conector)
    filas = ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    assert runtime_module.FIGURE_MAX_ROWS == 50
    assert conector.connections[0].fetch_sizes == [runtime_module.FIGURE_MAX_ROWS]
    assert len(filas) == runtime_module.FIGURE_MAX_ROWS and all(isinstance(f, tuple) for f in filas)


def test_si_la_consulta_falla_se_revierte_y_se_cierra_una_sola_vez(settings):
    conector = ConnectorConDatos(FIXTURE, fail=True)
    _, _, session, conector, ejecutor = _ejecutor(settings, conector)
    with pytest.raises(PermissionError):
        ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    [conexion] = conector.connections
    assert conexion.rolled_back == 1 and conexion.closed and conector.closed == 1


# --- figure_executor: auditoría de la consulta (F11) ----------------------------------------------------------------


def test_la_consulta_se_audita_antes_de_abrir_la_conexion(settings):
    _, runtime, session, conector, ejecutor = _ejecutor(settings)
    original = runtime.audit.event

    def registra(kind, user_id, **data):
        conector.order.append("audit")
        return original(kind, user_id, **data)

    runtime.audit.event = registra
    ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    assert conector.order == ["audit", "connect", "query"]


def test_el_evento_figure_query_dice_quien_donde_y_que_consulta(settings):
    _, runtime, session, conector, ejecutor = _ejecutor(settings)
    ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    [evento] = runtime.audit.recent(kind="figure_query")
    assert evento["type"] == "figure_query" and evento["user_id"] == session.user_id
    assert evento["server"] == session.servers[0] and evento["database"] == "BancaPrestamos"
    assert evento["sql"] == SQL_TOTAL
    assert set(evento) - {"hash", "prev"} == {"ts", "type", "user_id", "server", "database", "sql"}  # + cadena de hash


def test_si_la_auditoria_falla_la_consulta_no_se_ejecuta(settings):
    """F11 fail-closed también para el acceso a los datos: sin registro no hay consulta, ni siquiera conexión."""
    _, runtime, session, conector, ejecutor = _ejecutor(settings)

    def rota(kind, user_id, **data):
        raise RuntimeError("sin disco")

    runtime.audit.event = rota
    with pytest.raises(RuntimeError):
        ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    assert conector.connections == [] and conector.queries == []


def test_si_la_auditoria_falla_el_hueco_de_concurrencia_se_libera(settings):
    _, runtime, session, conector, ejecutor = _ejecutor(settings)
    original = runtime.audit.event
    runtime.audit.event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin disco"))
    for _ in range(runtime_module.FIGURE_CONCURRENCY + 2):  # más intentos fallidos que huecos
        with pytest.raises(RuntimeError):
            ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    runtime.audit.event = original
    assert ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL) == [(TOTAL, REGISTROS)]


def test_discover_si_la_auditoria_de_la_consulta_falla_responde_sin_cifra_y_sin_consultar(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    runtime, _ = _sesion(client)
    conector.queries.clear()
    original = runtime.audit.event

    def rota(kind, user_id, **data):
        if kind == "figure_query":
            raise RuntimeError("sin disco")
        return original(kind, user_id, **data)

    runtime.audit.event = rota
    env = client.post("/discover", json={"question": "cuantos clientes tienen prestamos?"}).json()
    assert env.get("figure") is None and env["flow"] == "discover"
    assert conector.queries == [] and not [c for c in conector.connections if c.sequence]
    assert str(TOTAL) not in env["answer_text"]


def test_el_evento_figure_query_no_trae_valores_ni_etiquetas_de_grupo(settings):
    """HU-21 / F17: la auditoría de la consulta dice qué se consultó, nunca qué devolvió."""
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    conector.total = 987654321
    conector.groups = [("ETIQUETA-SECRETA", 555444333, 60), ("OTRA-ETIQUETA", 222111000, 50)]
    client = _arranca(settings, conector)
    env = client.post("/discover", json={"question": "cuantos prestamos hay por categoria de riesgo"}).json()
    assert env["figure"]["value"] == 987654321  # la respuesta sí los lleva
    assert [g["label"] for g in env["figure"]["groups"]] == ["ETIQUETA-SECRETA", "OTRA-ETIQUETA"]
    runtime, _ = _sesion(client)
    eventos = runtime.audit.recent(kind="figure_query")
    assert len(eventos) == 3  # total, cardinalidad y grupos: cada consulta deja su evento
    texto = repr(eventos)
    for valor in ("987654321", "555444333", "222111000", "ETIQUETA-SECRETA", "OTRA-ETIQUETA"):
        assert valor not in texto, valor
    for evento in eventos:
        assert set(evento) - {"hash", "prev"} == {"ts", "type", "user_id", "server", "database", "sql"}  # + cadena de hash
        assert figures.ALLOWED_SQL.match(evento["sql"])


# --- figure_executor: concurrencia ---------------------------------------------------------------------------------


def test_el_tope_de_concurrencia_es_dos():
    assert runtime_module.FIGURE_CONCURRENCY == 2


def test_sin_hueco_el_ejecutor_lanza_timeout_sin_abrir_conexion_ni_auditar(settings):
    conector = ConnectorConDatos(FIXTURE)
    _, runtime, session, conector, ejecutor = _ejecutor(settings, conector)
    conector.gate = threading.Event()
    hilos = [threading.Thread(target=ejecutor, args=(session.servers[0], "BancaPrestamos", SQL_TOTAL), daemon=True)
             for _ in range(runtime_module.FIGURE_CONCURRENCY)]
    try:
        for hilo in hilos:
            hilo.start()
        for _ in hilos:  # esperar a que las dos consultas estén dentro del servidor
            assert conector.entered.acquire(timeout=10)
        abiertas, auditadas = len(conector.connections), len(runtime.audit.recent(kind="figure_query"))
        with pytest.raises(TimeoutError):
            ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL)
        assert len(conector.connections) == abiertas == runtime_module.FIGURE_CONCURRENCY
        assert len(runtime.audit.recent(kind="figure_query")) == auditadas
    finally:
        conector.gate.set()
        for hilo in hilos:
            hilo.join(10)
    # liberados los huecos, vuelve a funcionar
    assert ejecutor(session.servers[0], "BancaPrestamos", SQL_TOTAL) == [(TOTAL, REGISTROS)]


def test_el_semaforo_es_global_a_todas_las_sesiones(settings):
    """El tope es de la API, no de cada sesión: lo comparten los ejecutores de sesiones distintas."""
    _, runtime, session, conector, ejecutor = _ejecutor(settings)
    otro = runtime.figure_executor(session)
    conector.gate = threading.Event()
    hilos = [threading.Thread(target=ejecutor, args=(session.servers[0], "BancaPrestamos", SQL_TOTAL), daemon=True)
             for _ in range(runtime_module.FIGURE_CONCURRENCY)]
    try:
        for hilo in hilos:
            hilo.start()
        for _ in hilos:
            assert conector.entered.acquire(timeout=10)
        with pytest.raises(TimeoutError):
            otro(session.servers[0], "BancaPrestamos", SQL_TOTAL)
    finally:
        conector.gate.set()
        for hilo in hilos:
            hilo.join(10)


def test_discover_con_la_cifra_suprimida_por_pocos_registros_no_trae_numero(settings, monkeypatch):
    settings.ask_flow = True
    monkeypatch.setattr(sys.modules[__name__], "REGISTROS", 3)
    client = _arranca(settings, ConnectorConDatos(FIXTURE))
    env = client.post("/discover", json={"question": "cuantos clientes tienen prestamos?"}).json()
    assert env["flow"] == "ask" and env["figure"]["value"] is None
    assert str(TOTAL) not in env["answer_text"] and "4,321" not in env["answer_text"]
    assert env["answer_text"].startswith("No muestro la cifra")


# --- figure_executor: consultas con unión (desglose por una categoría de una tabla relacionada) -----------------------


def test_las_dos_formas_con_union_pasan_check_sql():
    assert figures.check_sql(SQL_UNION_CARDINALIDAD) == SQL_UNION_CARDINALIDAD
    assert figures.check_sql(SQL_UNION_GRUPOS) == SQL_UNION_GRUPOS


def test_el_ejecutor_acepta_las_formas_con_union_y_las_audita_antes_de_ejecutar(settings):
    _, runtime, session, conector, ejecutor = _ejecutor(settings)
    original = runtime.audit.event

    def registra(kind, user_id, **data):
        conector.order.append("audit")
        return original(kind, user_id, **data)

    runtime.audit.event = registra
    assert ejecutor(session.servers[0], "BancaPrestamos", SQL_UNION_CARDINALIDAD) == [(4,)]
    assert ejecutor(session.servers[0], "BancaPrestamos", SQL_UNION_GRUPOS) == [("A", 1, 40), ("B", 2, 30)]
    assert conector.order == ["audit", "connect", "query", "audit", "connect", "query"]
    assert [sql for _, sql in conector.queries] == [SQL_UNION_CARDINALIDAD, SQL_UNION_GRUPOS]
    eventos = runtime.audit.recent(kind="figure_query")
    assert sorted(e["sql"] for e in eventos) == sorted([SQL_UNION_CARDINALIDAD, SQL_UNION_GRUPOS])  # `recent` va de lo nuevo a lo viejo
    for conexion in conector.connections:  # mismas garantías que las consultas sin unión
        assert conexion.settings == [SQL_SET] and conexion.rolled_back == 1 and conexion.closed
        assert conexion.timeout == runtime_module.FIGURE_TIMEOUT_S


def test_si_la_auditoria_falla_la_consulta_con_union_no_se_ejecuta(settings):
    """F11 fail-closed también para las uniones: sin registro no hay ni conexión."""
    _, runtime, session, conector, ejecutor = _ejecutor(settings)

    def rota(kind, user_id, **data):
        raise RuntimeError("sin disco")

    runtime.audit.event = rota
    with pytest.raises(RuntimeError):
        ejecutor(session.servers[0], "BancaPrestamos", SQL_UNION_GRUPOS)
    assert conector.connections == [] and conector.queries == []


def test_la_politica_de_servidor_tambien_aplica_a_las_consultas_con_union(settings):
    runtime, session, conector = _con_politica(settings, environment="produccion", figures=None)
    with pytest.raises(PermissionError):
        runtime.figure_executor(session)(session.servers[0], "BancaPrestamos", SQL_UNION_GRUPOS)
    assert conector.connections == [] and runtime.audit.recent(kind="figure_query") == []


def test_discover_por_segmento_audita_las_tres_consultas_y_todas_son_de_la_plantilla(settings):
    """De punta a punta: total, cardinalidad con unión y grupos con unión; cada una audita su SQL antes de ejecutarse."""
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    runtime, _ = _sesion(client)
    conector.queries.clear()
    conector.order.clear()
    env = client.post("/discover", json={"question": "cual es el saldo total de la cartera de prestamos por segmento"}).json()
    assert env["flow"] == "ask" and env["figure"]["group_by"] == "Segmento"
    sqls = [sql for _, sql in conector.queries]
    assert len(sqls) == 3 and sqls[1:] == [SQL_UNION_CARDINALIDAD, SQL_UNION_GRUPOS]
    assert all(figures.ALLOWED_SQL.fullmatch(sql) for sql in sqls)
    assert sorted(e["sql"] for e in runtime.audit.recent(kind="figure_query")) == sorted(sqls)
    assert {db for db, _ in conector.queries} == {"BancaPrestamos"}


def test_discover_por_dato_personal_de_la_relacionada_no_ejecuta_union_ni_grupos(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    conector.queries.clear()
    for dato in ("nombres", "dui", "email"):
        env = client.post("/discover", json={"question": f"cuantos prestamos hay por {dato}"}).json()
        assert env["figure"]["groups"] == [] and env["figure"].get("group_by") is None
    assert conector.queries and not any("JOIN" in sql or "GROUP BY" in sql for _, sql in conector.queries)


def test_discover_la_etiqueta_de_un_grupo_pequeno_con_union_no_llega_a_la_respuesta_ni_a_la_auditoria(settings):
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    conector.groups = [("Personal", 900, 60), ("Premium", 500, 40), ("CLIENTE-UNICO-0042", 7, 2)]
    client = _arranca(settings, conector)
    r = client.post("/discover", json={"question": "cual es el saldo total de la cartera de prestamos por segmento"})
    assert "CLIENTE-UNICO-0042" not in r.text
    runtime, _ = _sesion(client)
    assert "CLIENTE-UNICO-0042" not in repr(runtime.audit.recent(kind="figure_query"))


def test_discover_un_analista_no_provoca_sql_sobre_bases_que_no_ve_tampoco_por_union(settings):
    """F14 en la API: el analista solo ve `BancaPrestamos` y `BancaCuentasDebito`."""
    settings.ask_flow = True
    conector = ConnectorConDatos(FIXTURE)
    client = _arranca(settings, conector)
    conector.queries.clear()
    analista = TestClient(client.app)
    assert analista.post("/auth/login", json={"login": "analista", "password": "demo"}).status_code == 200
    r = analista.post("/discover", json={"question": "cuantas tarjetas de credito hay por marca"})
    assert r.status_code == 200 and "BancaTarjetasCredito" not in r.text
    assert not any("BancaTarjetasCredito" in sql for _, sql in conector.queries)
    analista.post("/discover", json={"question": "cual es el saldo total de la cartera de prestamos por segmento"})
    assert conector.queries and all(figures.ALLOWED_SQL.fullmatch(sql) for _, sql in conector.queries)
    assert {db for db, _ in conector.queries} <= {"BancaPrestamos", "BancaCuentasDebito"}
