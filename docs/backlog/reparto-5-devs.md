# Reparto del backlog on-premise entre 5 desarrolladores

> 2026-10-27. Parte del [backlog on-premise](on-premise.md) (42 historias, 194 puntos) y del [orden de desarrollo](../PLAN-desarrollo.md#7-orden-de-desarrollo-del-agente-y-su-mcp).
> Criterio: las historias que dependen una de otra las lleva **la misma persona**; los carriles se tocan entre sí solo por **interfaces ya existentes**
> (puertos en `src/converdata/`), no por archivos compartidos.

## 1. Estado real de partida
La demo (modo `CONVERDATA_DEMO=1`) ya recorre los 8 pasos del [guion](../demo-inversionistas.md) con **almacenamiento en archivos y memoria**
(`api/converdata_api/`: vault, auditoría `FileAuditSink`, curación, feedback → golden YAML) y `/mcp` montado (HU-16, 154 tests en verde).
Por eso muchas historias de E2, E3 y E6 no empiezan de cero: su trabajo pendiente es **llevarlas a SQL Server, a la identidad real y a producción**.
Lo que no existe todavía: persistencia en la BD `ConverData` (E1), AD, ingesta de fuentes (E5), Bedrock probado, instalación y piloto.

## 2. Carriles

| Dev | Carril | Historias | Puntos | Camino crítico |
|---|---|---|---|---|
| **1** | Persistencia en la BD `ConverData` | HU-04 → HU-05 → HU-06 → HU-09 → HU-07 → HU-08 → HU-39 | 36 | **Sí**: HU-05 desbloquea a 3 carriles |
| **2** | Identidad, API y MCP (+ pantallas de login y chat) | HU-11 → HU-12 → HU-10 → HU-13, HU-14 → HU-15 → HU-16 (cierre) → HU-19 | 31 | HU-14 necesita HU-09 y HU-20 en producción |
| **3** | Auditoría, observabilidad, instalación | HU-20 → HU-21 → HU-22 → HU-23 → HU-24, HU-01/02/03 (revisión), HU-37, HU-38 | 39 | HU-20 necesita HU-05; HU-37 va al final |
| **4** | Curación, aprendizaje y piloto | HU-28 → HU-29 → HU-30 → HU-31 → HU-32, HU-33, HU-40, HU-41 | 32 | HU-31 necesita HU-06; HU-41 cierra todo |
| **5** | Fuentes de conocimiento y calidad del agente | HU-34 → HU-35 → HU-36, HU-18 → HU-25 → HU-26 → HU-27 | 35 | HU-18/25/26 necesitan HU-06; HU-27 necesita HU-07 |

Los puntos son aproximados: no cuentan HU-16 (casi hecha), HU-17 (pendiente de decisión), HU-41 (cierre compartido) ni HU-42 (hecha), así que no suman exactamente los 194 del backlog.

### Dev 1 — Persistencia (dueño de `db/`, `memory/`, `catalog/store.py`, `bootstrap.py`)
- **HU-04** DDL completo (`estate`, `semantic`), **HU-05** validación en SQL Server 2025 (`SqlServerVectorStore`), **HU-06** escribir el catálogo con historial,
  **HU-09** arrancar el DiscoverFlow desde la BD, **HU-07** grafo en tablas `NODE`/`EDGE`, **HU-08** exportar a YAML, **HU-39** respaldo y restauración.
- Es una cadena estricta (cada una depende de la anterior), por eso es de una sola persona.
- **Bloqueo externo:** instancia de SQL Server 2025 de desarrollo (⚠️ S5). Sin ella, empezar por HU-04 y por pruebas contra Express.
- **Entrega temprana:** publicar el puerto `CatalogStore` y una BD de desarrollo compartida en cuanto HU-05 pase; los demás carriles trabajan con los adaptadores de archivos hasta entonces.

### Dev 2 — Identidad y API (dueño de `api/converdata_api/main.py`, `vault.py`, `connector.py`, `integration/mcp/`, `web/src/app/login`, `web/src/app/(app)/page.tsx`)
- **HU-11/12/10**: custodia en `SessionVault`, conexiones con la credencial del usuario y login por servidor. La versión de demo ya existe; falta el login real de SQL Server y quitar `host.docker.internal` del camino de producción.
- **HU-13** grupos y roles desde AD (⚠️ S10: acceso LDAP de solo lectura).
- **HU-14/15** API REST y feedback. Decisión previa: rutas actuales (`/discover`) frente a las de OP-04 (`/api/discover`); el proxy de Next ya añade `/api`, así que lo más barato es documentar la equivalencia.
- **HU-16** cierre del MCP: fijar `CONVERDATA_MCP_HOSTS` para IIS, límite de preguntas por minuto en `/mcp` y revisar el fallo de respuestas truncadas de `mcp 2.3.0` bajo uvicorn con el cliente Python (los tests en memoria pasan).
- **HU-19** límite de tokens por usuario y día.
- **Primer encargo, antes de cualquier ruta nueva:** partir `main.py` en `routers/` (uno por área). Es el archivo donde más chocarían los carriles 3, 4 y 5.
- **HU-17 (Chainlit)**: ya existe el chat web en Next.js; decidir con el Product Owner si HU-17 se sustituye por él. Mi recomendación: sustituirla y reescribir los criterios de aceptación sobre `web/`.

### Dev 3 — Auditoría, observabilidad e instalación (dueño de `audit/`, `observability/`, `scripts/`, `docs/specs/on-premise/OP-05,07`)
- **HU-20** auditoría fail-closed en SQL Server. Hoy existe `FileAuditSink` y `audit/sqlserver.py`; programar contra el puerto actual y cambiar el adaptador cuando HU-05 esté.
- **HU-21/22** logs JSON sin contenido y `/health/metrics`; **HU-23/24** scorecard, jobs de mantenimiento y regresión (HU-24 necesita el set de HU-33 del Dev 4).
- **HU-01/02/03**: revisar y cerrar las specs hechas el 2026-10-27 (OP-07, parches de OP-03 a OP-06, modelo de procesos en IIS). Quien instala debe validarlas.
- **HU-37/38** instalación en Windows Server y secretos de servicio; van al final porque dependen de HU-14, HU-18 y HU-35 (gMSA: ⚠️ S10).

### Dev 4 — Curación, aprendizaje y piloto (dueño de `api/converdata_api/curation.py`, `web/src/app/(app)/curacion`, `solicitudes`, `metricas`)
- **HU-28** reglas gestionadas, **HU-29** golden discovery, **HU-30** preguntar al responsable, **HU-31** vista Curación, **HU-32** brechas. La demo ya cubre HU-29 a HU-31 con archivos; falta persistirlas en la BD tras HU-06 y conectar la asignación de responsables a AD (HU-13).
- **HU-30** necesita el canal de notificación (⚠️ S12; hoy hay webhook de Teams opcional).
- **HU-33** set de evaluación con 50–80 preguntas reales (⚠️ S9: steward asignado). Es lo que hace creíbles las cifras de la demo; empezar ya, es trabajo de personas, no de código.
- **HU-40/41** línea base firmada (⚠️ S13) e informe del piloto; HU-41 es el cierre de todo y lo coordina esta persona con el líder técnico.

### Dev 5 — Fuentes de conocimiento y calidad del agente (dueño de `builder/`, `llm/`, `discovery/`, `evaluation/`, `knowledge/`)
- **HU-34** medir embeddings (4 combinaciones del plan §3), **HU-35** Bedrock de punta a punta (⚠️ S4: cuenta AWS), **HU-36** batería de inyección de prompt. Es una cadena corta y no depende de nadie: arranca el día 1.
- **HU-18** administración de ingesta en `ConverData-Builder` (necesita HU-03 y HU-06), luego **HU-25** diccionarios, **HU-26** documentos con redacción de PII (⚠️ S6: ubicación de los documentos) y **HU-27** linaje desde SSIS y SQL Agent (necesita HU-07 y acceso a `SSISDB` y `msdb`).
- Regla del plan: todo cambio de lógica se acepta solo si mejora el set de evaluación sin bajar otros tipos ni crear fugas.

## 3. Orden por sprint

| Sprint | Dev 1 | Dev 2 | Dev 3 | Dev 4 | Dev 5 |
|---|---|---|---|---|---|
| **0** (2–3 días) | Acordar puertos (`CatalogStore`, `AuditSink`, `VisibilityResolver`, `SessionVault`) y pedir la instancia SQL Server 2025 | Partir `main.py` en `routers/` | Cerrar la revisión de HU-01/02/03 | Convocar al steward y fijar canal (S9, S12) | Instalar `bge-m3`, arrancar HU-34 |
| **1** | HU-04, HU-05 | HU-11, HU-12, HU-10 | HU-21, HU-20 sobre el adaptador de archivos | HU-28, HU-29, empezar HU-33 | HU-34, HU-35 |
| **2** | HU-06, HU-09 | HU-14, HU-15 (con HU-20 listo) | HU-20 sobre SQL Server, HU-22 | HU-30, HU-33 | HU-36, HU-18 |
| **3** | HU-07, HU-08 | HU-13, HU-16 cierre, HU-19 | HU-23, HU-24 | HU-31, HU-32 | HU-25, HU-26 |
| **4** | HU-39, apoyo a HU-27 | Soporte de pantallas | HU-37, HU-38 | HU-40, ensayo del piloto | HU-27 |
| **5** | Estabilización | Estabilización | Estabilización | HU-41 piloto e informe | Ajustes de calidad |

## 4. Cómo evitar que choquen
1. **Contratos primero:** los puertos ya existen en `src/converdata/` (`audit/recorder.py`, `memory/base.py`, `catalog/store.py`, `identity/visibility.py`, `api/.../vault.py`). Nadie cambia una firma sin avisar; los adaptadores SQL sustituyen a los de archivos sin tocar a quien los usa.
2. **Archivos calientes:**
   - `api/converdata_api/main.py`: lo parte el Dev 2 en el sprint 0; después cada quien añade rutas solo en su `routers/<área>.py`.
   - `web/src/lib/api.ts` y `types.ts`: separar por área (`api/discover.ts`, `api/curation.ts`, `api/admin.ts`) antes del sprint 1, para que cada pantalla tenga un solo dueño.
   - `docs/PLAN-desarrollo.md` y `on-premise.md`: cada dev actualiza solo el estado de sus historias, en su propio PR.
3. **Un PR por historia**, con sus tests; el repo exige `pytest` en verde (154 hoy) y `tsc --noEmit` limpio. El repo aún no tiene commits: el líder técnico hace el primer commit antes de repartir y las ramas parten de ahí.
4. **Dependencias entre carriles = fechas, no esperas:** cada carril trabaja contra el adaptador de archivos y cambia al de SQL Server cuando Dev 1 publique HU-05 (sprint 1) y HU-06/HU-09 (sprint 2).

## 5. Riesgos y decisiones abiertas
| # | Qué | Quién decide | Afecta |
|---|---|---|---|
| 1 | Instancia SQL Server 2025 de desarrollo (S5) | Infraestructura | Dev 1 y, por cascada, a Dev 2, 3, 4 y 5 |
| 2 | HU-17: Chainlit frente al chat Next.js ya hecho | Product Owner | Dev 2 (8 puntos) |
| 3 | Rutas `/discover` frente a `/api/discover` | Dev 2 con el líder técnico | MCP, chat, scripts de instalación |
| 4 | LDAP de solo lectura y gMSA (S10) | Seguridad / AD | HU-13, HU-31, HU-38 |
| 5 | Cuenta AWS con Bedrock (S4) y documentos fuente (S6) | Nube / Gerencia de Datos | HU-35, HU-26, HU-27 |
| 6 | Steward asignado (S9) y línea base (S13) | Gerencia de Datos | HU-33, HU-40, HU-41 |
| 7 | `BancosSQL.zip` (13 MB) está versionado en `main`; sacarlo o usar Git LFS antes del primer commit | Líder técnico | Todos |
