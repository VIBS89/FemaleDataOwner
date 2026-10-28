---
name: tdd-ciclo
description: Ciclo TDD rojo-verde-refactor para ConverData, partiendo de los criterios de aceptación (CA) de una historia HU-xx o spec. Úsalo al implementar una funcionalidad o corregir un bug; fuerza escribir y ver fallar el test antes del código de producción.
argument-hint: "[HU-xx | descripción del comportamiento | bug]"
---

# TDD en ConverData

Objetivo: `$ARGUMENTS`. Si está vacío, pregunta qué comportamiento o HU se va a desarrollar.

## 0. Entender (sin código)
- Lee la HU en `docs/backlog/on-premise.md` y las specs que cita (`docs/specs/...`). Lista los CA.
- Traduce cada CA a **un comportamiento observable** ("un usuario sin acceso no ve el activo"), no a un detalle interno.
- Ordena de lo más simple a lo más complejo; empieza por el camino feliz mínimo.

## 1. Rojo
1. Elige el nivel más bajo que pruebe el comportamiento: dominio (`tests/test_core.py`, `test_graph_rag.py`) →
   aplicación (`test_application_discovery.py`, `test_discover_flow_e2e.py`) → integración (`api/tests/`, `test_mcp_server.py`).
2. Reutiliza lo existente antes de crear nada: fixtures `service`, `analyst`, `rrhh_user` (`tests/conftest.py`);
   `FakeDb`/`FakeConnection`/`FakeCursor` (`tests/fakes.py`) para SQL Server; catálogos en `tests/fixtures/vbank` y `bancos`;
   modo demo (`CONVERDATA_DEMO=1`) para la API.
3. Escribe **un** test: nombre en español que describa el comportamiento
   (`test_get_asset_no_revela_lo_que_el_usuario_no_ve`), `from __future__ import annotations`, y el CA en el docstring.
4. Córrelo y **confirma que falla por la razón correcta** (no por un `ImportError` o un typo):
   ```bash
   .venv/Scripts/python -m pytest tests/<archivo>.py::<test> -q
   ```
   Si pasa sin código nuevo, el test no prueba nada: corrígelo.

## 2. Verde
- Escribe el código **mínimo** que lo hace pasar, en la capa correcta (ver skill `ddd-convenciones`). Sin generalizar por adelantado.
- Reglas de test: sin red, sin SQL Server real, sin LLM real; flujo en modo determinista o con dobles del gateway.
  No mockees librerías si existe un fake del puerto.
- Corre el test, luego el archivo, luego `tests/test_architecture.py`.

## 3. Refactor (en verde)
- Elimina duplicación, mejora nombres, extrae puertos/objetos de valor. Cero cambios de comportamiento.
- Corre la suite completa: `.venv/Scripts/python -m pytest -q`. Un refactor con la suite en rojo se revierte.
- No toques `eval/discovery.yaml` ni relajes un test para que pase.

## 4. Repite
Siguiente CA → vuelve al paso 1. Un commit por ciclo o por CA coherente.

## Tests obligatorios según el área
| Si tocas… | Debe existir |
|---|---|
| Permisos / visibilidad (F14) | Caso **negativo**: usuario sin acceso no ve el activo por API, MCP, caminos de unión ni sugerencias |
| Auditoría (F11) | Fail-closed: si el registrador falla, no hay respuesta |
| Logs / observabilidad (HU-21) | Los logs no contienen pregunta, SQL ni valores |
| `discovery/`, `flows/discover.py`, `graph/`, `memory/`, `llm/` | `converdata eval discovery` sin regresión (subagente `evaluador-descubrimiento`) |
| Endpoints de la API o `web/src/lib/api.ts` | Subagente `verificador-contrato-web-api` |
| Prompts / LLM | Una inyección más en `tests/test_prompt_injection.py` |

## Bugs
Primero un test que reproduce el bug y falla; luego el arreglo. Si el bug es de producción y no puedes corregirlo
ahora, deja el test marcado `xfail(strict=True)` con el motivo y repórtalo.

## Cierre
Reporta: tests añadidos (`archivo::test` → CA), salida real de pytest, CA sin cubrir y por qué.
Para generar tests en bloque a partir de una HU existe el subagente `escritor-tests`.
