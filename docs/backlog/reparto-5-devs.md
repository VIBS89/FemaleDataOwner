# Reparto del trabajo pendiente entre 5 desarrolladores

> Actualizado el 2026-11-17. Sustituye al reparto del 2026-10-27, que era anterior a la arquitectura simplificada
> ([PRD §13](../PRD.md#13-decisiones-y-preguntas-abiertas), decisiones 9–16) y repartía historias que ya están hechas.
> Parte del estado del [backlog on-premise §1](on-premise.md#estado-al-2026-11-17) y del orden del
> [plan de desarrollo §3](../PLAN-desarrollo.md#3-próximos-pasos-en-orden).
>
> Criterio, el mismo de antes: las historias que dependen una de otra las lleva **la misma persona**, y los carriles se tocan
> entre sí solo por **interfaces ya existentes** (puertos en `src/discovery_data_agent/`), no por archivos compartidos.

## 1. De dónde se parte
Lo que el reparto anterior daba por pendiente y ya está hecho:

| Entonces | Hoy |
|---|---|
| Persistencia en SQL Server (carril del Dev 1, camino crítico) | Hecha: con `DISCOVERY_DATA_AGENT_DB` todo el estado vive en la BD `DiscoveryDataAgent` (catálogo con historial, conocimiento, curación, inventario y auditoría); migraciones `001` y `002`; SQL Server 2016+, sin `VECTOR` ni tablas de grafo |
| HU-07, grafo en tablas `NODE`/`EDGE` | Retirada: el grafo se arma en memoria |
| HU-17, Chainlit | Sustituida por la web Next.js, ya construida |
| HU-18, servicio `DiscoveryDataAgent-Builder` | Es el comando `discovery-data-agent catalog build --db`; falta programarlo como tarea |
| HU-34, medir embeddings | Medido: no mejoran el acierto. El canal se retiró del código |
| Auditoría, curación, feedback y golden en archivos | En la BD; los archivos quedan solo para desarrollo y el modo demo |
| Rutas `/discover` frente a `/api/discover` | Cerrado: valen las del código (PRD §13, decisión 15) |
| `VisibilityResolver`, `SqlServerVectorStore` | Eliminados |

Lo que queda son 16 historias (76 puntos nominales; seis ya están a medias, así que el trabajo real es menor) y las deudas
de [calidad bancaria §5](../calidad-bancaria.md#5-lo-que-todavía-no-está-resuelto). Siete historias no se pueden cerrar sin el
banco o un tercero (⛔).

| Estado | Historias |
|---|---|
| 🟡 A medias | HU-18 (falta la tarea programada), HU-23 (falta `discovery-data-agent metrics report`), HU-24 (faltan las tareas), HU-25 (falta Excel), HU-32 (falta el reporte por dominio), HU-36 (falta repetirla con el LLM real) |
| ⏳ Sin empezar, sin dependencias externas | HU-26, HU-37 (scripts), HU-39 |
| ⛔ Dependen del banco o de terceros | HU-13 (LDAP), HU-27 (SSISDB y msdb), HU-33 (preguntas reales y steward), HU-35 (cuenta AWS), HU-38 (gMSA y certificados), HU-40, HU-41 |

## 2. Carriles

| Dev | Carril | Historias | Puntos | Empieza hoy con | Espera a |
|---|---|---|---|---|---|
| **1** | Instalación y operación (bloque F) | HU-37, HU-18, HU-24, HU-39, HU-38 | 23 | Scripts de `deploy/windows/` y SQL Server en la CI | Windows Server del piloto, gMSA (⚠️ S10) |
| **2** | Métricas y auditoría (bloque D) | HU-23, HU-32, HU-40 | 11 | `discovery-data-agent metrics report` y vistas SQL | Gestor de requerimientos para la línea base (⚠️ S13) |
| **3** | Fuentes de conocimiento (bloque E) | HU-25, HU-26, HU-27 | 21 | Excel y redacción de datos personales | Documentos del dominio, SSISDB y msdb (⚠️ S6) |
| **4** | Calidad del agente y LLM (bloque G) | HU-35, HU-36, HU-33 | 11 | Deudas de orden del descubrimiento y recarga del índice | Cuenta AWS (⚠️ S4), steward (⚠️ S9) |
| **5** | API, identidad y web | HU-13, y el piloto HU-41 con el líder técnico | 10 | Partir `main.py`, capas de la API, decisiones abiertas 7 a 9 | LDAP de solo lectura (⚠️ S10) |

Los puntos son los nominales del backlog. Los carriles 2, 4 y 5 llevan menos historias porque cargan con las deudas
técnicas, que no tienen puntos asignados.

### Dev 1 — Instalación y operación (dueño de `deploy/`, `.github/`, `requirements/`, `db/discovery_data_agent/`, `docs/specs/on-premise/OP-07`)
- **HU-37** scripts PowerShell: IIS con HttpPlatformHandler para la web y la API, firewall, certificado y verificación. Hoy solo hay `docker compose`.
- **HU-18** y **HU-24**: tareas programadas del refresco (`catalog build --db`, con `DISCOVERY_DATA_AGENT_BUILDER_HOSTS`), de la purga (`audit purge`, rol `discovery_data_agent_maintenance`) y de la evaluación semanal (`eval gate`).
- **HU-39** respaldo y restauración de la BD `DiscoveryDataAgent` en otra instancia, con el servicio arrancando contra ella.
- **HU-38** login de metadatos y Bedrock sin claves de larga duración (⛔ gMSA, IAM Roles Anywhere).
- Deudas suyas: SQL Server en la CI (las pruebas de BD hoy se omiten ahí), probar el DDL en la versión de la instancia del piloto (se probó en 2022, no en 2016), y mantener los bloqueos de dependencias y los digests de las imágenes ([`requirements/README.md`](../../requirements/README.md)).
- Es el único que añade migraciones (`003_…`): quien necesite un cambio de esquema se lo pide.

### Dev 2 — Métricas y auditoría (dueño de `audit/`, `observability/`, el reporte de métricas, `web/src/app/(app)/metricas`)
- **HU-23** `discovery-data-agent metrics report` y vistas SQL del scorecard sobre el esquema `audit`; **HU-32** brechas abiertas y cerradas por dominio.
- **HU-40** línea base de las cuatro métricas de negocio, con la Gerencia de Datos (⛔ S13).
- Deudas suyas: la fecha de un registro de auditoría la fija quien lo inserta (columna `recorded_at`, migración con el Dev 1); decidir con Seguridad qué lecturas se auditan además de las preguntas (PRD §13, pregunta 8); la alerta de auditoría en el monitoreo.

### Dev 3 — Fuentes de conocimiento (dueño de `builder/`, `api/discovery_data_agent_api/pii.py`, la ingesta de documentos, `knowledge/`)
- **HU-25** diccionario en Excel (el CSV ya funciona y escribe en la BD).
- **HU-26** documentos con redacción de datos personales (Presidio). El detector actual tiene seis tipos (DUI, NIT, correo, teléfono, IBAN, tarjeta) y no reconoce nombres ni direcciones; de él depende también la plantilla de las confirmaciones.
- **HU-27** linaje desde SSIS y SQL Server Agent (⛔ acceso a `SSISDB` y `msdb`).
- La medición con el glosario de prueba (`tests/fixtures/bancos/eval/reportes.yaml`) da la referencia: 16 % solo con catálogo, 60 % con conocimiento. Repetirla con los documentos reales es parte de su entrega.

### Dev 4 — Calidad del agente y LLM (dueño de `discovery/`, `flows/discover.py`, `llm/`, `evaluation/`, `tests/fixtures/*/eval/`)
- **HU-35** Bedrock de punta a punta (⛔ cuenta AWS); **HU-36** repetir la compuerta con el modelo real, sobre todo `inyeccion` y `guardas`, y ampliarla con Seguridad (⚠️ S7).
- **HU-33** set de 50–80 preguntas reales validadas por un experto (⛔ steward). Los 89 casos de hoy los escribió el equipo.
- Deudas suyas: los dos fallos que quedan en los sets (B14 y eng-06: una entidad con un calificativo que otra tabla sí conoce); actualizar solo la parte del índice que cambia en vez de reconstruirlo en cada escritura de curación.
- Es el único que regenera las líneas base (`eval gate --write-baseline`). Regla del plan: un cambio de lógica se acepta solo si la compuerta no baja, y se comprueba con preguntas que no se usaron para ajustarlo.

### Dev 5 — API, identidad y web (dueño de `api/discovery_data_agent_api/main.py`, `runtime.py`, `curation.py`, `vault.py`, `integration/mcp/`, `web/`)
- **Primer encargo:** partir `main.py` en `routers/` (uno por área). Sigue siendo el archivo donde más chocan los carriles 2, 3 y 4.
- Deudas suyas: llevar la orquestación de votos (`record_feedback`, `steward_golden`) a un caso de uso de `discovery_data_agent.application` y extender `tests/test_architecture.py` a `api/discovery_data_agent_api`; que la CLI use `open_stores`; emitir el token de sesión en el cuerpo del login solo a quien lo pide.
- Implementar lo que el banco decida en las preguntas abiertas 7 (qué ve un responsable dentro de sus dominios) y 9 (validación del login para dar un rol por su nombre).
- **HU-13** roles desde grupos de Active Directory (⛔ LDAP de solo lectura); sustituye a la lista de responsables por login.
- **HU-41** piloto de 8 semanas e informe: lo coordina con el líder técnico; el soporte de pantallas durante el piloto es suyo.

## 3. Orden
El calendario del backlog (seis sprints desde el 2026-11-02) hay que volver a confirmarlo (⚠️ S2): se hizo antes de la
simplificación. Mientras tanto, el orden es por lo que desbloquea cada cosa.

| Etapa | Dev 1 | Dev 2 | Dev 3 | Dev 4 | Dev 5 |
|---|---|---|---|---|---|
| **1 · Sin dependencias externas** | Scripts de HU-37, tareas de HU-18 y HU-24, SQL Server en la CI | HU-23, HU-32, `recorded_at` | HU-25 (Excel), conector y redacción de HU-26 con documentos de prueba | Fallos B14 y eng-06, recarga parcial del índice, batería de HU-36 en modo determinista | Partir `main.py`, capas de la API, token de sesión |
| **2 · Cuando llegue lo del banco** | Validar los scripts en el Windows Server del piloto, HU-39, HU-38 | HU-40 | HU-26 con los documentos reales, HU-27 | HU-35, HU-36 con Bedrock, HU-33 | HU-13, decisiones 7 a 9 |
| **3 · Piloto** | Operación y respaldo | Scorecard del piloto | Ingesta del dominio piloto | Regresión semanal con el set real | HU-41 |

Lo que hay que pedir al banco desde el primer día, porque es lo que más tarda: la cuenta AWS con Bedrock (S4), el steward y
las preguntas reales (S9), los documentos y el acceso a SSISDB (S6), el servidor con sus gMSA y LDAP (S10) y el gestor de
requerimientos para la línea base (S13).

## 4. Cómo evitar que choquen
1. **Contratos primero.** Los puertos están en `src/discovery_data_agent/`: `catalog/store.py` (`CatalogRepository`, `InventoryStore`), `curation.py` (`KnowledgeWriter`, `CurationRepository`), `audit/recorder.py`, `memory/base.py`, `metadata/ports.py`. Nadie cambia una firma sin avisar; cada puerto tiene su adaptador de SQL Server y su adaptador de archivos, pero las pruebas de contrato contra los dos solo existen para `CurationRepository` (`tests/test_curation.py`); las del catálogo solo corren contra SQL Server.
2. **Archivos calientes.**
   - `api/discovery_data_agent_api/main.py`: lo parte el Dev 5 en la etapa 1; después cada quien añade rutas solo en su `routers/<área>.py`.
   - `web/src/lib/api.ts` y `types.ts`: separar por área antes de que dos carriles toquen la web. Tras cambiar una ruta se pasa el subagente `verificador-contrato-web-api`.
   - `db/discovery_data_agent/`: solo el Dev 1 añade migraciones, numeradas y sin editar las ya aplicadas.
   - `tests/fixtures/*/eval/` y sus `baseline.yaml`: solo el Dev 4.
   - `requirements/*.lock` y `web/package-lock.json`: se regeneran en un PR propio, nunca mezclados con cambios de lógica.
   - `docs/PLAN-desarrollo.md` y `on-premise.md`: cada dev actualiza solo el estado de sus historias, en su propio PR.
3. **Un PR por historia**, con sus pruebas. La CI exige `pytest`, la compuerta `eval gate`, tipos, lint y build de la web, y el análisis de dependencias. Las pruebas contra SQL Server no corren en la CI todavía: quien toque `storage/`, `audit/` o `db/` las corre a mano con `DISCOVERY_DATA_AGENT_TEST_DB` antes de pedir revisión.
4. **Revisión antes del commit.** Tras tocar `identity/`, `audit/`, `storage/`, `curation.py` o `api/`, pasar los subagentes `revisor-seguridad-datos` y `revisor-arquitectura-specs`; tras tocar `discovery/` o los sets, `evaluador-descubrimiento`. En las sesiones del 2026-11-16 y 17 encontraron fallos que las pruebas no veían.
5. **Dependencias entre carriles = fechas, no esperas.** Cada carril trabaja contra el adaptador de archivos o contra una BD `DiscoveryDataAgent` local (`discovery-data-agent db migrate`) y no espera al servidor del piloto.

## 5. Riesgos y decisiones abiertas
| # | Qué | Quién decide | Afecta |
|---|---|---|---|
| 1 | Calendario y capacidad: el plan de seis sprints es anterior a la simplificación (S2, S3) | Líder técnico y Gerencia de Datos | Todos |
| 2 | Cuenta AWS con Bedrock (S4) | Nube | HU-35, HU-36, HU-38, objetivo O8 |
| 3 | Steward asignado, preguntas reales (S9) y línea base (S13) | Gerencia de Datos | HU-33, HU-40, HU-41 |
| 4 | Documentos del dominio piloto y acceso a SSISDB y msdb (S6) | Gerencia de Datos | HU-26, HU-27 |
| 5 | Windows Server del piloto, gMSA y LDAP de solo lectura (S10) | Plataformas y Seguridad | HU-37, HU-38, HU-13 |
| 6 | Preguntas abiertas 7, 8 y 9 del PRD: qué ve un responsable en sus dominios, qué lecturas se auditan, cómo se valida el login para dar un rol | Seguridad y Gerencia de Datos | Dev 5, Dev 2 |
| 7 | Guardrails de Bedrock y revisión de la batería de inyección (S7) | Seguridad | HU-36 |
| 8 | `BancosSQL.zip` (13 MB) sigue versionado; sacarlo del repositorio o pasarlo a Git LFS | Líder técnico | Todos |
| 9 | La rama `feat/congruencia-y-persistencia` no está publicada: hasta que se integre en `main`, los carriles no tienen base común | Líder técnico | Todos |
