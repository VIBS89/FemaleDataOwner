# Gateway de modelos (LLM)

Actualizado el 2026-11-17.

**Para qué sirve.** Es el único punto por el que ConverData llama a un modelo de lenguaje. Resuelve cada rol (`planner`, `fast`,
`judge`) al proveedor y modelo de `config/models.yaml`, aplica la guarda de residencia de datos, cambia a un proveedor de respaldo
ante errores transitorios, abre un circuito ante fallos repetidos e informa el consumo de tokens. Los nodos del DiscoverFlow y el
enriquecimiento del Catalog Builder lo usan sin saber qué proveedor hay detrás.

**Lo esencial**
- Sin `config/models.yaml` (o sin `CONVERDATA_MODELS` en la API) todo es determinista y el flujo responde igual.
- Proveedores: `nvidia_nim`, `bedrock`, `ollama` (este solo con `environment: local`, regla de código).
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
| `ModelsConfig`, `ProviderConfig`, `RoleConfig`, `FallbackConfig`, `CircuitConfig` | `src/converdata/llm/factory.py` | Esquema de `models.yaml` |
| `load_models` | `src/converdata/llm/factory.py:91` | Lee el YAML; `CONVERDATA_ENV` sobrescribe `environment` |
| `build_nim_chat`, `build_bedrock_chat`, `build_ollama_chat` | `src/converdata/llm/factory.py:113-152` | Constructores LangChain por proveedor |
| `LLMGateway` | `src/converdata/llm/gateway.py:151` | Validación, rutas, invocación, respaldo, etiquetas, uso |
| `RoutedChat` | `src/converdata/llm/gateway.py:117` | Imita `invoke` y `with_structured_output` de LangChain |
| `CircuitBreaker` | `src/converdata/llm/gateway.py:66` | Circuito por proveedor |
| `classify_error` | `src/converdata/llm/gateway.py:48` | Decide si un error es transitorio |
| `estimate_usage` | `src/converdata/llm/gateway.py:103` | Tokens del proveedor o ~4 caracteres por token |
| `LlmIntentClassifier`, `LlmReranker`, `LlmNarrator` | `src/converdata/llm/nodes.py` | Puertos del DiscoverFlow con LLM |
| `LlmEnricher` | `src/converdata/llm/nodes.py:116` | Descripciones sugeridas en el build |
| Ensamblado | `src/converdata/bootstrap.py:96` | Conecta los nodos según los roles declarados |
| `converdata llm smoke` | `src/converdata/cli.py:458` | Prueba cada rol contra su proveedor |

## Roles de modelo
| Rol | Lo usa | Si falta en `models.yaml` |
|---|---|---|
| `planner` | `intent` y `rerank` del DiscoverFlow; `LlmEnricher` del build | Reglas y relevancia por cobertura |
| `fast` | `respond` (narrativa) | `TemplateNarrator` |
| `judge` | Nadie: el nodo `review` lo anota como rol, pero no hay implementación conectada | Chequeos deterministas |
| `embed` | Retirado: se ignora con un aviso; en qa/prod la API no arranca si aparece | — |

`config/models.example.yaml` usa `planner` y `fast` (NIM alojado, `openai/gpt-oss-20b`); `config/models.local.example.yaml` y el
`config/models.yaml` local usan Ollama y declaran también `judge`.

## Cómo funciona
1. **Carga** (`load_models`): YAML → `ModelsConfig`. `CONVERDATA_ENV` gana a `environment`. Roles retirados se descartan.
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
   la API rechaza (429) o, con `CONVERDATA_TOKEN_LIMIT_MODE=deterministic`, usa el mismo catálogo sin LLM.

### Qué se envía al modelo y qué no
| Nodo | Se envía | No se envía |
|---|---|---|
| intent | Pregunta y hasta 5 entradas del historial que manda el cliente, entre `<datos>` | Usuario, roles, `visible_ids`, catálogo |
| rerank | Pregunta; hasta 25 candidatos **ya filtrados por visibilidad**: `id` (`asset_key`), tipo, descripción y su fuente, ids de reglas, evidencias (`tipo:fuente`) | Ubicaciones, servidores, responsables, textos de reglas |
| respond | Pregunta; candidatos (`asset_key`, confianza, `why`, descripción), alternativas completas, `knowledge_gap` | Relaciones, ubicaciones, responsables, reglas |
| enrich (build) | Por tabla: nombre completo, tipo, PK, FKs, columnas con nombre y tipo | Valores de datos, filas, descripciones existentes |

