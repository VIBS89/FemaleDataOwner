---
name: nueva-historia
description: Flujo completo para implementar una historia de usuario (HU-xx) del backlog de ConverData con TDD y DDD, desde leer los criterios de aceptación hasta revisar, actualizar la documentación viva y dejar el commit listo.
argument-hint: "HU-xx"
disable-model-invocation: true
---

# Implementar una historia: $ARGUMENTS

Si no se indicó HU, lee `docs/PLAN-desarrollo.md` y propón la siguiente por sprint y prioridad (*Must* primero); espera confirmación.

## 1. Preparar
1. Rama desde `main` si estás en `main`: `git switch -c feat/hu-xx-<tema>`.
2. Lee la HU y sus CA en `docs/backlog/on-premise.md`, las specs que cita (F/OP/CN) y los RF del PRD.
3. Verifica dependencias de otras HU. Si faltan, dilo antes de empezar.
4. Línea base: `.venv/Scripts/python -m pytest -q` debe estar en verde antes de tocar nada.
5. Crea una lista de tareas con un paso por CA.

## 2. Construir (un CA a la vez)
Sigue el skill `tdd-ciclo` (rojo → verde → refactor) respetando `ddd-convenciones`.
Para paridad de interfaces: si cambia un caso de uso, revisa que API, MCP y CLI lo expongan igual, con los mismos permisos y auditoría.

## 3. Revisar (en paralelo, sin pedir permiso entre uno y otro)
Lanza los subagentes que apliquen **sobre el diff**:
- `revisor-arquitectura-specs`: siempre.
- `revisor-seguridad-datos`: si tocaste `identity/`, `audit/`, auth/vault/tokens/curación de la API, `flows/discover.py`, `llm/` u `observability/`.
- `evaluador-descubrimiento`: si tocaste `discovery/`, `flows/discover.py`, `graph/`, `memory/`, `llm/` o los fixtures de evaluación.
- `verificador-contrato-web-api`: si cambiaste endpoints o `web/src/lib/{api,types}.ts`.

Corrige todo hallazgo alto/medio con un test primero. No los descartes sin justificarlo.

## 4. Documentación viva
Actualiza en el mismo cambio: `docs/PLAN-desarrollo.md` (estado, conteo de tests, resultados), el estado de la HU en el
backlog, `docs/architecture/capas-backend.md` si hay módulos o deuda nueva, y `README.md` si cambian comandos.

## 5. Cierre
1. Suite completa y prueba de capas en verde (los hooks lo exigen antes del commit; no los saltes).
2. Resume al usuario: CA cubiertos con `archivo::test`, hallazgos de los revisores y qué quedó pendiente.
3. **Pregunta antes de hacer commit.** Mensaje en español: `feat: <qué> (HU-xx)`.
4. No hagas push ni abras PR sin que el usuario lo pida.
