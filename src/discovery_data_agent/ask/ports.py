"""Puertos del AskFlow: el planner (LLM) y el ejecutor (la conexión del usuario los da la capa de integración)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ChartSuggestion(BaseModel):
    kind: Literal["bar", "pie", "none"] = Field(
        description="bar: comparar una medida entre categorías, rankings o evolución en el tiempo. pie: partes de un "
                    "total (porcentajes o reparto) con pocas categorías, todas positivas. none: una cifra sola, un "
                    "listado de registros o varias medidas que no se comparan en una sola escala.")
    label_column: str = Field(default="", description="Alias de la columna con las categorías")
    value_column: str = Field(default="", description="Alias de la columna numérica que se grafica")
    title: str = Field(default="", description="Título corto del gráfico, en lenguaje de negocio")


class SqlPlan(BaseModel):
    """Lo que devuelve el planner. Nunca ve los resultados: la frase lleva marcadores que se rellenan después."""

    database: str = Field(description="Base de datos donde se ejecuta la consulta")
    sql: str = Field(description="Una sola sentencia SELECT en T-SQL con nombres de tres partes [db].[schema].[tabla]")
    answer_template: str = Field(
        description="Frase final para una persona no técnica, en español, que responde directo a la pregunta. "
                    "Se usa cuando el resultado es una sola fila: cada cifra va como marcador {alias} con el alias "
                    "exacto de una columna del SELECT. Sin otros números.")
    list_intro: str = Field(
        default="",
        description="Frase que presenta el resultado cuando son varias filas (un listado o un desglose). Solo admite "
                    "el marcador {filas} (cuántas filas hay); sin otros marcadores ni números.")
    explanation: str = Field(description="Cómo se calculó, en una o dos frases sencillas, sin nombres técnicos")
    filters: list[str] = Field(default_factory=list,
                               description="Criterios aplicados en lenguaje sencillo, p. ej. 'Solo préstamos vigentes'")
    chart: ChartSuggestion = Field(
        default_factory=lambda: ChartSuggestion(kind="none"),
        description="Si un gráfico ayuda a entender el resultado y cuál. Se decide antes de ver los datos.")


class QuestionInterpretation(BaseModel):
    """Lo que entiende el LLM de la pregunta, sin listas de palabras clave: si pide un dato, la pregunta limpia y
    explícita, y en qué base y tablas buscar. Recibe solo metadatos (nombres y descripciones), nunca datos."""

    kind: Literal["dato", "descubrimiento", "fuera_de_alcance"] = Field(
        description="dato: pide cifras, conteos, sumas, promedios, rankings, listados o filas calculadas con los "
                    "datos. descubrimiento: pregunta dónde está, qué significa o cómo se relaciona un dato. "
                    "fuera_de_alcance: saludos, temas ajenos o pedidos de modificar información.")
    refined_question: str = Field(
        description="La pregunta reescrita en español, completa y sin ambigüedad: resuelve referencias a preguntas "
                    "anteriores, convierte periodos relativos en fechas exactas (p. ej. 'el trimestre pasado' → "
                    "'del 01/07/2026 al 30/09/2026') y nombra los conceptos de negocio con precisión.")
    database: str | None = Field(default=None, description="Base de datos que contiene la información, si aplica")
    tables: list[str] = Field(default_factory=list,
                              description="Tablas o vistas necesarias, como Base.esquema.Tabla, tomadas de la lista")


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list] = field(default_factory=list)
    truncated: bool = False


class QueryRejected(RuntimeError):
    """SQL Server rechazó la consulta. `retry=False` cuando reintentar no sirve (permiso denegado)."""

    def __init__(self, message: str, retry: bool = True):
        super().__init__(message)
        self.retry = retry


class QueryExecutor(Protocol):
    def run(self, server: str, database: str, sql: str, max_rows: int, probe: bool = False) -> QueryResult:
        """`probe`: consulta auxiliar del planner (valores de categorías, rangos de fechas)."""
        ...

    def server_label(self, server: str) -> str: ...


class SqlPlanner(Protocol):
    def plan(self, question: str, schema: str, feedback: list[str]) -> SqlPlan: ...


class QuestionInterpreter(Protocol):
    def interpret(self, question: str, history: list[str], overview: str, today: str) -> QuestionInterpretation: ...
