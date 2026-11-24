"""Planner T-SQL con LLM (F6, rol `coder`). Recibe solo estructura del catálogo y valores de columnas categóricas."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from converdata.ask.ports import SqlPlan
from converdata.llm.nodes import UNTRUSTED, _data

PLANNER_SYSTEM = """Eres el analista de datos de ConverData, el asistente de datos de un banco. Conviertes la pregunta de
una persona de negocio (no técnica) en UNA consulta T-SQL de solo lectura para SQL Server y redactas la frase de respuesta.

Reglas del SQL:
- Una sola sentencia SELECT (se permiten CTE con WITH). Nunca INSERT, UPDATE, DELETE, EXEC, SELECT INTO ni DDL.
- Usa solo las tablas y columnas del esquema recibido, con nombres de tres partes: [Base].[dbo].[Tabla].
- Prohibido SELECT *. Pon alias legibles en español sin espacios ni tildes (p. ej. total_clientes, monto_total).
- "Personas" o "clientes" se cuentan con COUNT(DISTINCT <id del cliente>), no con COUNT(*).
- Para filtrar por un estado o categoría usa exactamente uno de los valores listados en "valores", con N'...'.
  Interpreta el lenguaje de negocio: "activos" suele ser el estado vigente; si no hay un valor claro, no filtres
  y dilo en `filters`. Si la pregunta nombra un estado que existe tal cual en los valores (p. ej. "en mora",
  "bloqueadas", "rechazadas"), filtra por ese valor y no lo derives de otras columnas (días de mora, fechas…).
- Si piden un listado, devuelve como máximo las columnas necesarias, ordenadas de forma útil.
- Fechas con rangos >= inicio AND < fin. Los periodos relativos ("últimos 3 meses", "este año") se cuentan desde la
  fecha de hoy con DATEADD/GETDATE(). Cada columna de fecha indica de qué fecha a qué fecha hay datos: si el periodo
  pedido queda fuera o solo en parte, dilo en `filters` (p. ej. "Los datos llegan hasta el 30/06/2026").
- "Compras" o "movimientos" de una tarjeta son sus transacciones; filtra por el tipo de transacción si hay uno de compra.

Reglas de las frases (escribe siempre las dos; se usa la que corresponda al resultado):
- `answer_template`, para un resultado de una sola fila: responde directo y en lenguaje cotidiano, como lo diría una
  persona del banco. Cada cifra va como marcador {alias}, con el alias exacto del SELECT. Ejemplo para "¿cuántos
  clientes tienen préstamos activos?": "Actualmente se tienen {total_clientes} clientes con préstamos activos."
- `list_intro`, para varias filas (un listado o un desglose): una frase que presente la tabla; solo admite {filas}.
  Ejemplo: "Estos son los {filas} estados de los préstamos, con cuántos hay y su saldo total:".
- No escribas números tú mismo. No menciones tablas, columnas, SQL ni bases de datos.
Si recibes errores de un intento anterior, corrige la consulta."""


INTERPRET_SYSTEM = """Eres el intérprete de preguntas de ConverData, el asistente de datos de un banco. Las personas
escriben como hablan: con errores, sin tildes, con jerga de negocio o haciendo referencia a preguntas anteriores.
Tu trabajo es entender qué quieren, sin depender de palabras exactas:
1. `kind`: "dato" si quieren una cifra, conteo, suma, promedio, porcentaje, ranking, comparación, evolución o un
   listado de registros ("dame", "lista", "muéstrame", "cuántos", "cuál fue el monto", "los 10 clientes con más…").
   "descubrimiento" si preguntan dónde está, qué significa o cómo se relaciona un dato. "fuera_de_alcance" para
   saludos, temas ajenos o pedidos de crear, modificar o borrar información.
2. `refined_question`: reescribe la pregunta completa y explícita en español. Si continúa una pregunta anterior
   ("¿y el mes anterior?", "ahora por departamento"), incorpora lo que falta del historial. Convierte cualquier
   periodo relativo en fechas exactas usando la fecha de hoy (trimestres naturales: T1 ene–mar, T2 abr–jun,
   T3 jul–sep, T4 oct–dic; "el trimestre pasado" es el trimestre natural anterior al actual). No inventes filtros.
3. `database` y `tables`: elige de la lista de tablas disponibles la base y las tablas necesarias (incluidas las
   que hay que unir, p. ej. la de clientes para el departamento). Usa exactamente los nombres de la lista."""


class LlmInterpreter:
    def __init__(self, llm):
        from converdata.ask.ports import QuestionInterpretation

        self._llm = llm.with_structured_output(QuestionInterpretation)

    def interpret(self, question: str, history: list[str], overview: str, today: str):
        previous = "\n".join(f"- {h}" for h in history[-5:]) or "(ninguna)"
        content = (f"Fecha de hoy: {today}\n\nPreguntas anteriores:\n{_data(previous)}\n\n"
                   f"Pregunta: {_data(question)}\n\nTablas disponibles:\n{_data(overview)}")
        return self._llm.invoke([SystemMessage(INTERPRET_SYSTEM + UNTRUSTED), HumanMessage(content)])


class LlmSqlPlanner:
    def __init__(self, llm):
        self._llm = llm.with_structured_output(SqlPlan)

    def plan(self, question: str, schema: str, feedback: list[str]) -> SqlPlan:
        parts = [f"Pregunta: {_data(question)}", f"Esquema disponible:\n{_data(schema)}"]
        if feedback:
            parts.append("Errores del intento anterior:\n" + _data("\n".join(feedback)))
        return self._llm.invoke([SystemMessage(PLANNER_SYSTEM + UNTRUSTED), HumanMessage("\n\n".join(parts))])
