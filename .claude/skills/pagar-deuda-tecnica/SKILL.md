---
name: pagar-deuda-tecnica
description: Salda deuda técnica de ConverData de forma segura (pruebas de caracterización, pasos pequeños en verde, capas y documentación al día). Úsalo para resolver la "Deuda conocida" de capas-backend.md, mover código a la capa correcta o simplificar módulos sin cambiar su comportamiento.
argument-hint: "[ítem de deuda | módulo]"
disable-model-invocation: true
---

# Pagar deuda técnica: $ARGUMENTS

Un refactor **no cambia comportamiento**. Si hace falta cambiarlo, es una historia: usa `/nueva-historia`.

## 1. Elegir y acotar
- Sin argumento, lista la "Deuda conocida" de `docs/architecture/capas-backend.md` y propón la de mayor retorno
  (violaciones de capas y duplicación entre API/MCP/CLI primero). Espera confirmación.
- Ítems hoy conocidos: `catalog.store` mezcla modelo y carga YAML (extraer puerto `CatalogRepository`);
  `identity.visibility.PyodbcObjectLister` en dominio; la API llama a DiscoverFlow sin pasar por `DiscoveryTools` (HU-14, HU-16).
- Define el alcance en una frase y qué queda fuera. Un ítem por rama (`refactor/<tema>`).

## 2. Red de seguridad
- Suite completa en verde antes de empezar; anota el conteo de tests.
- Si el área no tiene cobertura, escribe **pruebas de caracterización** que fijen el comportamiento actual
  (skill `tdd-ciclo`, nivel de aplicación o integración). Deben pasar en el código sin tocar.
- Si el área toca recuperación o ranking, captura la línea base con `converdata eval discovery` (subagente `evaluador-descubrimiento`).

## 3. Refactor en pasos pequeños
1. Un movimiento a la vez (extraer puerto → mover implementación → redirigir llamadores → borrar lo viejo).
2. Tras cada paso: `.venv/Scripts/python -m pytest -q`. Rojo ⇒ revierte ese paso, no avances.
3. Guía de diseño: skill `ddd-convenciones` (dependencias hacia el dominio, composición en `bootstrap.py`, un caso de uso por intención).
4. Sin código muerto: borra lo que quede sin uso; no dejes "compatibilidad" sin llamadores.
5. No mezcles en el mismo cambio funcionalidad nueva ni formateo masivo.

## 4. Verificar y documentar
- Suite igual o mayor que la inicial, `test_architecture.py` en verde, eval sin regresión si aplica.
- Subagentes: `revisor-arquitectura-specs` siempre; `revisor-seguridad-datos` si tocaste identidad, auditoría o auth.
- Actualiza `capas-backend.md`: quita el ítem de "Deuda conocida", corrige la tabla de capas y `LAYERS`; refleja el estado en `docs/PLAN-desarrollo.md`.

## 5. Cierre
Resume qué se movió, evidencia de que el comportamiento no cambió (conteo y salida de pytest) y deuda restante.
Pregunta antes de commit (`refactor: <qué>`).
