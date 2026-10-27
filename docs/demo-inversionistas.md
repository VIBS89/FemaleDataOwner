# Guion de demo · ConverData (10 minutos)

Modo demo: servidores simulados con **metadatos** de prueba (VBank de la propuesta + BancosSQL); ningún dato real.

```bash
CONVERDATA_DEMO=1 docker compose up --build      # http://localhost:3000
```
Usuarios (contraseña `demo`): `demo` (administrador), `analista` (consulta, sin RRHH), `responsable` (responsable de datos).

| # | Quién | Qué hacer | Qué mostrar |
|---|---|---|---|
| 1 | `demo` | Entrar → Administración → **Descubrir esquemas** | El agente lee solo la estructura de 4 servidores (Producción, QA, DWH, desarrollo): 10 BDs, ~49 objetos, entidades entre BDs. Sin catálogo previo. |
| 2 | `analista` | Preguntar: *"Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital."* | Los pasos del agente en vivo → **ClientCode 96 %**, Producción y QA con aviso de diferencia, "Revisada por un responsable", regla BR-ONB-004, alternativas. **Ver ficha** y **Ver relacionadas**. |
| 3 | `analista` | *"¿Qué proceso llena la dimensión de clientes del DWH?"* | Linaje hacia el DWH y preguntas sugeridas. |
| 4 | `analista` | Catálogo | Solo ve las BDs que su login puede leer (RRHH no aparece): los permisos se heredan de SQL Server. |
| 5 | `analista` | *"¿Dónde está el puntaje de riesgo crediticio del cliente?"* → **Preguntar al responsable** | Confianza baja (~44 %): el agente no inventa y escala. Aparece en Mis solicitudes. |
| 6 | `responsable` | Curación → **Responder** (CategoriaRiesgo + descripción) | Se responde una vez; queda como conocimiento revisado. |
| 7 | `analista` | Repetir la pregunta del paso 5 | Ahora **~93 %**, "Revisada por un responsable". Mis solicitudes muestra la respuesta. **El agente aprende del experto.** |
| 8 | `demo` | Métricas | Adopción, % confirmadas, resueltas sin escalar, tiempo hasta encontrar el dato, brechas. En modo demo puede incluir actividad simulada (aviso visible). |

**Extra (MCP):** `.venv/Scripts/python scripts/mcp_stdio_probe.py` muestra a un cliente MCP real (como Claude Code) llamando a `discover`, `get_asset` y `list_business_rules` sobre el mismo catálogo; por HTTP, `/mcp` usa el `Bearer` de `/login`.

Mensajes clave: reduce la dependencia del conocimiento tribal; nadie ve más de lo que ya puede ver; los datos de clientes no salen del banco
(solo metadatos); cada recomendación muestra su evidencia y su confianza; el éxito se mide contra una línea base.
