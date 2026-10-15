# F4 — Schema Linking

## Historia de usuario
Como **agente SQL**, necesito un contexto pequeño y preciso (5 a 15 tablas con sus columnas relevantes y rutas de join)
para generar SQL correcto en una BD de más de 300 tablas.

## Algoritmo
1. **Recuperación amplia**: `search_tables(rewritten_question + entities, k=30, databases, visible_ids)` y `search_columns(k=50)`. Las columnas suman puntos a su tabla.
2. **Golden boost**: las tablas usadas por los 5 golden SQL más similares reciben un bonus.
3. **Poda con LLM**: el nodo `schema_linker` recibe las 30 candidatas en formato compacto (`nombre: descripción | columnas clave`) y devuelve 3 a 10 tablas, cada una con una justificación de una línea.
4. **Expansión por FKs**: `find_join_path(selected)` sobre el grafo `networkx` (nodos = tablas, aristas = FKs ponderadas por cardinalidad). Añade las tablas puente necesarias, sin superar 15 tablas en total.
5. **Proyección de columnas**: para cada tabla elegida, PK, FKs, columnas mencionadas o similares (top 12) y columnas de fecha y estado.
6. **Filtro de permisos**: se descarta cualquier objeto fuera de `visible_ids`, como defensa en profundidad.

## Salida (`SchemaContext`)
```python
class SchemaContext(BaseModel):
    database: str
    tables: list[TableCtx]        # nombre completo, descripción, columnas[], row_count
    join_paths: list[JoinPath]    # [{left: "dbo.Pedido.ClienteID", right: "dbo.Cliente.ClienteID"}]
    glossary_hits: list[GlossaryHit]
    golden_examples: list[GoldenHit]
    ddl_snippet: str              # CREATE TABLE compacto que se entrega al planner
```

## Criterios de aceptación
1. Recall de tablas de al menos 95 % en el set de evaluación: las tablas del SQL de referencia están en `tables`.
2. El tamaño medio del contexto es menor de 4 000 tokens.
3. Nunca incluye objetos fuera de la visibilidad del usuario (test con un usuario restringido).
4. Si dos tablas candidatas no tienen ruta de FK, se informa en `assumptions` y se permite un join por nombre de columna solo si las columnas coinciden en nombre y tipo.
