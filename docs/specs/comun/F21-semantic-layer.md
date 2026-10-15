# F21 — Capa semántica: métricas gobernadas y consultas verificadas · común

> Inspirada en el *semantic model* YAML y el *Verified Query Repository* de Snowflake Cortex Analyst, y en dbt MetricFlow (Apache-2.0 desde oct-2025).
> Se adopta el **formato y el enfoque**, sin depender de dbt ni de Snowflake.

## Problema
Generar SQL libre para "ventas netas" o "margen" da cifras distintas según el día. Las organizaciones ya tienen definiciones
oficiales; el agente debe **usarlas** en lugar de reinventarlas.

## Modelo semántico (`catalog/_semantic/*.yaml`)
```yaml
entities:
  - name: cliente
    canonical_table: Ventas.dbo.Cliente          # de F19
    key: ClienteID
    synonyms: [customer, comprador]
dimensions:
  - name: region
    expr: r.Nombre
    table: Ventas.dbo.Region
  - name: fecha_factura
    expr: p.FechaFactura
    type: time
    grains: [day, month, quarter, year]
measures:
  - name: importe_bruto
    expr: SUM(p.Importe)
    table: Ventas.dbo.Pedido
metrics:
  - name: ventas_netas
    label: "Ventas netas"
    type: derived                     # simple | ratio | derived | cumulative
    expr: importe_bruto - descuentos - devoluciones
    default_time_dimension: fecha_factura
    owner: Finanzas
    certified: true
verified_queries:
  - name: ventas_netas_por_region_trimestre
    question: "¿Cuáles fueron las ventas netas por región el último trimestre?"
    sql: |
      SELECT r.Nombre AS region, SUM(...) AS ventas_netas
      FROM ...
      WHERE p.FechaFactura >= @inicio AND p.FechaFactura < @fin
      GROUP BY r.Nombre
    verified_by: finanzas@empresa
```

## Uso
- **Planner (F6)**, nueva prioridad: SP oficial → **métrica certificada / consulta verificada** → golden SQL → SQL nuevo.
- Si la pregunta menciona una métrica certificada, el SQL se **compila** desde su definición (no lo inventa el LLM) y la respuesta muestra la insignia "métrica certificada · Finanzas".
- El motor de análisis (F20) usa las mismas métricas en todos sus pasos, así que las comparaciones son coherentes.
- El modelo semántico solo contiene definiciones (D3) y SQL con parámetros, sin literales de datos (F17).

## Construcción
- **Arranque asistido**: el Catalog Builder propone métricas y dimensiones a partir de vistas existentes, SPs de reporting y joins frecuentes de Query Store (F19), marcadas `certified: false`.
- **Certificación humana**: un propietario de datos revisa y certifica (`converdata semantic review`).
- Las golden SQL (F2) muy usadas se pueden promover a `verified_queries`.

## Criterios de aceptación
1. Dos usuarios que preguntan "ventas netas del Q3" con redacciones distintas obtienen el mismo SQL compilado desde la métrica certificada.
2. Una métrica no certificada se puede usar, pero la respuesta lo indica y baja el `confidence`.
3. El validador (F7) comprueba que el SQL compilado de cada métrica es válido tras cada `catalog refresh`.
