# F23 — Fuentes de conocimiento: diccionarios, documentación, ETL y reglas de negocio · común

> Origen: Propuesta, secciones 1, 6 y "¿Por qué es innovador?": el agente debe razonar sobre **metadatos, documentación técnica,
> procesos ETL, diccionarios y glosarios de datos y conocimiento institucional**, no solo sobre la estructura de las bases.
> Infraestructura por entorno: **on-premise** → [OP-02](../on-premise/OP-02-catalogo-memoria.md) · **cloud native** → [CN-02](../cloud-native/CN-02-catalogo-memoria.md)

## Historia de usuario
Como **administrador de datos**, quiero cargar los diccionarios de datos, la documentación funcional y técnica, los paquetes ETL y las reglas
de negocio que hoy están dispersos, para que el agente los conecte con las tablas y columnas del catálogo.

## Fuentes y conectores
Cada fuente implementa la interfaz `KnowledgeConnector`:
```python
class KnowledgeConnector(Protocol):
    kind: Literal["data_dictionary", "document", "etl", "business_rule", "metadata"]
    def discover(self) -> Iterable[SourceRef]: ...           # qué hay y su hash
    def extract(self, ref: SourceRef) -> list[KnowledgeItem]: ...
```

| Fuente | Conector (fase 1) | Qué produce |
|---|---|---|
| **Diccionarios de datos** (Excel/CSV) | `DictionaryConnector` con un mapeo de columnas por archivo en `config/knowledge.yaml` | Descripciones, dominios, dueños y sinónimos por columna → `description_source: data_dictionary` |
| **Documentación** (DOCX, PDF, Markdown, HTML; carpeta compartida o exportación de SharePoint/Confluence) | `DocumentConnector` (unstructured + chunking por sección, 500–800 tokens) | Fragmentos en la colección `documents`, con `linked_assets` |
| **ETL: SQL Server Integration Services** | `SsisConnector`: `SSISDB.catalog.packages` + parseo del XML `.dtsx` (orígenes, destinos, SQL embebido) | Aristas de linaje `origen → destino` con el paquete como `via` |
| **ETL: SQL Agent** | `SqlAgentConnector`: `msdb.dbo.sysjobs`, `sysjobsteps`, `sysschedules` | Qué jobs ejecutan qué paquetes o SPs, con su frecuencia |
| **ETL: SPs y vistas** | `sys.sql_expression_dependencies` + parseo con sqlglot de `INSERT … SELECT`, `MERGE`, `SELECT … INTO` | Aristas de linaje a nivel de tabla (columna cuando el parseo lo permite) |
| **Reglas de negocio** | Archivos `knowledge/rules/*.yaml` mantenidos por humanos + sugerencias extraídas | Colección `business_rules` |
| **Otras plataformas** (data warehouse o data lake fuera de SQL Server) | Interfaz `MetadataConnector` (listar objetos, describir, dependencias) | Mismo formato de catálogo que F1. Fase 1: SQL Server (incluye el DWH en SQL Server). Adaptadores posteriores: Fabric/Synapse, Databricks Unity Catalog, AWS Glue, Oracle |

## Vinculación con el catálogo (`linked_assets`)
Para cada `KnowledgeItem`:
1. **Coincidencia determinista** de nombres calificados (`db.schema.tabla`, `tabla.columna`) y alias conocidos (sinónimos de F1).
2. **Coincidencia semántica**: embeddings del fragmento contra `tables`/`columns`, con umbral 0.8.
3. **Confirmación con LLM** (rol `fast`) solo para los casos entre 0.65 y 0.8.
El resultado guarda `{asset_key, method, score}`; los vínculos con `score < 0.8` quedan `reviewed: false`.

## Reglas de negocio
```yaml
# knowledge/rules/onboarding.yaml
- id: BR-ONB-004
  text: "ClientCode se asigna al completar la verificación de identidad; antes de eso el usuario solo tiene UserId."
  domain: onboarding_digital
  applies_to: [VBank_ING.dbo.Users.ClientCode, VBank_ING.dbo.Users.UserId]
  source: "Manual de procesos Banca Digital v3, sección 4.2"
  owner: "Producto Banca Digital"
  reviewed: true
```
El Catalog Builder **sugiere** reglas (`reviewed: false`) a partir de: filtros recurrentes en SPs y vistas (`WHERE Estado = 'A'`), expresiones
`CASE` que definen categorías, restricciones `CHECK` y fragmentos de documentos con lenguaje normativo ("se considera", "solo cuando").
Una regla sugerida nunca se presenta como oficial: la UI la marca "sugerida, sin revisar".

## Linaje (`knowledge/lineage/*.yaml`, derivado)
```yaml
- from: Onboarding.dbo.Solicitud
  to: VBank_ING.dbo.Users
  via: {kind: ssis, name: ONB_CargaUsuarios, job: "JOB_ONB_Nocturno", schedule: "diario 02:00"}
  level: table
  columns: [{from: NumeroDocumento, to: LegalClientId}]
```
El linaje se carga en el mismo grafo `networkx` de F4 como aristas de tipo `etl` (las FKs son de tipo `fk`). En la fase 1 se cubre un salto y
el nivel de tabla; el linaje completo de extremo a extremo es la visión futura "Descubrimiento automatizado de linaje".

## Residencia y seguridad (F17)
- Los documentos y diccionarios **pueden contener datos de clientes** (ejemplos, capturas, extractos). Antes de indexar, cada fragmento pasa por
  un detector de PII (Microsoft Presidio con reconocedores en español y patrones locales: DUI, NIT, número de cuenta, tarjeta, teléfono, correo).
  - Si hay PII, el fragmento se indexa **redactado** (`<DUI>`, `<CUENTA>`) y se marca `redacted: true`.
  - Si más del 20 % de los tokens son PII, el fragmento se descarta y se registra en el reporte de ingesta.
- El índice guarda fragmentos redactados (clase D3 de F17); el documento original no se copia y permanece en su repositorio de origen.
- El SQL embebido en paquetes y SPs se guarda sin literales (sustituidos por placeholders tipados, como el golden SQL).
- Los conectores de SSISDB, msdb y definiciones de SPs se implementan como herramientas adicionales de `converdata-discovery`
  ([F18](F18-discovery-mcp.md)): consultas fijas y parametrizadas, con un login técnico de solo lectura, como el de metadatos de F1.
- Cada fragmento conserva la ACL de su origen cuando el conector la conoce (`allowed_groups`) y la búsqueda la aplica como pre-filtro.

## Comandos
- `converdata knowledge ingest [--source <nombre>]`: procesa solo lo que cambió (por hash).
- `converdata knowledge report`: fragmentos indexados, redactados y descartados; vínculos sin revisar; conflictos.

## Conflictos
Si dos fuentes describen el mismo activo de forma contradictoria (por ejemplo, el diccionario y `MS_Description`), el activo se marca
`conflict: true`, la respuesta muestra ambas descripciones con su fuente y el caso entra en la cola de curación (F24).

## Criterios de aceptación
1. Un diccionario Excel de prueba con 200 columnas actualiza las descripciones del catálogo con `description_source: data_dictionary`
   sin sobrescribir campos `human`.
2. Un paquete `.dtsx` de prueba produce las aristas de linaje esperadas (origen, destino, paquete y job).
3. Un documento con un DUI y un número de cuenta de prueba queda indexado con ambos valores redactados (búsqueda del literal en el índice = 0).
4. La pregunta "¿qué reglas aplican al ClientCode?" devuelve `BR-ONB-004` con su fuente.
5. Una segunda ingesta sin cambios no llama al LLM ni reindexa.
