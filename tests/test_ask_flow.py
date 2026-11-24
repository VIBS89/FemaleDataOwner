"""AskFlow (F6–F10): la pregunta de cifras se responde con el dato, calculado con los permisos del usuario."""

import datetime as dt
import decimal

import pytest

from discovery_data_agent.ask.engine import AskEngine, fill_answer, format_value
from discovery_data_agent.ask.ports import QueryRejected, QueryResult, SqlPlan
from discovery_data_agent.ask.validator import ValidationError, validate
from discovery_data_agent.config import Features, Settings
from discovery_data_agent.models.discovery import Discovery

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

    def run(self, server, database, sql, max_rows, probe=False):
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
    deps.settings = Settings(features=Features(ask_llm_sql=True))
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
    env = ask_service(service, planner).run(Q, analyst, sql_executor=executor)
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
    env = ask_service(service, FakePlanner(plan())).run(Q, analyst, sql_executor=FakeExecutor())
    record = service.deps.audit.records[-1]
    assert record.envelope.data.rows == [] and record.envelope.data.sql
    assert env.data.rows == [[1790]]


def test_un_error_de_sql_server_vuelve_al_planner(service, analyst):
    planner = FakePlanner(plan(), plan())
    executor = FakeExecutor(fail_first=QueryRejected("Invalid column name 'Foo'."))
    env = ask_service(service, planner).run(Q, analyst, sql_executor=executor)
    assert env.flow == "ask" and len(planner.calls) == 2
    assert "Invalid column name" in planner.calls[1][2][0]


def test_sin_permiso_se_responde_como_descubrimiento(service, analyst):
    executor = FakeExecutor(fail_first=QueryRejected("No tienes permiso para leer esa información.", retry=False))
    env = ask_service(service, FakePlanner(plan())).run(Q, analyst, sql_executor=executor)
    assert env.flow == "discover" and env.data is None
    assert "No tienes permiso para leer esa información." in env.assumptions


def test_sin_ejecutor_sigue_siendo_descubrimiento(service, analyst):
    env = ask_service(service, FakePlanner(plan())).run(Q, analyst)
    assert env.flow == "discover" and env.data is None and "Todavía no calculo cifras" in env.assumptions[0]


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
    from discovery_data_agent.ask.ports import QuestionInterpretation

    interp = FakeInterpreter(QuestionInterpretation(
        kind="dato", refined_question="Número de clientes con el onboarding completo",
        database="VBank_ING", tables=["[VBank_ING].[dbo].[Users]"]))
    planner = FakePlanner(plan())
    svc = ask_service(service, planner)
    svc.deps.ask.interpreter = interp
    env = svc.run("dame los clientes que ya terminaron el onboarding", analyst, sql_executor=FakeExecutor(),
                  history=["¿dónde está el estado del onboarding?"])
    assert env.flow == "ask" and env.data.tables == ["VBank_ING.dbo.Users"]
    question, history, overview, _ = interp.calls[0]
    assert history == ["¿dónde está el estado del onboarding?"]
    assert "VBank_ING.dbo.Users" in overview and "RRHH" not in overview  # solo lo que el usuario puede ver
    assert "Interpretación: Número de clientes con el onboarding completo" in planner.calls[0][0]


def test_si_el_interprete_falla_se_usan_las_reglas(service, analyst):
    svc = ask_service(service, FakePlanner(plan()))
    svc.deps.ask.interpreter = FakeInterpreter(error=TimeoutError())
    env = svc.run(Q, analyst, sql_executor=FakeExecutor())
    assert env.flow == "ask"
    assert any(s.error and "interprete:fallback" in s.error for s in service.deps.audit.records[-1].steps)


# --- convivencia con las cifras de plantilla (decisión 17): con la fase 1b activa responde el LLM y la plantilla
#     queda de respaldo; sin ella, todo sigue como en main ----------------------------------------------------------
class SchemaPlanner:
    """Planner doble que cuenta sobre la primera tabla del esquema que recibe (sirve con cualquier catálogo)."""

    def __init__(self):
        self.calls = []

    def plan(self, question, schema, feedback):
        import re as _re

        self.calls.append(question)
        db, sch, table = _re.search(r"^\[([^\]]+)\]\.\[([^\]]+)\]\.\[([^\]]+)\]", schema, _re.M).groups()
        return SqlPlan(database=db, sql=f"SELECT COUNT(*) AS total FROM [{db}].[{sch}].[{table}]",
                       answer_template="Se registraron {total} clientes.", explanation="Conté los registros.")


def coexist_service(planner):
    from discovery_data_agent.bootstrap import build_service
    from pathlib import Path

    svc = build_service(Path(__file__).parent / "fixtures" / "bancos")
    svc.deps.settings = Settings(features=Features(ask_flow=True, ask_llm_sql=True))
    svc.deps.ask = AskEngine(planner, svc.deps.catalog, max_rows=100)
    svc.rebuild()
    return svc


def test_con_la_fase_1b_activa_responde_primero_el_llm():
    from discovery_data_agent.bootstrap import user_with_databases
    from test_cifras_agregadas import Ejecutor

    planner, plantilla = SchemaPlanner(), Ejecutor()
    svc = coexist_service(planner)
    user = user_with_databases(svc, "dev", None)
    env = svc.run("cuantos clientes tienen prestamos?", user, executor=plantilla,
                  sql_executor=FakeExecutor(QueryResult(["total"], [[42]])))
    assert env.flow == "ask" and env.data is not None and env.figure is None
    assert planner.calls and plantilla.calls == []


