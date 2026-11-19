---
name: nuevo-puerto-adaptador
description: Añade un puerto (Protocol) en el dominio y su adaptador en infraestructura con TDD, incluyendo fake de pruebas, test de contrato, registro en la prueba de capas y cableado en bootstrap. Úsalo para cualquier integración nueva (almacén, proveedor de LLM, fuente de metadatos, repositorio).
argument-hint: "<NombreDelPuerto> [tecnología]"
disable-model-invocation: true
---

# Nuevo puerto + adaptador: $ARGUMENTS

Si falta el nombre o la tecnología, pregunta. Antes de empezar, confirma que no existe ya un puerto equivalente
(`grep -rn "Protocol" src/converdata`): ampliar uno existente suele ser mejor que crear otro.

## Pasos (en este orden)

1. **Puerto en el dominio** — `Protocol` nombrado por el rol, no por la tecnología; vive con su contexto
   (p. ej. `memory/base.py`, `metadata/ports.py`, `discovery/ports.py`). Tipos de entrada/salida como objetos de valor
   inmutables. Si maneja datos de usuario, el parámetro de visibilidad (`visible_ids`) es obligatorio, no opcional (F14).
2. **Fake en `tests/fakes.py`** (o `InMemory...` en infraestructura si también sirve en modo determinista/demo).
   Debe cumplir el puerto y ser determinista.
3. **Test de contrato** (rojo): una batería parametrizada que corre contra el fake y, cuando haya servidor, contra el adaptador
   real (marcado para saltarse sin él, como `tests/test_sqlserver_store.py`). Cubre: camino feliz, vacío, no visible = inexistente,
   y el error del backend (debe fallar cerrado, no devolver datos parciales).
4. **Casos de uso** que dependen del puerto se prueban con el fake (skill `tdd-ciclo`).
5. **Adaptador en infraestructura** (verde): las librerías de adaptador (`pyodbc`, `langchain_*`, `boto3`, `httpx`…)
   se importan solo aquí. Credenciales por configuración/entorno, nunca en el código; `config/models.yaml` y `.env` no se editan.
6. **Capas**: registra el módulo en `LAYERS` de `tests/test_architecture.py` y en la tabla de `docs/architecture/capas-backend.md`.
   Si usa una librería nueva, evalúa si va en `ADAPTER_LIBS`.
7. **Composición**: se cablea **solo** en `bootstrap.py`; el dominio y la aplicación reciben el puerto por constructor.
8. **Dependencias**: extra opcional en `pyproject.toml` (como `sqlserver`, `bedrock`); el núcleo no debe exigirla.
9. **Observabilidad y auditoría**: sin contenido de preguntas, SQL ni valores en logs; si participa en una respuesta, pasa por el flujo auditado.
10. **Cierre**: `pytest -q` completo + `revisor-arquitectura-specs` (y `revisor-seguridad-datos` si maneja identidad, credenciales o LLM).

## Checklist final
- [ ] Puerto sin imports de adaptadores
- [ ] Fake + test de contrato
- [ ] Falla cerrado ante error del backend
- [ ] `LAYERS` y `capas-backend.md` al día
- [ ] Cableado solo en `bootstrap.py`
- [ ] Extra en `pyproject.toml`, sin secretos en el repo
