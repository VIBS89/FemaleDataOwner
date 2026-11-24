"""AskFlow (F6–F10): la pregunta de cifras se responde con el dato, calculado con los permisos del usuario."""

import datetime as dt
import decimal

import pytest

from converdata.ask.engine import AskEngine, fill_answer, format_value
from converdata.ask.ports import QueryRejected, QueryResult, SqlPlan
from converdata.ask.validator import ValidationError, validate
from converdata.config import Features, Settings
from converdata.models.discovery import Discovery

Q = "¿cuántos clientes completaron el onboarding?"
COUNT_SQL = ("SELECT COUNT(DISTINCT u.UserId) AS total_clientes FROM [VBank_ING].[dbo].[Users] u "
             "WHERE u.OnboardingStatus = N'COMPLETO'")


class FakePlanner:
    def __init__(self, *plans: SqlPlan):
        self.plans, self.calls = list(plans), []

    def plan(self, question, schema, feedback):
        self.calls.append((question, schema, list(feedback)))
        return self.plans[min(len(self.calls), len(self.plans)) - 1]


class FakeExecutor:
    """Simula SQL Server: valores de las columnas categóricas y el resultado de la consulta final."""

    def __init__(self, result=None, fail_first=None):
        self.result = result or QueryResult(["total_clientes"], [[1790]])
        self.fail_first, self.queries = fail_first, []

    def server_label(self, server):
        return "SQL Producción Canales"

    def run(self, server, database, sql, max_rows):
        self.queries.append(sql)
        if "AS valor, COUNT(*) AS n" in sql:
            return QueryResult(["valor", "n"], [["COMPLETO", 10], ["PENDIENTE", 3]])
        if sql.startswith("SELECT MIN("):
            n = sql.count("MIN(")
            return QueryResult([f"c{i}" for i in range(2 * n)], [[dt.datetime(2026, 1, 1), dt.datetime(2026, 6, 30)] * n])
        if self.fail_first is not None:
            error, self.fail_first = self.fail_first, None
            raise error
        return self.result


def plan(sql=COUNT_SQL, template="Actualmente se tienen {total_clientes} clientes con el onboarding completo."):
    return SqlPlan(database="VBank_ING", sql=sql, answer_template=template,
                   explanation="Conté los clientes distintos con el onboarding completo.",
                   filters=["Solo onboarding completo"])


def ask_service(service, planner):
    deps = service.deps
    deps.settings = Settings(features=Features(ask_flow=True))
    deps.ask = AskEngine(planner, deps.catalog, max_rows=100)
    service.rebuild()
    return service


# --- F7: validador -------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "DELETE FROM [VBank_ING].[dbo].[Users]",
    "SELECT 1 FROM [VBank_ING].[dbo].[Users]; DROP TABLE [VBank_ING].[dbo].[Users]",
    "SELECT UserId INTO t FROM [VBank_ING].[dbo].[Users]",
    "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
    "EXEC xp_cmdshell 'dir'",
    "WAITFOR DELAY '00:01'",
    "SELECT UserId FROM [VBank_ING].[dbo].[NoExiste]",
])
def test_el_validador_rechaza_lo_que_no_es_una_lectura_segura(service, analyst, sql):
    with pytest.raises(ValidationError):
        validate(sql, "VBank_ING", service.deps.catalog, analyst.visible_ids, 100)


def test_el_validador_rechaza_tablas_que_el_usuario_no_ve(service, rrhh_user):
    with pytest.raises(ValidationError, match="no tienes acceso"):
        validate(COUNT_SQL, "VBank_ING", service.deps.catalog, rrhh_user.visible_ids, 100)


def test_el_validador_acepta_cte_e_inyecta_top(service, analyst):
    sql = "WITH c AS (SELECT UserId FROM [VBank_ING].[dbo].[Users]) SELECT UserId FROM c"
    checked = validate(sql, "VBank_ING", service.deps.catalog, analyst.visible_ids, 100)
    assert "TOP 101" in checked.sql and checked.tables == ["VBank_ING.dbo.Users"]


def test_un_texto_con_palabras_reservadas_no_dispara_la_lista_negra(service, analyst):
    sql = "SELECT COUNT(*) AS n FROM [VBank_ING].[dbo].[Users] WHERE OnboardingStatus = N'delete'"
    assert validate(sql, "VBank_ING", service.deps.catalog, analyst.visible_ids, 100)


# --- F10: redacción ------------------------------------------------------------------------
def test_la_frase_usa_solo_las_cifras_del_resultado():
    result = QueryResult(["total_clientes"], [[1790]])
    text = fill_answer("Actualmente se tienen {total_clientes} clientes con préstamos activos.", result, Q)
    assert text == "Actualmente se tienen 1,790 clientes con préstamos activos."


def test_un_numero_inventado_por_el_modelo_invalida_la_frase():
    result = QueryResult(["total_clientes"], [[1790]])
    text = fill_answer("Se tienen 2000 clientes, exactamente {total_clientes}.", result, Q)
    assert "2000" not in text and "1,790" in text


def test_varias_filas_se_presentan_como_listado():
    result = QueryResult(["departamento", "clientes"], [["San Salvador", 10], ["La Libertad", 7]])
    assert fill_answer("Estos son los {filas} departamentos con más clientes:", result, Q) == \
        "Estos son los 2 departamentos con más clientes:"
    assert fill_answer("", QueryResult(["x"], []), Q) == "No encontré registros que cumplan esa condición."