class FailingPlanner:
    def plan(self, question, schema, feedback):
        raise TimeoutError("sin modelo")


def test_si_la_fase_1b_falla_responde_la_plantilla_sin_avisos_del_llm():
    from discovery_data_agent.bootstrap import user_with_databases
    from test_cifras_agregadas import Ejecutor

    svc = coexist_service(FailingPlanner())
    user = user_with_databases(svc, "dev", None)
    env = svc.run("cuantos clientes tienen prestamos?", user, executor=Ejecutor(), sql_executor=FakeExecutor())
    assert env.flow == "ask" and env.figure is not None and env.data is None
    assert env.assumptions == []
    steps = [s.step for s in svc.deps.audit.records[-1].steps]
    assert steps.index("ask") < steps.index("compute")


def test_un_periodo_lo_responde_la_fase_1b():
    """Un periodo ("el mes pasado") queda fuera de la plantilla: el SQL de un LLM lo responde."""
    from discovery_data_agent.bootstrap import user_with_databases
    from test_cifras_agregadas import Ejecutor

    planner = SchemaPlanner()
    svc = coexist_service(planner)
    user = user_with_databases(svc, "dev", None)
    plantilla = Ejecutor()
    env = svc.run("cuantos clientes se registraron el mes pasado", user, executor=plantilla,
                  sql_executor=FakeExecutor(QueryResult(["total"], [[42]])))
    assert plantilla.calls == [] and env.figure is None
    assert env.flow == "ask" and env.answer_text == "Se registraron 42 clientes."
    assert not any(a.startswith("No calculé la cifra") for a in env.assumptions)


def test_sin_fase_1b_la_plantilla_sigue_diciendo_por_que_no_calcula():
    from discovery_data_agent.bootstrap import user_with_databases
    from test_cifras_agregadas import Ejecutor

    svc = coexist_service(SchemaPlanner())
    svc.deps.settings.features.ask_llm_sql = False
    user = user_with_databases(svc, "dev", None)
    env = svc.run("cuantos clientes se registraron el mes pasado", user, executor=Ejecutor(),
                  sql_executor=FakeExecutor())
    assert env.flow == "discover" and env.data is None
    assert any(a.startswith("No calculé la cifra") for a in env.assumptions)


# --- gráficos: la IA sugiere, los datos confirman ------------------------------------------------------------
from discovery_data_agent.ask.engine import chart_for  # noqa: E402
from discovery_data_agent.ask.ports import ChartSuggestion  # noqa: E402

ESTADOS = QueryResult(["estado", "total"], [["Vigente", 1796], ["Cancelado", 793], ["En mora", 80]])


def test_un_desglose_se_grafica_como_lo_sugiere_la_ia():
    chart = chart_for(ChartSuggestion(kind="bar", label_column="Estado", value_column="TOTAL", title="Préstamos"), ESTADOS)
    assert (chart.kind, chart.label_column, chart.value_column, chart.title) == ("bar", "estado", "total", "Préstamos")
    assert chart_for(ChartSuggestion(kind="pie", label_column="estado", value_column="total"), ESTADOS).kind == "pie"


@pytest.mark.parametrize("suggestion, result", [
    (ChartSuggestion(kind="none"), ESTADOS),  # la IA dijo que no
    (ChartSuggestion(kind="bar", label_column="estado", value_column="no_existe"), ESTADOS),
    (ChartSuggestion(kind="bar", label_column="estado", value_column="estado"), ESTADOS),
    (ChartSuggestion(kind="bar", label_column="estado", value_column="total"), QueryResult(["estado", "total"], [["A", 1]])),
    (ChartSuggestion(kind="bar", label_column="estado", value_column="total"),
     QueryResult(["estado", "total"], [["A", 1], ["B", None]])),  # una medida vacía
    (ChartSuggestion(kind="pie", label_column="estado", value_column="total"),
     QueryResult(["estado", "total"], [["A", 5], ["B", -2]])),  # un pastel no reparte negativos
    (ChartSuggestion(kind="pie", label_column="estado", value_column="total"),
     QueryResult(["estado", "total"], [[str(i), 1] for i in range(13)])),  # demasiadas porciones
    (ChartSuggestion(kind="bar", label_column="estado", value_column="total"),
     QueryResult(["estado", "total"], [["A", 1], ["B", 2]], truncated=True)),
])
def test_sin_datos_que_lo_sostengan_no_hay_grafico(suggestion, result):
    assert chart_for(suggestion, result) is None


def test_la_respuesta_lleva_el_grafico_confirmado(service, analyst):
    p = plan(sql="SELECT OnboardingStatus AS estado, COUNT(*) AS total FROM [VBank_ING].[dbo].[Users] "
                 "GROUP BY OnboardingStatus")
    p.chart = ChartSuggestion(kind="pie", label_column="estado", value_column="total", title="Clientes por estado")
    env = ask_service(service, FakePlanner(p)).run(Q, analyst, sql_executor=FakeExecutor(
        QueryResult(["estado", "total"], [["COMPLETO", 10], ["PENDIENTE", 3]])))
    assert env.data.chart.kind == "pie" and env.data.chart.title == "Clientes por estado"
