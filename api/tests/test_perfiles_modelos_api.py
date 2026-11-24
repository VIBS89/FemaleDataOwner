"""Elección en pantalla del proveedor de IA: GET/PUT /admin/llm (F16, F17, F11)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from discovery_data_agent.llm import factory
from discovery_data_agent.llm.factory import selection_path

from test_api import build, login, make_client, settings  # noqa: F401  (fixtures de la API)

CLAVE_NVIDIA = "nvapi-centinela-NVIDIA-123456"
CLAVE_CLAUDE = "sk-ant-centinela-CLAUDE-654321"

MODELOS = """
data_mode: test
active_profile: nvidia
providers:
  nvidia_nim: {enabled: false, api_key_env: NVIDIA_API_KEY, allowed_data: test}
  anthropic: {enabled: false, api_key_env: ANTHROPIC_API_KEY, allowed_data: test}
profiles:
  nvidia:
    label: NVIDIA NIM
    description: Nemotron
    roles:
      fast: {provider: nvidia_nim, model: nv-fast}
      enrich: {provider: nvidia_nim, model: nv-enrich}
  claude:
    label: Claude
    roles:
      fast: {provider: anthropic, model: cl-fast}
      enrich: {provider: anthropic, model: cl-enrich}
"""

# Datos reales: solo el perfil con Bedrock (allowed_data real) es válido; el de NVIDIA hospedado no.
MODELOS_REALES = """
data_mode: real
active_profile: banco
providers:
  nvidia_nim: {enabled: true, api_key_env: NVIDIA_API_KEY, allowed_data: test}
  bedrock: {enabled: false, region: us-east-1, allowed_data: real}
profiles:
  banco:
    label: Bedrock
    roles:
      fast: {provider: bedrock, model: m-fast}
  externo:
    label: NVIDIA hospedado
    roles:
      fast: {provider: nvidia_nim, model: nv-fast}
"""

SIN_PERFILES = """
data_mode: test
providers:
  nvidia_nim: {allowed_data: test, api_key_env: NVIDIA_API_KEY}
roles:
  fast: {provider: nvidia_nim, model: nv-fast}