def test_formato_de_cifras_en_espanol():
    assert format_value(decimal.Decimal("1234567.5")) == "1,234,567.50"
    assert format_value(12) == "12" and format_value(dt.date(2026, 11, 23)) == "23/11/2026"


# --- flujo completo ------------------------------------------------------------------------
def test_pregunta_de_cifras_devuelve_el_dato_y_su_evidencia(service, analyst):
    planner = FakePlanner(plan())
    executor = FakeExecutor()
    env = ask_service(service, planner).run(Q, analyst, executor=executor)
    assert env.flow == "ask" and env.status == "ok"
    assert env.answer_text == "Actualmente se tienen 1,790 clientes con el onboarding completo."
    assert env.data.rows == [[1790]] and env.data.tables == ["VBank_ING.dbo.Users"]
    assert env.data.server == "SQL Producción Canales" and "TOP 101" in env.data.sql
    assert env.data.filters == ["Solo onboarding completo"]
    # El planner ve los valores de las columnas categóricas, pero nunca los de columnas personales.
    schema = planner.calls[0][1]
    assert "valores: COMPLETO, PENDIENTE" in schema
    assert not any("[Email]" in q for q in executor.queries)


def test_la_auditoria_no_guarda_los_valores(service, analyst):
    env = ask_service(service, FakePlanner(plan())).run(Q, analyst, executor=FakeExecutor())
    record = service.deps.audit.records[-1]
    assert record.envelope.data.rows == [] and record.envelope.data.sql
    assert env.data.rows == [[1790]]


def test_un_error_de_sql_server_vuelve_al_planner(service, analyst):
    planner = FakePlanner(plan(), plan())
    executor = FakeExecutor(fail_first=QueryRejected("Invalid column name 'Foo'."))
    env = ask_service(service, planner).run(Q, analyst, executor=executor)
    assert env.flow == "ask" and len(planner.calls) == 2
    assert "Invalid column name" in planner.calls[1][2][0]


def test_sin_permiso_se_responde_como_descubrimiento(service, analyst):
    executor = FakeExecutor(fail_first=QueryRejected("No tienes permiso para leer esa información.", retry=False))
    env = ask_service(service, FakePlanner(plan())).run(Q, analyst, executor=executor)
    assert env.flow == "discover" and env.data is None
    assert "No tienes permiso para leer esa información." in env.assumptions


def test_sin_ejecutor_sigue_siendo_descubrimiento(service, analyst):
    env = ask_service(service, FakePlanner(plan())).run(Q, analyst)
    assert env.flow == "discover" and "no está habilitada" in env.assumptions[0]


def test_un_listado_usa_la_frase_de_presentacion():
    result = QueryResult(["estado", "total"], [["Vigente", 1796], ["Cancelado", 793]])
    text = fill_answer("Hay {total} préstamos en estado {estado}.", result, Q, "Estos son los {filas} estados:")
    assert text == "Estos son los 2 estados:"


def test_sin_candidato_recomendado_calcula_en_la_base_mejor_puntuada(service, analyst):
    """Palabras ajenas al catálogo ("dime", "en los últimos 3 meses") dejan a todos bajo el umbral de recomendación,
    pero la base mejor puntuada basta para calcular el dato."""
    planner = FakePlanner(plan())
    discovery = Discovery()
    engine = AskEngine(planner, service.deps.catalog, max_rows=100)
    outcome = engine.run(Q, discovery, analyst, FakeExecutor(), hints=["VBank_ING.dbo.Users.CreatedAt"])
    assert outcome.ok and outcome.data.tables == ["VBank_ING.dbo.Users"]
    schema = planner.calls[0][1]
    assert schema.startswith("Fecha de hoy:") and "datos de 01/01/2026 00:00 a 30/06/2026 00:00" in schema


class FakeInterpreter:
    def __init__(self, interpretation=None, error=None):
        self.interpretation, self.error, self.calls = interpretation, error, []

    def interpret(self, question, history, overview, today):
        self.calls.append((question, list(history), overview, today))
        if self.error:
            raise self.error
        return self.interpretation


def test_el_interprete_reconoce_un_pedido_de_datos_sin_palabras_clave(service, analyst):
    """"Dame…" no está en las reglas de `data_query`: lo decide el LLM y elige las tablas, con solo metadatos."""
    from converdata.ask.ports import QuestionInterpretation

    interp = FakeInterpreter(QuestionInterpretation(
        kind="dato", refined_question="Número de clientes con el onboarding completo",
        database="VBank_ING", tables=["[VBank_ING].[dbo].[Users]"]))
    planner = FakePlanner(plan())
    svc = ask_service(service, planner)
    svc.deps.ask.interpreter = interp
    env = svc.run("dame los clientes que ya terminaron el onboarding", analyst, executor=FakeExecutor(),
                  history=["¿dónde está el estado del onboarding?"])
    assert env.flow == "ask" and env.data.tables == ["VBank_ING.dbo.Users"]
    question, history, overview, _ = interp.calls[0]
    assert history == ["¿dónde está el estado del onboarding?"]
    assert "VBank_ING.dbo.Users" in overview and "RRHH" not in overview  # solo lo que el usuario puede ver
    assert "Interpretación: Número de clientes con el onboarding completo" in planner.calls[0][0]


def test_si_el_interprete_falla_se_usan_las_reglas(service, analyst):
    svc = ask_service(service, FakePlanner(plan()))
    svc.deps.ask.interpreter = FakeInterpreter(error=TimeoutError())
    env = svc.run(Q, analyst, executor=FakeExecutor())
    assert env.flow == "ask"
    assert any(s.error and "interprete:fallback" in s.error for s in service.deps.audit.records[-1].steps)
