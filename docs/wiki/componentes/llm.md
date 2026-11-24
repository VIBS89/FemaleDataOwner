# Gateway de modelos (LLM)

Actualizado el 2026-11-22.

**Para qué sirve.** Es el único punto por el que DiscoveryDataAgent llama a un modelo de lenguaje. Resuelve cada rol (`planner`, `fast`,
`judge`) al proveedor y modelo de `config/models.yaml`, aplica la guarda de residencia de datos, cambia a un proveedor de respaldo
ante errores transitorios, abre un circuito ante fallos repetidos e informa el consumo de tokens. Los nodos del DiscoverFlow y el
enriquecimiento del Catalog Builder lo usan sin saber qué proveedor hay detrás.

**Lo esencial**
- Sin `config/models.yaml` (o sin `DISCOVERY_DATA_AGENT_MODELS` en la API) todo es determinista y el flujo responde igual.
- Proveedores: `nvidia_nim`, `openai`, `anthropic` (Claude), `bedrock` y `ollama` (este solo con `environment: local`, regla
  de código). Cada rol elige proveedor y modelo en `models.yaml`; el respaldo puede ser cualquier otro proveedor activo.
- **Probado en vivo solo NVIDIA NIM** (2026-11-22, API alojada). OpenAI y Claude están probados sin red, con el SDK real y un
  transporte local; falta una llamada real con clave.
- Con `data_mode: real`, el gateway no arranca si algún rol o el respaldo puede enviar datos a un proveedor `allowed_data: test`.
- Respaldo solo ante throttling, indisponibilidad o timeout; nunca por errores de contenido.
- Circuito por proveedor: 3 fallos transitorios en 60 s lo abren 5 min.
- Lo que devuelve el modelo nunca se usa sin validar: ids contra la lista, narrativa contra la respuesta, texto sin enlaces ni HTML.
- **Bedrock no se ha probado de punta a punta**: solo con un constructor falso en las pruebas.

Diagramas: [flujo de descubrimiento](../../architecture/flujo-descubrimiento.html) ·
[controles de calidad bancaria](../../architecture/controles-calidad-bancaria.html).

## Responsabilidades
- Cargar y validar `models.yaml` (roles, proveedores, residencia, ambiente).
- Construir el chat model de cada proveedor de forma perezosa y cachearlo.
- Enrutar, reintentar en el respaldo y abrir el circuito.
- Etiquetar qué `proveedor:modelo` atendió cada rol, para `audit_step.model`.
- Informar tokens de entrada y salida al gancho de uso (tope diario y métricas).
- Ofrecer los nodos con salida estructurada: intención, reranking, narrativa y enriquecimiento.

## Piezas internas
| Pieza | Archivo | Qué hace |
|---|---|---|
| `ModelsConfig`, `ProviderConfig`, `RoleConfig`, `FallbackConfig`, `CircuitConfig` | `src/discovery_data_agent/llm/factory.py` | Esquema de `models.yaml` |
| `load_models` | `src/discovery_data_agent/llm/factory.py:91` | Lee el YAML; `DISCOVERY_DATA_AGENT_ENV` sobrescribe `environment` |
| `build_nim_chat`, `build_bedrock_chat`, `build_openai_chat`, `build_ollama_chat` | `src/discovery_data_agent/llm/factory.py` | Constructores LangChain por proveedor |
| `build_anthropic_chat`, `ClaudeChat` | `src/discovery_data_agent/llm/factory.py`, `src/discovery_data_agent/llm/anthropic_chat.py` | Claude con el SDK oficial de Anthropic: `messages.parse` para la salida estructurada, `effort`, rechazo como `LLMRefused` |
| `LLMGateway` | `src/discovery_data_agent/llm/gateway.py:151` | Validación, rutas, invocación, respaldo, etiquetas, uso |
| `RoutedChat` | `src/discovery_data_agent/llm/gateway.py:117` | Imita `invoke` y `with_structured_output` de LangChain |
| `CircuitBreaker` | `src/discovery_data_agent/llm/gateway.py:66` | Circuito por proveedor |
| `classify_error` | `src/discovery_data_agent/llm/gateway.py:48` | Decide si un error es transitorio |
| `estimate_usage` | `src/discovery_data_agent/llm/gateway.py:103` | Tokens del proveedor o ~4 caracteres por token |
| `LlmIntentClassifier`, `LlmReranker`, `LlmNarrator` | `src/discovery_data_agent/llm/nodes.py` | Puertos del DiscoverFlow con LLM |
| `LlmEnricher` | `src/discovery_data_agent/llm/nodes.py:116` | Descripciones sugeridas en el build |
| Ensamblado | `src/discovery_data_agent/bootstrap.py:96` | Conecta los nodos según los roles declarados |
| `discovery-data-agent llm smoke` | `src/discovery_data_agent/cli.py:458` | Prueba cada rol contra su proveedor |

