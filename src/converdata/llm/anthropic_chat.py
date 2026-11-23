"""Claude por la API de Anthropic, con su SDK oficial (proveedor `anthropic` del gateway, F16).

Expone la parte de la interfaz de chat que usan los nodos (`invoke`, `with_structured_output`), igual que los demás
proveedores. Diferencias de la API de Claude que este adaptador resuelve:

- La salida estructurada usa `messages.parse` con el modelo de Pydantic; no hace falta forzar una herramienta.
- Los modelos actuales rechazan `temperature` y piensan siempre: la profundidad se regula con `effort`.
- Un rechazo por política llega como respuesta (`stop_reason: refusal`), no como excepción: aquí se convierte en
  `LLMRefused`, que el gateway trata como error de contenido (no salta a otro proveedor).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

# Sin `max_tokens` en el rol. El pensamiento cuenta dentro de este tope: un valor bajo corta la respuesta.
DEFAULT_MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMRefused(RuntimeError):
    """El modelo declinó la petición por política."""


def split_messages(messages) -> tuple[str, list[dict]]:
    """Mensajes de LangChain (o un texto) → (`system`, turnos `user`/`assistant`)."""
    if isinstance(messages, str):
        return "", [{"role": "user", "content": messages}]
    system: list[str] = []
    turns: list[dict] = []
    for message in messages:
        kind = getattr(message, "type", "human")
        content = getattr(message, "content", message)
        text = content if isinstance(content, str) else "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        if kind == "system":
            system.append(text)
        else:
            turns.append({"role": "assistant" if kind == "ai" else "user", "content": text})
    return "\n\n".join(system), turns


class ClaudeChat:
    def __init__(self, client, model: str, max_tokens: int | None = None, effort: str | None = None,
                 refusal_fallback: bool = False, schema: Any = None):
        self._client, self.model, self._max_tokens = client, model, max_tokens or DEFAULT_MAX_TOKENS
        self._effort, self._refusal_fallback, self._schema = effort, refusal_fallback, schema

    def with_structured_output(self, schema, **_kwargs) -> "ClaudeChat":
        return ClaudeChat(self._client, self.model, self._max_tokens, self._effort, self._refusal_fallback, schema)

    def invoke(self, messages, **_kwargs):
        system, turns = split_messages(messages)
        params: dict[str, Any] = {"model": self.model, "max_tokens": self._max_tokens, "messages": turns}
        if system:
            params["system"] = system
        if self._effort:
            params["output_config"] = {"effort": self._effort}
        api = self._client.messages
        if self._refusal_fallback:
            # Ante un rechazo, la API repite la petición en otro modelo de Claude dentro de la misma llamada.
            api = self._client.beta.messages
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        if self._schema is None:
            response = api.create(**params)
        else:
            response = api.parse(output_format=self._schema, **params)
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise LLMRefused(f"{self.model} declinó la petición" + (f" ({category})" if category else ""))
        if self._schema is not None:
            if response.parsed_output is None:
                raise ValueError(f"{self.model} no devolvió una salida estructurada (stop_reason={response.stop_reason})")
            return response.parsed_output
        if response.stop_reason not in ("end_turn", "stop_sequence"):  # cortada (`max_tokens`) o sin terminar
            raise ValueError(f"{self.model} no terminó la respuesta (stop_reason={response.stop_reason})")
        text = "".join(block.text for block in response.content if block.type == "text")
        tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
        return AIMessage(content=text, usage_metadata={"input_tokens": tokens_in, "output_tokens": tokens_out,
                                                       "total_tokens": tokens_in + tokens_out})
