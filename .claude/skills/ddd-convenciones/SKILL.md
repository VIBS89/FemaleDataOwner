---
name: ddd-convenciones
description: Convenciones de DDD y arquitectura por capas de ConverData (dominio, aplicación, infraestructura, integración), lenguaje ubicuo e invariantes de seguridad. Úsalo al diseñar o modificar cualquier módulo de src/converdata o api/converdata_api, al decidir en qué capa va una clase, o al introducir una dependencia nueva.
---

# DDD en ConverData

Fuente de verdad: `docs/architecture/capas-backend.md` y `tests/test_architecture.py` (`LAYERS`, `ALLOWED`, `ADAPTER_LIBS`).
Si este skill y esos archivos discrepan, mandan ellos.

## Regla de dependencias
```
integración ──► aplicación ──► dominio ◄── infraestructura
```
| Capa | Qué va aquí | Qué NO va |
|---|---|---|
| Dominio (`models`, `catalog`, `discovery`, `graph`, `builder`, `identity`, `audit`, `memory.base`, `metadata.ports`) | Entidades, objetos de valor, reglas deterministas, **puertos** (`Protocol`) | Librerías de adaptador (`pyodbc`, `langchain_*`, `fastapi`, `mcp`, `httpx`, `boto3`), E/S, relojes o azar sin inyectar |
| Aplicación (`flows`, `application`) | Casos de uso; orquestación con LangGraph (único lugar) | SQL, HTTP, SDKs de proveedores |
| Infraestructura (`memory.*_store`, `metadata.sqlserver`, `llm`, `observability`) | Implementaciones de puertos | Reglas de negocio |
| Integración (`integration`, `cli`, `bootstrap`, `evaluation`, `api/`) | Traducir protocolo ↔ caso de uso; **composición solo en `bootstrap.py`** | Lógica de negocio: si la API o la CLI deciden algo, súbelo a `application` o `discovery` |

## Cómo modelar
- **Lenguaje ubicuo**: usa los términos del glosario (PRD Anexo B): `asset_key`, visibilidad, golden discovery, steward,
  brecha de conocimiento, confianza. No inventes sinónimos (`resource`, `permissions`, `owner`) para conceptos que ya tienen nombre.
- **Objetos de valor**: inmutables (`@dataclass(frozen=True)` o `BaseModel` con `frozen`), comparados por valor, validados
  al construirse (`Field(ge=0, le=1)`). `UserContext.visible_ids` es `frozenset` por esa razón.
- **Entidades**: identidad explícita (`asset_key`, `user_id`); no compares por atributos mutables.
- **Puertos**: `Protocol` en el dominio, nombrado por el rol (`VectorStore`, `Embedder`), no por la tecnología
  (nada de `SqlServerStore` en el dominio). La implementación determinista y la de LLM cumplen el mismo puerto.
- **Contextos**: Descubrimiento (`discovery`, `graph`, `flows.discover`), Catálogo (`catalog`, `builder`, `flows.catalog`),
  Identidad y auditoría (`identity`, `audit`), Conocimiento (`memory`, curación). No cruces de un contexto a las
  entrañas de otro: usa su interfaz pública (`__init__`, puerto o `DiscoveryTools`).
- **Casos de uso únicos**: API, MCP y CLI llaman a `application.discovery.DiscoveryTools`; no repliques lógica por interfaz.
- **Módulo nuevo** ⇒ agrégalo a `LAYERS` en `tests/test_architecture.py` y a la tabla de `capas-backend.md` en el mismo cambio.

## Invariantes (rompen el producto si fallan)
1. **Permisos (F14)**: toda búsqueda recibe `visible_ids`; lo no visible responde igual que lo inexistente.
   Ninguna herramienta acepta identidad como argumento (OP-03 CA5).
2. **Auditoría fail-closed (F11)**: si el registrador falla, no hay respuesta.
3. **Sin valores ni PII**: el catálogo guarda metadatos, nunca datos de clientes; los logs no contienen la pregunta, SQL ni filas (HU-21).
4. **Determinismo**: el orden de los pasos nunca depende del LLM; todo nodo con LLM tiene respaldo determinista
   y el flujo corre sin proveedores configurados.
5. **Residencia (F17)**: los datos de clientes no salen del banco; Ollama solo en local.
6. **Contrato de respuesta**: `AnswerEnvelope` con evidencia y confianza (PRD §8.3).

## Deuda conocida (no la agraves)
Ver "Deuda conocida" al final de `docs/architecture/capas-backend.md` (`catalog.store` mezcla carga YAML,
`PyodbcObjectLister` en dominio, API llamando al flujo sin pasar por `DiscoveryTools`). Si tu cambio toca esas
zonas, resuélvelo o déjalo anotado; para saldarla usa `/pagar-deuda-tecnica`.

## Antes de dar por bueno un cambio
`.venv/Scripts/python -m pytest tests/test_architecture.py -q` y, para cambios no triviales, el subagente
`revisor-arquitectura-specs` (y `revisor-seguridad-datos` si tocaste identidad, auditoría, auth o LLM).
