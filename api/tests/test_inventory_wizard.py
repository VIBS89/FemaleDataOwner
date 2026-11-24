"""Asistente "Conectar base de datos" de Administración: sondear un servidor y conectarlo con las bases elegidas.

`POST /admin/inventory/probe` se conecta con la credencial de la sesión del administrador y lista las bases de usuario
(con acceso o no y cuántas tablas y vistas tienen) sin guardar nada. `POST /admin/inventory/connect` añade o actualiza
un servidor del inventario con esas bases, con la misma auditoría que `PUT /admin/inventory`, y lanza el descubrimiento.
"""

from __future__ import annotations

import json
import os
import re
import time

import pytest
from fastapi.testclient import TestClient

from discovery_data_agent.config import ServerConfig
from discovery_data_agent_api.audit import FileAuditSink
from discovery_data_agent_api.connector import DatabaseProbe, DemoConnector, DemoUser, LoginFailed, SqlConnector
from discovery_data_agent_api.main import create_app
from discovery_data_agent_api.vault import Credential

from test_api import FIXTURE, build, login, make_client, ready, settings  # noqa: F401  (fixtures de la API)

BANCOS = ["BancaCuentasDebito", "BancaLeasing", "BancaPrestamos", "BancaTarjetasCredito", "BancaTokenizacion"]


def events(client, kind: str) -> list[dict]:
    return client.get("/admin/audit", params={"kind": kind, "limit": 500}).json()["items"]


def wait_build(client) -> dict:
    for _ in range(400):
        job = client.get("/admin/catalog/build").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("la construcción no terminó")


class CountingConnector(DemoConnector):
    def __init__(self, fixtures):
        super().__init__(fixtures)
        self.probes = 0

    def probe(self, server, cred):
        self.probes += 1
        return super().probe(server, cred)


class PartialAdmin(DemoConnector):
    """El administrador `demo` entra a una sola base del servidor (permiso por BD, F14)."""

    def _check(self, cred):
        user = super()._check(cred)
        return DemoUser(["BancaPrestamos"], can_build=True) if (cred.login or "").lower() == "demo" else user


# --- sondeo ------------------------------------------------------------------------------------------
def test_sondear_un_servidor_es_solo_para_administradores(ready, settings):
    body = {"host": "otro-sql"}
    assert TestClient(ready.app).post("/admin/inventory/probe", json=body).status_code == 401
    analyst = make_client(settings)
    analyst.app = ready.app
    login(analyst, user="analista")
    assert analyst.post("/admin/inventory/probe", json=body).status_code == 403
    assert analyst.post("/admin/inventory/connect", json={"host": "otro-sql", "alias": "Otro",
                                                          "databases": ["*"]}).status_code == 403
    denied = {r["route"] for r in events(ready, "access_denied")}
    assert {"/admin/inventory/probe", "/admin/inventory/connect"} <= denied
    assert events(ready, "inventory_probe") == []  # quien no puede no llega a conectar