## Roles de modelo
| Rol | Lo usa | Si falta en `models.yaml` |
|---|---|---|
| `planner` | `intent` y `rerank` del DiscoverFlow; `LlmEnricher` del build | Reglas y relevancia por cobertura |
| `fast` | `respond` (narrativa para una persona de negocio), `grade` (`LlmQueryExpander`, reformula si la búsqueda cubre poco) y la guía sin candidatos (`LlmGuide`); el enriquecimiento del build si falta `planner` | `TemplateNarrator`; sin reformulación; sin guía |
| `judge` | Nadie: el nodo `review` lo anota como rol, pero no hay implementación conectada | Chequeos deterministas |
| `embed` | Retirado: se ignora con un aviso; en qa/prod la API no arranca si aparece | — |

`config/models.example.yaml` usa `fast` con `nvidia/nemotron-3-ultra-550b-a55b`, `enrich` con `nvidia/nemotron-3.5-bolt-e4b` y `bolt` como respaldo (NIM alojado) y trae comentados los
bloques para Claude, OpenAI y Bedrock; `config/models.local.example.yaml` y el
`config/models.yaml` local usan Ollama y declaran también `judge`.

## Cómo funciona
1. **Carga** (`load_models`): YAML → `ModelsConfig`. `DISCOVERY_DATA_AGENT_ENV` gana a `environment`. Roles retirados se descartan.
2. **Validación** al crear el gateway (`gateway.py:169`), para cada rol y su respaldo:
   - el proveedor debe estar `enabled`;
   - `ollama` solo con `environment: local`;
   - con `data_mode: real`, el proveedor debe tener `allowed_data: real` (si no, `ResidencyError`).
   Un proveedor no listado en `providers` vale `enabled: true` y `allowed_data: test`.
3. **Rutas** (`gateway.py:186`): el primario del rol y, si hay `fallback` de otro proveedor activo con modelo para ese rol, el respaldo.
4. **Invocación** (`gateway.py:227`), por cada ruta:
   - circuito abierto → se salta;
   - error no transitorio → se relanza sin probar el respaldo;
   - error transitorio → cuenta en el circuito; si es la última ruta o el tipo no está en `fallback.on`, `AllProvidersFailed`;
   - éxito → cierra la cuenta del circuito, anota la etiqueta (con " (respaldo)" si no fue el primario) e informa el uso.
