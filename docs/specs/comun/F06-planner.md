# F6 — Planner T-SQL / Stored Procedure

## Historia de usuario
Como **usuario**, quiero que el sistema genere la consulta correcta en T-SQL o use el stored procedure oficial cuando exista,
para obtener datos consistentes con los reportes de la empresa.

## Comportamiento
- Nodo `planner` del grafo (rol `coder` de F16, por ejemplo Claude Sonnet en Bedrock, temperatura 0).
- **Prioridad de estrategias** (ampliada con F21):
  0. **Métrica certificada o consulta verificada** de la capa semántica ([F21](F21-semantic-layer.md)): el SQL se compila desde la definición
     (o se usa el SP que la métrica declare en `procedure:`).
  1. **Stored procedure de la lista blanca** cuyo `description`/`intents` en `config/procedures.yaml` coincide con la pregunta (similitud ≥ 0.8) y cuyos parámetros pueden deducirse de la pregunta. Así se respeta la lógica oficial de negocio.
  2. **Golden SQL adaptado**, si hay un ejemplo con similitud ≥ 0.9.
  3. **T-SQL nuevo** generado a partir del `SchemaContext`.
- Reglas del prompt (dialecto T-SQL):
  - `TOP (n)` y no `LIMIT`; nombres citados con `[]` y siempre en formato de tres partes (`[db].[schema].[tabla]`).
  - Fechas con `>= inicio AND < fin` (sargable), sin funciones sobre columnas indexadas en el `WHERE`.
  - Agregaciones con alias en español legible; CTEs permitidas.
  - Prohibido `SELECT *`; solo columnas necesarias.
  - Joins solo por las `join_paths` recibidas, salvo que se justifique en `assumptions`.
  - Literales resueltos por F5 como **parámetros** (`@p1`), nunca concatenados.
- **Exploración de columnas** (inspirada en ReFoRCE): ante ambigüedad, consultas exploratorias pequeñas y validadas (`TOP 5`, `COUNT DISTINCT`) para confirmar formatos y valores antes de la consulta final.
- **Consultas entre BDs**: nombres de tres partes en el mismo servidor; plan federado si son servidores distintos ([F19](F19-multi-db-discovery.md)).
- Opcional, con `planner.candidates: 2` en la configuración: genera dos candidatos con prompts distintos. El Validator (F7) y el Verifier (F9) eligen; si ambos ejecutan y sus resultados coinciden, se suma confidence.

## Salida (`QueryPlan`)
```python
class QueryPlan(BaseModel):
    kind: Literal["sql", "procedure"]
    database: str
    sql: str | None
    params: dict[str, Any]
    procedure: str | None
    procedure_params: dict[str, Any] | None
    tables_used: list[str]
    assumptions: list[str]
    rationale: str               # explicación breve para el usuario
```

## `config/procedures.yaml`
```yaml
- name: Ventas.dbo.usp_VentasPorRegion
  description: "Ventas netas por región y periodo, lógica oficial de finanzas."
  intents: ["ventas por región", "ventas por zona"]
  side_effects: false            # true => requiere confirmación explícita del usuario (F12)
  params:
    FechaInicio: {type: date, required: true}
    FechaFin: {type: date, required: true}
    RegionID: {type: int, required: false}
  max_rows: 50000
  timeout_s: 60
```

## Criterios de aceptación
1. Con un SP aplicable, `kind=procedure` y parámetros correctos (test con `usp_VentasPorRegion`).
2. El SQL generado siempre pasa el parser de sqlglot `tsql`.
3. Cero literales de usuario concatenados en el SQL (test de inyección).
4. Precisión de ejecución de al menos 85 % en el set golden, sumado al bucle de corrección de F7.