"""


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", CLAVE_NVIDIA)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CLAVE_CLAUDE)
    monkeypatch.delenv("DISCOVERY_DATA_AGENT_ENV", raising=False)

    def prohibido(*args, **kwargs):  # validar un perfil no debe construir ni llamar a ningún modelo
        raise AssertionError("se intentó construir un modelo: no debe haber llamadas al proveedor")

    for clave in list(factory.BUILDERS):
        monkeypatch.setitem(factory.BUILDERS, clave, prohibido)


def api(settings, tmp_path, texto: str | None = MODELOS):
    """(admin, ruta del models.yaml) con el catálogo construido; `texto=None` = sin `models_path`."""
    path = tmp_path / "models.yaml"
    if texto is not None:
        path.write_text(texto, encoding="utf-8")
        settings.models_path = path
    client = make_client(settings)
    login(client, host="demo-sql", alias="SQL demo")
    assert build(client)["status"] == "ok"
    return client, path


def consumidor(admin) -> TestClient:
    client = TestClient(admin.app)
    login(client, user="analista")
    return client


def perfil(datos: dict, nombre: str) -> dict:
    return next(p for p in datos["profiles"] if p["id"] == nombre)


def eventos(admin) -> list[dict]:
    return admin.get("/admin/audit", params={"kind": "llm_profile_changed", "limit": 500}).json()["items"]


# --- 6. acceso y contenido de GET ---------------------------------------------------------------------------
def test_get_exige_sesion_y_rol_de_administrador(settings, tmp_path):
    admin, _ = api(settings, tmp_path)
    assert TestClient(admin.app).get("/admin/llm").status_code == 401
    assert TestClient(admin.app).put("/admin/llm", json={"profile": "claude"}).status_code == 401
    analista = consumidor(admin)
    assert analista.get("/admin/llm").status_code == 403
    assert analista.put("/admin/llm", json={"profile": "none"}).status_code == 403
    assert admin.get("/admin/llm").status_code == 200
    assert selection_path(settings.models_path).exists() is False  # el consumidor no cambió nada
    assert eventos(admin) == []


def test_get_lista_los_perfiles_y_nunca_devuelve_una_clave(settings, tmp_path):
    admin, _ = api(settings, tmp_path)
    r = admin.get("/admin/llm")
    assert r.status_code == 200
    datos = r.json()
    assert datos["configured"] is True and datos["selectable"] is True
    assert datos["active"] == "nvidia" and datos["data_mode"] == "test" and datos["none_id"] == "none"
    assert datos["roles"] == {"fast": {"provider": "nvidia_nim", "model": "nv-fast"},
                              "enrich": {"provider": "nvidia_nim", "model": "nv-enrich"}}
    assert {p["id"] for p in datos["profiles"]} == {"nvidia", "claude"}
    assert all(p["usable"] and p["reason"] is None for p in datos["profiles"])
    texto = r.text + json.dumps(admin.put("/admin/llm", json={"profile": "claude"}).json())
    assert CLAVE_NVIDIA not in texto and CLAVE_CLAUDE not in texto


def test_la_clave_no_sale_ni_con_el_perfil_inutilizable_ni_en_el_error(settings, tmp_path, monkeypatch):
    admin, _ = api(settings, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    listado = admin.get("/admin/llm")
    rechazo = admin.put("/admin/llm", json={"profile": "claude"})
    assert rechazo.status_code == 409
    for respuesta in (listado, rechazo):
        assert CLAVE_NVIDIA not in respuesta.text and CLAVE_CLAUDE not in respuesta.text
    auditoria = admin.get("/admin/audit", params={"limit": 500}).text
    assert CLAVE_NVIDIA not in auditoria and CLAVE_CLAUDE not in auditoria


def test_sin_models_path_get_dice_que_no_esta_configurado(settings, tmp_path):
    admin, _ = api(settings, tmp_path, texto=None)
    datos = admin.get("/admin/llm").json()
    assert datos["configured"] is False and datos["selectable"] is False
    assert datos["active"] is None and datos["profiles"] == []
    r = admin.put("/admin/llm", json={"profile": "none"})
    assert r.status_code == 409


def test_un_archivo_sin_perfiles_no_es_elegible(settings, tmp_path):
    admin, path = api(settings, tmp_path, SIN_PERFILES)
    datos = admin.get("/admin/llm").json()
    assert datos["configured"] is True and datos["selectable"] is False
    assert datos["profiles"] == [] and datos["active"] is None
    assert datos["roles"]["fast"]["model"] == "nv-fast"
    assert admin.put("/admin/llm", json={"profile": "none"}).status_code == 409
    assert not selection_path(path).exists()


# --- 7. PUT ----------------------------------------------------------------------------------------------------
def test_put_a_un_perfil_usable_lo_activa_lo_guarda_lo_audita_y_recarga_el_servicio(settings, tmp_path):
    admin, path = api(settings, tmp_path)
    runtime = admin.app.state.runtime
    version = runtime.version
    assert runtime.service.deps.guide is not None  # nvidia declara `fast`
    r = admin.put("/admin/llm", json={"profile": "claude"})
    assert r.status_code == 200, r.text
    assert r.json()["active"] == "claude" and r.json()["roles"]["fast"]["model"] == "cl-fast"
    assert admin.get("/admin/llm").json()["active"] == "claude"
    assert selection_path(path).read_text(encoding="utf-8").strip() == "claude"
    assert runtime.version > version and runtime.service is not None
    assert runtime.service.deps.guide is not None
    [evento] = eventos(admin)
    assert evento["previous"] == "nvidia" and evento["profile"] == "claude" and evento["user_id"] == "demo"
    # el siguiente cambio parte del activo anterior
    assert admin.put("/admin/llm", json={"profile": "nvidia"}).status_code == 200
    # la auditoría lista lo más reciente primero
    assert [(e["previous"], e["profile"]) for e in eventos(admin)] == [("claude", "nvidia"), ("nvidia", "claude")]


def test_put_none_siempre_se_acepta_y_deja_el_servicio_sin_narrador(settings, tmp_path, monkeypatch):
    admin, path = api(settings, tmp_path)
    for variable in ("NVIDIA_API_KEY", "ANTHROPIC_API_KEY"):  # ni siquiera hacen falta claves
        monkeypatch.delenv(variable)
    runtime = admin.app.state.runtime
    r = admin.put("/admin/llm", json={"profile": "none"})
    assert r.status_code == 200, r.text
    assert r.json()["active"] == "none" and r.json()["roles"] == {}
    assert runtime.service.deps.guide is None  # el narrador de plantilla determinista sigue ahí
    assert selection_path(path).read_text(encoding="utf-8").strip() == "none"
    assert [(e["previous"], e["profile"]) for e in eventos(admin)] == [("nvidia", "none")]
    # sigue respondiendo, en modo determinista
    analista = consumidor(admin)
    assert analista.post("/discover", json={"question": "¿Dónde está el saldo del préstamo?"}).status_code == 200


def test_volver_de_none_a_un_perfil_devuelve_el_narrador(settings, tmp_path):
    admin, _ = api(settings, tmp_path)
    runtime = admin.app.state.runtime
    assert admin.put("/admin/llm", json={"profile": "none"}).status_code == 200
    assert runtime.service.deps.guide is None
    assert admin.put("/admin/llm", json={"profile": "claude"}).status_code == 200
    assert runtime.service.deps.guide is not None


def test_la_seleccion_sobrevive_a_un_reinicio(settings, tmp_path):
    admin, _ = api(settings, tmp_path)
    assert admin.put("/admin/llm", json={"profile": "claude"}).status_code == 200
    reiniciada = make_client(settings)  # mismo models.yaml, mismo `.active`
    login(reiniciada, host="demo-sql")
    assert reiniciada.get("/admin/llm").json()["active"] == "claude"


def test_put_a_un_perfil_inexistente_es_409_y_no_cambia_nada(settings, tmp_path):
    admin, path = api(settings, tmp_path)
    runtime = admin.app.state.runtime
    version = runtime.version
    r = admin.put("/admin/llm", json={"profile": "inventado"})
    assert r.status_code == 409 and "no existe" in r.json()["detail"]
    assert not selection_path(path).exists()
    assert runtime.version == version and admin.get("/admin/llm").json()["active"] == "nvidia"


@pytest.mark.parametrize("cuerpo", [
    {"profile": ""}, {"profile": "../etc/passwd"}, {"profile": "a b"}, {"profile": "nv;DROP"}, {"profile": "ñandú"},
    {"profile": "x" * 41}, {"profile": "uno\ndos"}, {}, {"profile": None}, {"profile": 7},
])
def test_put_con_cuerpo_invalido_es_422_y_no_escribe(settings, tmp_path, cuerpo):
    admin, path = api(settings, tmp_path)
    assert admin.put("/admin/llm", json=cuerpo).status_code == 422
    assert not selection_path(path).exists()
    assert eventos(admin) == []


def test_si_falta_la_clave_del_proveedor_el_perfil_no_es_usable_y_el_put_da_409(settings, tmp_path, monkeypatch):
    admin, path = api(settings, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    runtime = admin.app.state.runtime
    version = runtime.version
    claude = perfil(admin.get("/admin/llm").json(), "claude")
    assert claude["usable"] is False
    assert "ANTHROPIC_API_KEY" in claude["reason"] and CLAVE_CLAUDE not in claude["reason"]
    assert perfil(admin.get("/admin/llm").json(), "nvidia")["usable"] is True  # el otro perfil no se ve afectado
    r = admin.put("/admin/llm", json={"profile": "claude"})
    assert r.status_code == 409
    assert "ANTHROPIC_API_KEY" in r.json()["detail"] and CLAVE_CLAUDE not in r.text
    assert not selection_path(path).exists()
    assert runtime.version == version and admin.get("/admin/llm").json()["active"] == "nvidia"


def test_un_cambio_rechazado_deja_constancia_de_que_no_se_aplico(settings, tmp_path, monkeypatch):
    """F11: el intento se audita antes de aplicar y, si falla, queda `llm_profile_changed_failed`."""
    admin, _ = api(settings, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert admin.put("/admin/llm", json={"profile": "claude"}).status_code == 409
    fallidos = admin.get("/admin/audit", params={"kind": "llm_profile_changed_failed"}).json()["items"]
    assert len(fallidos) == 1 and fallidos[0]["profile"] == "claude" and fallidos[0]["previous"] == "nvidia"


def test_sin_auditoria_no_se_cambia_el_proveedor(settings, tmp_path, monkeypatch):
    """F11 fail-closed: si el registro falla, el cambio de proveedor no se aplica."""
    from discovery_data_agent_api.audit import FileAuditSink

    admin, path = api(settings, tmp_path)
    cliente = TestClient(admin.app, raise_server_exceptions=False)
    cliente.cookies.update(admin.cookies)

    def roto(self, row, when=None):
        raise OSError("disco de auditoría lleno")

    monkeypatch.setattr(FileAuditSink, "append", roto)
    assert cliente.put("/admin/llm", json={"profile": "claude"}).status_code == 500
    monkeypatch.undo()
    assert not selection_path(path).exists()


# --- 4. residencia por la API ----------------------------------------------------------------------------------
def test_con_datos_reales_el_perfil_de_un_tercero_no_es_usable_y_el_put_no_cambia_nada(settings, tmp_path):
    admin, path = api(settings, tmp_path, MODELOS_REALES)
    runtime = admin.app.state.runtime
    datos = admin.get("/admin/llm").json()
    assert datos["data_mode"] == "real" and datos["active"] == "banco"
    assert perfil(datos, "banco")["usable"] is True
    externo = perfil(datos, "externo")
    assert externo["usable"] is False and externo["reason"]
    servicio, version = runtime.service, runtime.version
    r = admin.put("/admin/llm", json={"profile": "externo"})
    assert r.status_code == 409 and r.json()["detail"]
    assert not selection_path(path).exists()
    assert runtime.service is servicio and runtime.version == version
    assert admin.get("/admin/llm").json()["active"] == "banco"
    assert CLAVE_NVIDIA not in r.text


def test_con_datos_reales_el_motivo_del_rechazo_nombra_la_residencia(settings, tmp_path):
    """FALLA HOY (bug de produccion): `AgentRuntime._profile_problem` solo captura `GatewayConfigError`, pero
    `ResidencyError` hereda de `RuntimeError`, no de aquel. El administrador ve «La configuración del perfil no es
    válida (ResidencyError)» en vez del motivo del gateway (data_mode=real ... allowed_data=test)."""
    admin, _ = api(settings, tmp_path, MODELOS_REALES)
    motivo = perfil(admin.get("/admin/llm").json(), "externo")["reason"]
    assert "data_mode=real" in motivo and "allowed_data=test" in motivo, motivo
    detalle = admin.put("/admin/llm", json={"profile": "externo"}).json()["detail"]
    assert "data_mode=real" in detalle, detalle


def test_con_datos_reales_none_y_el_perfil_valido_se_aceptan(settings, tmp_path):
    admin, path = api(settings, tmp_path, MODELOS_REALES)
    assert admin.put("/admin/llm", json={"profile": "none"}).status_code == 200
    assert admin.put("/admin/llm", json={"profile": "banco"}).status_code == 200
    assert selection_path(path).read_text(encoding="utf-8").strip() == "banco"