5. **En el DiscoverFlow**, cada nodo captura cualquier excepción y usa su respaldo determinista, con `error = fallback:<tipo>` en el
   paso auditado. Ver [descubrimiento](descubrimiento.md#modo-determinista-frente-a-modo-con-llm).
6. **Tope diario** (API): el gancho `usage_hook` suma tokens al usuario del contexto (`TokenLedger`) y a `/health/metrics`. Agotado,
   la API rechaza (429) o, con `DISCOVERY_DATA_AGENT_TOKEN_LIMIT_MODE=deterministic`, usa el mismo catálogo sin LLM.

### Qué se envía al modelo y qué no
| Nodo | Se envía | No se envía |
|---|---|---|
| intent | Pregunta y hasta 5 entradas del historial que manda el cliente, entre `<datos>` | Usuario, roles, `visible_ids`, catálogo |
| rerank | Pregunta; hasta 25 candidatos **ya filtrados por visibilidad**: `id` (`asset_key`), tipo, descripción y su fuente, ids de reglas, evidencias (`tipo:fuente`) | Ubicaciones, servidores, responsables, textos de reglas |
| respond | Pregunta; candidatos (`asset_key`, confianza, `why`, descripción), alternativas completas, `knowledge_gap` | Relaciones, ubicaciones, responsables, reglas |
| enrich (build) | Por tabla: nombre completo, tipo, PK, FKs, columnas con nombre y tipo | Valores de datos, filas, descripciones existentes |

Nunca viajan credenciales, hosts ni valores de datos (el catálogo no los tiene: `FORBIDDEN_KEYS` en
`src/discovery_data_agent/models/catalog.py:13`). La pregunta del usuario sí viaja: por eso la guarda de residencia.

### Tope de tokens
- **Por llamada**: `max_tokens` del rol (`max_completion_tokens` en NIM, `max_tokens` en Bedrock, `num_predict` en Ollama). En los
  ejemplos, `fast` = 400 y `planner` = 1024 (NIM) o sin tope (Ollama local).
- **Por entrada**: la API limita la pregunta a 2000 caracteres y el historial a 10 textos; el nodo `intent` usa los 5 últimos.
- **Por día y usuario**: `DISCOVERY_DATA_AGENT_TOKEN_LIMIT` (0 = sin tope). Con salida estructurada el proveedor no informa el uso y se estima.

### Guardas sobre la salida
- **Prompts**: el contenido del catálogo y el texto del usuario van entre `<datos>` y `</datos>`, y se quitan esos delimitadores si
  vienen dentro (`nodes.py:33`). El sistema dice que no se sigan instrucciones de ahí ni se escriban enlaces, correos ni HTML.
- **Intención**: salida Pydantic `IntentResult`; confianza < 0,6 → aclaración.
- **Rerank**: `RerankScore.relevance` acotada a 0..1; ids desconocidos o repetidos se descartan; el `why` se corta a una línea de
  240 caracteres y se vacía si trae enlaces, HTML o correos (`discovery/engine.py:488`).
- **Narrativa**: se rechaza si nombra objetos fuera de la respuesta o trae enlaces, HTML o correos; entonces va la plantilla.
- **Enriquecimiento**: solo se aplica a columnas y tablas que existen y que no tienen descripción; texto cortado a 500/300 caracteres;
  queda como `generated`.

## Contratos y datos
- `RoutedChat.invoke(messages)` devuelve lo que devuelva el modelo LangChain (un mensaje o el objeto Pydantic pedido).
- `gateway.labels`: vista viva rol → `proveedor:modelo` (o el primario si aún no hubo llamada). La usa `audit_step.model`.
- Errores: `GatewayConfigError` (configuración), `ResidencyError` (residencia), `AllProvidersFailed` (sin proveedor disponible),
  `MissingCredential` (falta la clave del proveedor), `LLMRefused` (Claude declinó la petición; es un error de contenido).
- Salidas estructuradas: `IntentResult` (`models/intent.py`), `RerankResult` (`discovery/ports.py`), `EnrichmentBatch` (`llm/nodes.py`).

## Configuración
`config/models.yaml` (fuera de git; plantillas `config/models.example.yaml` y `config/models.local.example.yaml`).

| Clave | Efecto |
|---|---|
| `environment` | `local` permite Ollama; `DISCOVERY_DATA_AGENT_ENV` la sobrescribe |
| `data_mode` | `real` activa la guarda de residencia; obligatorio en qa/prod (`production_violations`) |
| `providers.<p>.enabled`, `allowed_data` | Activación y qué datos puede recibir |
| `providers.nvidia_nim.base_url`, `api_key_env`, `timeout_s` | `null` = API alojada de NVIDIA; clave en `NVIDIA_API_KEY` por defecto |
| `providers.openai.base_url`, `api_key_env`, `timeout_s` | `null` = API de OpenAI; con una URL, un servidor compatible. Clave en `OPENAI_API_KEY` por defecto |
| `providers.anthropic.api_key_env`, `base_url`, `timeout_s` | Clave de la API de Anthropic. Sin `api_key_env`, el SDK resuelve la credencial del entorno (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` o un perfil) |
| `providers.bedrock.region` | Región; por defecto `us-east-1` |
| `roles.<rol>` | `provider`, `model`, `temperature`, `max_tokens`, `reasoning` y `num_ctx` (solo Ollama), `effort` (OpenAI y Claude), `refusal_fallback` (solo Claude) |
| `fallback` | `provider`, `models` por rol, `on` (tipos de error) |
| `circuit` | `errors`, `window_s`, `open_s` |

En la API: `DISCOVERY_DATA_AGENT_MODELS` (ruta del archivo; si no existe, modo determinista), `DISCOVERY_DATA_AGENT_TOKEN_LIMIT`,
`DISCOVERY_DATA_AGENT_TOKEN_LIMIT_MODE`, `DISCOVERY_DATA_AGENT_ENV`.

## Pruebas que lo cubren
- `tests/test_llm_providers.py` (15 pruebas): OpenAI y Claude por configuración y como terceros para la residencia; parámetros
  de cada constructor; petición real del SDK de Anthropic contra un transporte local (esquemas de intención y orden,
  `effort`, respaldo ante rechazo, sin `temperature`); rechazo y salida cortada como errores de contenido; clasificación de
  las excepciones reales de los dos SDK.
- `tests/test_llm_gateway.py` (21 pruebas): enrutado a NIM, cambio a Bedrock por configuración, residencia, respaldo solo ante
  transitorios, circuito, clasificación de errores, caída total → determinista, timeout de NIM, Ollama solo en local, `DISCOVERY_DATA_AGENT_ENV`,
  gancho de uso.
- `tests/test_llm_guards.py`: el reranker no añade candidatos; narrativa con objetos ajenos reemplazada; fallo del modelo → respaldo.
- `tests/test_prompt_injection.py` y suites `inyeccion` y `guardas` de `discovery-data-agent eval gate` (`tests/test_gate.py`).
- `api/tests/test_api.py`: tope diario, uso atribuido al usuario, modo determinista con el tope agotado.

## Modelos por proveedor
- **NVIDIA NIM (API alojada)**, comparados el 2026-11-23 los 13 modelos generativos con las llamadas reales del chat, a través del gateway
  (sustituye a la medición del 2026-11-22, que daba por correctos a `minimax-m3.1-flash` y otros con otra carga):

  | Modelo | Resultado | Hit@1 en reportes |
  |---|---|---|
  | `nvidia/nemotron-3.5-bolt-e4b` | **Elegido para `enrich`** (y para `fast` hasta el 2026-11-24): 6 de 6 correctas, 1,2 s de media | 52 % (p50 de 2 s) |
  | `nvidia/nemotron-3-ultra-550b-a55b` | 5 de 6, 5–8 s por llamada; reformula con más detalle, pero bajo carga agota el tiempo y el circuito del gateway lo desconecta | 36 % |
  | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Solo funciona pidiendo JSON en el mensaje (rechaza `guided_json`); 5 s y con timeouts | — |
  | `nemotron-3.5-lightning-30b-a3b`, `nemotron-3-nano-omni-30b-a3b-reasoning` | No sirven hoy: rechazan `guided_json` y no devuelven JSON por mensaje | — |
  | `mistral-large-4`, `kimi-k3.1-pro`, `muse-glimmer-30b`, `step-5-preview`, `gemma-4-31b-it`, `glm-5.3-flash`, `minimax-m3.1-flash` | No sirven hoy: agotan el tiempo | — |
  | `gemma-3-12b-it` | No sirve: 404 | — |

  Repetido el 2026-11-24 (detalle en F16): `fast` pasa a `nvidia/nemotron-3-ultra-550b-a55b` sin razonamiento (84 % de Hit@1 en
  reportes con conocimiento, frente a 80 % de `bolt`, a ~3 s por respuesta) con `bolt` de respaldo; el gateway apaga el
  razonamiento en NIM salvo `reasoning: true`, porque con él la redacción volvía vacía; `enrich` sigue en `bolt`, que describe más columnas.

  Referencia con Claude Sonnet 5.5: 68 % de Hit@1 en reportes. Todas las llamadas pasan por el gateway y no hay uso directo de un
  proveedor fuera de `src/discovery_data_agent/llm/`: el chat, la reformulación y el refresco del catálogo usan el perfil que elige el
  administrador en pantalla.

  Que un modelo devuelva salida válida no basta. En la evaluación de descubrimiento (58 casos, BancosSQL), usar estos modelos
  para intención y orden **baja el acierto**: Hit@1 62,7 % con `nemotron-3.5-bolt-e4b` (p50 6,2 s) y 64,7 % con
  `nemotron-3-ultra-550b-a55b` (p50 39 s), frente a 98,0 % sin modelo. Con el modelo solo en la narrativa (rol `fast`, sin
  `planner`) se mantiene 98,0 % con p50 de 0,9 s: es lo que trae el ejemplo.

  `openai/gpt-oss-20b`, el modelo anterior del ejemplo, ya no está en el catálogo de la cuenta. El catálogo cambia: listar con
  `GET /v1/models` y probar con `discovery-data-agent llm smoke` antes de cambiar un modelo.
- **Claude (`anthropic`)**: el modelo se escribe tal cual en el rol (`claude-opus-5-5`, `claude-haiku-5-5`…). Los modelos
  actuales rechazan `temperature` (el adaptador no la envía) y piensan siempre: la profundidad se regula con `effort`, y el
  pensamiento cuenta dentro de `max_tokens` (sin valor en el rol, 16 000). Con `refusal_fallback: true`, ante un rechazo por
  política la API repite la petición en otro modelo de Claude; solo lo admiten algunos modelos, y con `data_mode: real` el
  gateway no arranca si un rol lo tiene (la petición la atendería un modelo que la configuración no nombra).
- **OpenAI (`openai`)**: `ChatOpenAI` con `max_completion_tokens` y `reasoning_effort`. Los modelos de razonamiento no admiten
  `temperature`: no ponerla en el rol.
- Los extras `openai` y `anthropic` están en `requirements/dev.lock`, no en `runtime.lock`: la imagen de la API no los trae.

## Estado real de Bedrock
- `build_bedrock_chat` usa `ChatBedrockConverse` con `model`, `region_name`, `temperature` y `max_tokens`. Nada más.
- **Sin probar de punta a punta**: la única prueba (`test_pasar_a_bedrock_es_solo_configuracion`) sustituye el constructor por un
  modelo falso; el código real de Bedrock no se ejecuta en ninguna prueba. Pendiente HU-35 (proxy corporativo, IAM Roles Anywhere,
  suites `inyeccion` y `guardas` con el modelo real).
- **`timeout_s` no se aplica a Bedrock**: solo `build_nim_chat` lo pasa (`factory.py:118`). Un Bedrock lento depende de los tiempos
  por defecto de boto3 antes de contar como timeout para el respaldo.
- Las credenciales salen de la cadena por defecto de AWS; el código no configura IAM Roles Anywhere ni el proxy.
- Para usarlo con datos reales hay que declarar `allowed_data: real` en `providers.bedrock` (el valor por defecto es `test`).

## Límites conocidos y deuda
Ver [deuda técnica](../deuda-tecnica.md).
- Los puertos `QueryExpander` (C) y `Reviewer` (B, rol `judge`) no tienen implementación con LLM.
- `reasoning` solo se aplica a Ollama; `effort` solo a OpenAI y Claude. Los demás proveedores los ignoran.
- OpenAI y Claude no se han llamado con una clave real. `timeout_s` sí se aplica a los dos.
- Una clave que falta no se detecta al arrancar: los clientes se crean en la primera llamada, el paso queda como
  `fallback:MissingCredential` y la respuesta sale en modo determinista. `discovery-data-agent llm smoke` lo detecta.
- El respaldo conserva `temperature` y `max_tokens` del rol, pero no `effort` ni `refusal_fallback`.
- El uso de tokens se estima con salida estructurada.
- El gateway del enriquecimiento del build se crea aparte, sin gancho de uso: sus tokens no se cuentan.
- La aclaración que devuelve el modelo se muestra sin la guarda de texto (ver
  [seguridad](seguridad-auditoria.md#fallos-encontrados-al-revisar-el-código)).
- El circuito y la caché de modelos viven en memoria; cada recarga del catálogo crea un gateway nuevo y el circuito se reinicia.
- La etiqueta de `intent` en la auditoría muestra el modelo aunque haya caído a reglas (el error `fallback:` lo aclara).

## Dónde cambiar qué
| Si quieres… | Toca… |
|---|---|
| Cambiar de proveedor o de modelo | `config/models.yaml` (sin código) |
| Añadir un proveedor | `Provider` y un constructor en `BUILDERS` (`factory.py`); si es solo local, `LOCAL_ONLY_PROVIDERS` |
| Cambiar qué error es transitorio | `classify_error` y `_TRANSIENT_*` en `gateway.py` |
| Cambiar el circuito | `circuit` en `models.yaml` |
| Cambiar un prompt | Constantes `*_SYSTEM` y `UNTRUSTED` en `src/discovery_data_agent/llm/nodes.py` |
| Conectar un nodo nuevo | Implementar el puerto en `nodes.py` y pasarlo en `bootstrap.build_service_from_snapshot` |
| Pasar el timeout a Bedrock | `build_bedrock_chat` en `factory.py` |
| Cambiar la guarda de texto | `unsafe_generated_text` y `narrative_mentions_ok` en `src/discovery_data_agent/discovery/engine.py` |

## Specs y contradicciones
Specs: [F16](../../specs/comun/F16-llm-providers.md), [F17](../../specs/comun/F17-data-residency.md),
[OP-06](../../specs/on-premise/OP-06-residencia-datos.md), [F22](../../specs/comun/F22-discovery-flow.md).

La spec contradice al código en:
- F16 §Integración: "Credenciales: IAM Roles Anywhere on-premise". El código no las configura: usa la cadena por defecto de AWS.
- F16: `timeout_s` se presenta como tope por petición del proveedor; solo NIM lo recibe.
- El docstring de `src/discovery_data_agent/flows/discover.py` y `DiscoverDeps` describen un juez (`judge`) y un expansor (`fast`) con LLM; F16
  dice que no hay juez en la fase 1a. Manda F16: en el código no están conectados.
- `src/discovery_data_agent/discovery/ports.py` habla de "tres nodos que razonan con LLM", pero declara cinco puertos.