def test_el_sondeo_lista_las_bases_con_sus_conteos_y_no_guarda_nada(ready, settings):
    before_inventory = settings.inventory_path.read_text(encoding="utf-8")
    before_servers = ready.get("/auth/me").json()["servers"]

    r = ready.post("/admin/inventory/probe", json={"host": "otro-sql"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["connected"] is True and data["error"] is None
    assert [d["name"] for d in data["databases"]] == BANCOS
    for d in data["databases"]:
        assert d["accessible"] is True and d["reason"] is None
        assert isinstance(d["tables"], int) and isinstance(d["views"], int) and d["tables"] + d["views"] > 0

    assert settings.inventory_path.read_text(encoding="utf-8") == before_inventory
    assert ready.get("/auth/me").json()["servers"] == before_servers  # ni credencial nueva en la sesión
    assert [s["id"] for s in ready.get("/admin/inventory").json()["servers"]] == ["DEMO_SQL"]
    probe = events(ready, "inventory_probe")
    assert len(probe) == 1 and probe[0]["user_id"] == "demo" and probe[0]["host"] == "otro-sql"
    raw = "".join(p.read_text(encoding="utf-8") for p in settings.audit_dir.glob("*.jsonl"))
    assert "password" not in raw and '"demo"' in raw


def test_el_sondeo_de_un_servidor_del_inventario_usa_su_configuracion(ready):
    r = ready.post("/admin/inventory/probe", json={"server_id": "DEMO_SQL"})
    assert r.status_code == 200 and r.json()["connected"]
    assert [d["name"] for d in r.json()["databases"]] == BANCOS
    assert ready.post("/admin/inventory/probe", json={"server_id": "NO_EXISTE"}).status_code == 404
    assert ready.post("/admin/inventory/probe", json={}).status_code == 400  # ni host ni servidor
    assert ready.post("/admin/inventory/probe", json={"host": "sql01;Trusted_Connection=yes"}).status_code == 422


def test_el_sondeo_se_audita_antes_de_conectar(settings, monkeypatch):
    """Fail-closed (F11): si el sondeo no se puede registrar, la credencial no viaja al servidor."""
    connector = CountingConnector(FIXTURE)
    client = TestClient(create_app(settings, connector), raise_server_exceptions=False)
    login(client, host="demo-sql")
    real = FileAuditSink.event

    def broken(self, kind, *args, **kwargs):
        if kind == "inventory_probe":
            raise OSError("auditoría no disponible")
        return real(self, kind, *args, **kwargs)

    monkeypatch.setattr(FileAuditSink, "event", broken)
    assert client.post("/admin/inventory/probe", json={"host": "otro-sql"}).status_code == 500
    assert connector.probes == 0


def test_las_bases_sin_acceso_se_marcan_y_no_se_cuentan(settings):
    client = TestClient(create_app(settings, PartialAdmin(FIXTURE)))
    login(client, host="demo-sql")
    data = client.post("/admin/inventory/probe", json={"server_id": "DEMO_SQL"}).json()
    by_name = {d["name"]: d for d in data["databases"]}
    assert set(by_name) == set(BANCOS)
    assert by_name["BancaPrestamos"]["accessible"] and by_name["BancaPrestamos"]["tables"] > 0
    for name in set(BANCOS) - {"BancaPrestamos"}:
        assert by_name[name]["accessible"] is False and by_name[name]["reason"]
        assert by_name[name]["tables"] is None and by_name[name]["views"] is None


def test_el_sondeo_excluye_las_bases_de_sistema_y_la_propia(settings, monkeypatch, tmp_path):
    """La BD de trabajo no se cataloga a sí misma (como en el build), se llame `DiscoveryDataAgent` o como diga DISCOVERY_DATA_AGENT_DB."""
    from discovery_data_agent.bootstrap import open_stores

    class WithSystem(DemoConnector):
        def probe(self, server, cred):
            extra = [DatabaseProbe(n, True, 1, 0) for n in ("master", "msdb", "DiscoveryDataAgent", "DiscoveryDataAgent_Piloto")]
            return extra + super().probe(server, cred)

    monkeypatch.setattr("discovery_data_agent_api.main.open_audit", lambda s: FileAuditSink(s.audit_dir))
    monkeypatch.setattr("discovery_data_agent_api.runtime.open_api_stores",
                        lambda s: open_stores(None, data_root=s.data_root, curation_dir=s.curation_dir,
                                              inventory_path=s.inventory_path))
    settings.db = "SERVER=sql-discovery-data-agent;DATABASE=DiscoveryDataAgent_Piloto;Trusted_Connection=yes"
    client = TestClient(create_app(settings, WithSystem(FIXTURE)))
    login(client, host="demo-sql")
    names = [d["name"] for d in client.post("/admin/inventory/probe", json={"host": "otro-sql"}).json()["databases"]]
    assert names == BANCOS


def test_en_produccion_no_se_acepta_un_certificado_sin_validar(ready, settings):
    settings.environment = "prod"  # se lee en cada petición
    r = ready.post("/admin/inventory/probe", json={"host": "otro-sql", "trust_server_certificate": True})
    assert r.status_code == 400 and "certificado" in r.json()["detail"]
    r = ready.post("/admin/inventory/connect", json={"host": "otro-sql", "alias": "Otro", "databases": ["*"],
                                                     "trust_server_certificate": True})
    assert r.status_code == 400
    assert events(ready, "inventory_probe") == []
    assert [s["id"] for s in ready.get("/admin/inventory").json()["servers"]] == ["DEMO_SQL"]


def test_un_error_de_conexion_no_filtra_host_ni_credenciales(settings):
    class Broken(DemoConnector):
        def probe(self, server, cred):
            if server.host == "caido-sql":
                raise LoginFailed("No se pudo conectar al servidor", credentials=False)
            raise RuntimeError(f"[ODBC Driver 18] TCP Provider: {server.host}.corp.local UID={cred.login} PWD={cred.password}")

    client = TestClient(create_app(settings, Broken(FIXTURE)))
    login(client, host="demo-sql")
    r = client.post("/admin/inventory/probe", json={"host": "caido-sql"})
    assert r.status_code == 200 and r.json() == {"connected": False, "error": "No se pudo conectar al servidor",
                                                  "databases": []}
    r = client.post("/admin/inventory/probe", json={"host": "raro-sql"})
    assert r.status_code == 200 and r.json()["connected"] is False
    assert "raro-sql" not in r.text and "ODBC" not in r.text and "PWD" not in r.text and "demo" not in r.text


def test_el_conector_sql_traduce_los_errores_del_driver(monkeypatch):
    import pyodbc

    def refuse(*args, **kwargs):
        raise pyodbc.OperationalError("08001", "[Microsoft][ODBC Driver 18] TCP Provider: sqlprd01.corp.local no responde")

    monkeypatch.setattr("discovery_data_agent_api.connector.best_driver", lambda: "ODBC Driver 18 for SQL Server")
    monkeypatch.setattr(pyodbc, "connect", refuse)
    server = ServerConfig(id="S1", host="sqlprd01.corp.local", alias="SQL", environment="produccion")
    with pytest.raises(LoginFailed) as caught:
        SqlConnector().probe(server, Credential("S1", "ana", "secreta"))
    assert str(caught.value) == "No se pudo conectar al servidor" and caught.value.credentials is False


class _Cursor:
    def __init__(self, db: str, fake: "_Server"):
        self.db, self.fake, self.rows = db, fake, []

    def execute(self, sql, *params):
        self.fake.sql.append((self.db, sql))
        if "sys.databases" in sql:
            self.rows = self.fake.databases
        elif "sys.objects" in sql:
            if self.db in self.fake.failing:
                raise RuntimeError("sin permiso")
            self.rows = [self.fake.counts[self.db]]
        return self

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Server:
    def __init__(self):
        self.sql: list[tuple[str, str]] = []
        self.databases = [("Ventas", "ONLINE", 1), ("Riesgo", "ONLINE", 0), ("Archivo", "OFFLINE", None),
                          ("Lenta", "ONLINE", 1), ("Rara;UID=sa", "ONLINE", 1)]
        self.counts = {"Ventas": (12, 3)}
        self.failing = {"Lenta"}
        self.opened: list[str] = []

    def connect(self, server, cred, database="master"):
        self.opened.append(database)
        fake = self

        class Conn:
            def cursor(self):
                return _Cursor(database, fake)

            def close(self):
                pass

        return Conn()


def test_el_conector_sql_cuenta_solo_en_las_bases_con_acceso(monkeypatch):
    fake = _Server()
    connector = SqlConnector()
    monkeypatch.setattr(connector, "connect", fake.connect)
    server = ServerConfig(id="S1", host="sql01", alias="SQL", environment="desarrollo")
    found = {d.name: d for d in connector.probe(server, Credential("S1", "ana", "x"))}
    assert found["Ventas"] == DatabaseProbe("Ventas", True, 12, 3)
    assert found["Riesgo"].accessible is False and found["Riesgo"].tables is None and found["Riesgo"].reason
    assert found["Archivo"].accessible is False and "línea" in found["Archivo"].reason
    assert found["Lenta"].accessible is True and found["Lenta"].tables is None  # el conteo falló: sigue con las demás
    assert found["Rara;UID=sa"].accessible is False  # un nombre que no entra en una cadena ODBC no se abre
    assert sorted(set(fake.opened)) == ["Lenta", "Ventas", "master"]  # nunca abre una base sin acceso


# --- conectar y descubrir ---------------------------------------------------------------------------
def test_conectar_un_servidor_nuevo_lo_agrega_y_descubre_solo_las_bases_elegidas(ready, settings):
    r = ready.post("/admin/inventory/connect", json={"host": "otro-sql", "alias": "SQL Otro", "environment": "qa",
                                                     "databases": ["BancaLeasing"]})
    assert r.status_code == 202, r.text
    server_id = r.json()["server"]["id"]
    assert server_id == "OTRO_SQL" and r.json()["job"]["status"] in ("running", "ok")
    assert wait_build(ready)["status"] == "ok"

    inventory = {s["id"]: s for s in ready.get("/admin/inventory").json()["servers"]}
    assert set(inventory) == {"DEMO_SQL", "OTRO_SQL"}  # el resto del inventario queda como estaba
    assert inventory["OTRO_SQL"]["databases"] == ["BancaLeasing"] and inventory["OTRO_SQL"]["connected"]
    assert inventory["OTRO_SQL"]["environment"] == "qa" and inventory["OTRO_SQL"]["is_reference"] is True
    assert inventory["DEMO_SQL"]["databases"] == ["*"]
    groups = [g for g in ready.get("/catalog/databases").json() if g["server"] == "OTRO_SQL"]
    assert [g["database"] for g in groups] == ["BancaLeasing"] and groups[0]["server_alias"] == "SQL Otro"

    updated = events(ready, "inventory_updated")[0]  # lo más reciente primero
    assert updated["via"] == "connect" and updated["user_id"] == "demo"
    assert {s["host"] for s in updated["servers"]} == {"demo-sql", "otro-sql"}
    assert {s["host"] for s in updated["previous"]} == {"demo-sql"}
    assert "password" not in json.dumps(updated)


def test_conectar_un_servidor_existente_le_cambia_las_bases(ready):
    r = ready.post("/admin/inventory/connect", json={"server_id": "DEMO_SQL",
                                                     "databases": ["BancaPrestamos", "BancaLeasing"]})
    assert r.status_code == 202, r.text
    assert wait_build(ready)["status"] == "ok"
    inventory = ready.get("/admin/inventory").json()["servers"]
    assert len(inventory) == 1 and inventory[0]["databases"] == ["BancaPrestamos", "BancaLeasing"]
    assert inventory[0]["alias"] == "SQL demo" and inventory[0]["host"] == "demo-sql"


def test_conectar_valida_lo_que_recibe(ready):
    def connect(**body):
        return ready.post("/admin/inventory/connect", json={"databases": ["*"], **body})

    assert connect(host="otro-sql").status_code == 400  # sin nombre visible el host acabaría a la vista
    assert connect(server_id="NO_EXISTE").status_code == 404
    assert connect().status_code == 400
    assert connect(host="DEMO-SQL", alias="Repetido").status_code == 409  # ya está en el inventario
    assert connect(host="otro-sql", alias="x", databases=["master;UID=sa"]).status_code == 422
    assert connect(host="otro-sql", alias="x", databases=[]).status_code == 422
    assert [s["id"] for s in ready.get("/admin/inventory").json()["servers"]] == ["DEMO_SQL"]


def test_si_la_credencial_no_entra_no_se_guarda_el_servidor(settings):
    class Refuses(DemoConnector):
        def identify(self, server, cred):
            if server.host == "caido-sql":
                raise LoginFailed("No se pudo conectar al servidor", credentials=False)
            return super().identify(server, cred)

    client = TestClient(create_app(settings, Refuses(FIXTURE)))
    login(client, host="demo-sql")
    before = settings.inventory_path.read_text(encoding="utf-8")
    r = client.post("/admin/inventory/connect", json={"host": "caido-sql", "alias": "Caído", "databases": ["*"]})
    assert r.status_code == 400 and "No se pudo conectar al servidor" in r.json()["detail"]
    assert "caido-sql" not in r.json()["detail"]
    assert settings.inventory_path.read_text(encoding="utf-8") == before
    assert client.get("/admin/catalog/build").json()["status"] != "running"
    kinds = [e["type"] for e in client.get("/admin/audit", params={"limit": 20}).json()["items"]]
    assert kinds.index("inventory_updated_failed") < kinds.index("inventory_updated")  # anunciado y no aplicado


def test_conectar_sin_auditoria_no_cambia_el_inventario(ready, settings, monkeypatch):
    quiet = TestClient(ready.app, raise_server_exceptions=False, cookies=ready.cookies)
    before = settings.inventory_path.read_text(encoding="utf-8")
    real = FileAuditSink.event

    def broken(self, kind, *args, **kwargs):
        if kind == "inventory_updated":
            raise OSError("auditoría no disponible")
        return real(self, kind, *args, **kwargs)

    monkeypatch.setattr(FileAuditSink, "event", broken)
    r = quiet.post("/admin/inventory/connect", json={"host": "otro-sql", "alias": "Otro", "databases": ["*"]})
    assert r.status_code == 500
    assert settings.inventory_path.read_text(encoding="utf-8") == before


def test_conectar_con_un_descubrimiento_en_curso_espera(ready):
    ready.app.state.runtime.job.status = "running"
    r = ready.post("/admin/inventory/connect", json={"host": "otro-sql", "alias": "Otro", "databases": ["*"]})
    assert r.status_code == 409
    ready.app.state.runtime.job.status = "ok"


def test_el_put_del_inventario_sigue_auditando_antes_y_despues(ready):
    servers = ready.get("/admin/inventory").json()["servers"]
    servers.append({"id": "S2", "host": "s2-sql", "alias": "S2", "databases": ["*"]})
    body = {"servers": [{k: v for k, v in s.items() if k != "connected"} for s in servers]}
    r = ready.put("/admin/inventory", json=body)
    assert r.status_code == 200 and r.json()["connections"] == {"S2": "conectado"}
    updated = events(ready, "inventory_updated")[0]
    assert {s["host"] for s in updated["previous"]} == {"demo-sql"}
    assert {s["host"] for s in updated["servers"]} == {"demo-sql", "s2-sql"}


# --- SQL Server real --------------------------------------------------------------------------------
@pytest.mark.sqlserver
def test_el_sondeo_real_ve_la_bd_de_pruebas_con_sus_tablas(discovery_data_agent_db):
    """Con `DISCOVERY_DATA_AGENT_TEST_DB`: la BD desechable (migrada, con tablas) aparece con acceso y con su conteo."""
    server_string = os.environ["DISCOVERY_DATA_AGENT_TEST_DB"]
    host = re.search(r"SERVER=([^;]+)", server_string, re.I).group(1)
    trust = bool(re.search(r"TrustServerCertificate=yes", server_string, re.I))
    login_ = re.search(r"UID=([^;]+)", server_string, re.I)
    password = re.search(r"PWD=([^;]+)", server_string, re.I)
    server = ServerConfig(id="TEST", host=host, alias="Pruebas", environment="desarrollo",
                          trust_server_certificate=trust)
    cred = Credential("TEST", login_.group(1) if login_ else None, password.group(1) if password else None)
    name = re.search(r"DATABASE=([^;]+)", discovery_data_agent_db, re.I).group(1)
    found = {d.name: d for d in SqlConnector().probe(server, cred)}
    assert "master" not in found and "tempdb" not in found
    assert found[name].accessible is True and found[name].tables and found[name].tables > 5


# --- revisión de seguridad ---------------------------------------------------------------------------
def test_conectar_no_cataloga_bases_de_sistema_ni_la_propia_aunque_lleguen_a_mano(ready):
    for name in ("master", "MSDB", "DiscoveryDataAgent"):
        r = ready.post("/admin/inventory/connect", json={"server_id": "DEMO_SQL", "databases": ["BancaLeasing", name]})
        assert r.status_code == 400 and name in r.json()["detail"], r.text
    assert ready.get("/admin/inventory").json()["servers"][0]["databases"] == ["*"]
    assert not [e for e in events(ready, "inventory_updated") if e.get("via") == "connect"]  # ni se intentó


def test_conectar_comparte_el_limite_de_ritmo_del_sondeo(ready):
    """Cada intento envía la credencial del administrador a un servidor: el tope es el mismo que el del sondeo."""
    codes = [ready.post("/admin/inventory/connect", json={"host": f"otro-{i}", "databases": ["*"]}).status_code
             for i in range(31)]  # sin nombre visible: 400 antes de conectar, pero ya cuenta como intento
    assert codes[:30] == [400] * 30 and codes[30] == 429
    assert ready.post("/admin/inventory/probe", json={"host": "otro-sql"}).status_code == 429


def test_si_no_se_puede_guardar_la_sesion_no_conserva_la_credencial_del_servidor(ready, monkeypatch):
    from discovery_data_agent_api import runtime as runtime_module

    def boom(self, servers, *, by):
        raise RuntimeError("BD caída")

    monkeypatch.setattr(runtime_module.AgentRuntime, "save_inventory", boom)
    with pytest.raises(RuntimeError):
        ready.post("/admin/inventory/connect", json={"host": "otro-sql", "alias": "SQL Otro", "databases": ["*"]})
    monkeypatch.undo()
    assert ready.get("/auth/me").status_code == 200  # la sesión sigue válida, sin el servidor que no se guardó
    assert [s["id"] for s in ready.get("/admin/inventory").json()["servers"]] == ["DEMO_SQL"]