Nunca viajan credenciales, hosts ni valores de datos (el catálogo no los tiene: `FORBIDDEN_KEYS` en
`src/converdata/models/catalog.py:13`). La pregunta del usuario sí viaja: por eso la guarda de residencia.

### Tope de tokens
- **Por llamada**: `max_tokens` del rol (`max_completion_tokens` en NIM, `max_tokens` en Bedrock, `num_predict` en Ollama). En los
  ejemplos, `fast` = 400 y `planner` = 1024 (NIM) o sin tope (Ollama local).
- **Por entrada**: la API limita la pregunta a 2000 caracteres y el historial a 10 textos; el nodo `intent` usa los 5 últimos.
- **Por día y usuario**: `CONVERDATA_TOKEN_LIMIT` (0 = sin tope). Con salida estructurada el proveedor no informa el uso y se estima.

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
  `MissingCredential` (falta la clave de NIM alojado).
- Salidas estructuradas: `IntentResult` (`models/intent.py`), `RerankResult` (`discovery/ports.py`), `EnrichmentBatch` (`llm/nodes.py`).

## Configuración
`config/models.yaml` (fuera de git; plantillas `config/models.example.yaml` y `config/models.local.example.yaml`).

| Clave | Efecto |
|---|---|
| `environment` | `local` permite Ollama; `CONVERDATA_ENV` la sobrescribe |
| `data_mode` | `real` activa la guarda de residencia; obligatorio en qa/prod (`production_violations`) |
| `providers.<p>.enabled`, `allowed_data` | Activación y qué datos puede recibir |
| `providers.nvidia_nim.base_url`, `api_key_env`, `timeout_s` | `null` = API alojada de NVIDIA; clave en `NVIDIA_API_KEY` por defecto |
| `providers.bedrock.region` | Región; por defecto `us-east-1` |
| `roles.<rol>` | `provider`, `model`, `temperature`, `max_tokens`, `reasoning` y `num_ctx` (solo Ollama) |
| `fallback` | `provider`, `models` por rol, `on` (tipos de error) |
| `circuit` | `errors`, `window_s`, `open_s` |

En la API: `CONVERDATA_MODELS` (ruta del archivo; si no existe, modo determinista), `CONVERDATA_TOKEN_LIMIT`,
`CONVERDATA_TOKEN_LIMIT_MODE`, `CONVERDATA_ENV`.

## Pruebas que lo cubren
- `tests/test_llm_gateway.py` (21 pruebas): enrutado a NIM, cambio a Bedrock por configuración, residencia, respaldo solo ante
  transitorios, circuito, clasificación de errores, caída total → determinista, timeout de NIM, Ollama solo en local, `CONVERDATA_ENV`,
  gancho de uso.
- `tests/test_llm_guards.py`: el reranker no añade candidatos; narrativa con objetos ajenos reemplazada; fallo del modelo → respaldo.
- `tests/test_prompt_injection.py` y suites `inyeccion` y `guardas` de `converdata eval gate` (`tests/test_gate.py`).
- `api/tests/test_api.py`: tope diario, uso atribuido al usuario, modo determinista con el tope agotado.

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
- `reasoning` solo se aplica a Ollama; NIM y Bedrock lo ignoran.
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
| Cambiar un prompt | Constantes `*_SYSTEM` y `UNTRUSTED` en `src/converdata/llm/nodes.py` |
| Conectar un nodo nuevo | Implementar el puerto en `nodes.py` y pasarlo en `bootstrap.build_service_from_snapshot` |
| Pasar el timeout a Bedrock | `build_bedrock_chat` en `factory.py` |
| Cambiar la guarda de texto | `unsafe_generated_text` y `narrative_mentions_ok` en `src/converdata/discovery/engine.py` |

## Specs y contradicciones
Specs: [F16](../../specs/comun/F16-llm-providers.md), [F17](../../specs/comun/F17-data-residency.md),
[OP-06](../../specs/on-premise/OP-06-residencia-datos.md), [F22](../../specs/comun/F22-discovery-flow.md).

La spec contradice al código en:
- F16 §Integración: "Credenciales: IAM Roles Anywhere on-premise". El código no las configura: usa la cadena por defecto de AWS.
- F16: `timeout_s` se presenta como tope por petición del proveedor; solo NIM lo recibe.
- El docstring de `src/converdata/flows/discover.py` y `DiscoverDeps` describen un juez (`judge`) y un expansor (`fast`) con LLM; F16
  dice que no hay juez en la fase 1a. Manda F16: en el código no están conectados.
- `src/converdata/discovery/ports.py` habla de "tres nodos que razonan con LLM", pero declara cinco puertos.
