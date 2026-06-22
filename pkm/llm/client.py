"""OpenAI implementation of the LLM client.

Transport + OpenAI-strict-schema only; all cache / agent_runs / retry
orchestration lives in pkm.llm.base_client.BaseLLMClient. The Gemini sibling is
pkm.llm.gemini_client.GeminiClient. Pick one via pkm.llm.factory.build_llm_client.
"""
import copy
import logging
import time
from typing import Any

import openai
from pydantic import BaseModel

from pkm.llm.base_client import (
    DEFAULT_MAX_COMPLETION_TOKENS as _DEFAULT_MAX_COMPLETION_TOKENS,  # noqa: F401 — re-export
    RETRY_MAX_COMPLETION_TOKENS as _RETRY_MAX_COMPLETION_TOKENS,  # noqa: F401 — re-export
    BaseLLMClient,
    Generation,
)
from pkm.llm.models import MINI  # noqa: F401 — re-exported for callers/tests
from pkm.llm.pricing import compute_cost

logger = logging.getLogger(__name__)

# OpenAI transient errors worth retrying with exponential backoff.
_RETRYABLE = (
    openai.RateLimitError,            # 429
    openai.InternalServerError,        # 5xx
    openai.APIConnectionError,
    openai.APITimeoutError,
)

# Primitive JSON schema types whose pydantic anyOf:[{type:T},{type:"null"}] can be
# collapsed to OpenAI-strict-friendly {"type": [T, "null"]}.
_PRIMITIVE_TYPES = {"string", "integer", "number", "boolean"}


def _inline_refs(schema: dict) -> dict:
    """Resolve every ``$ref`` to a ``$defs`` entry in place, then drop ``$defs``.

    Returns a fully self-contained schema with no ``$ref``/``$defs``. Cycles are
    guarded with a visited set. Shared by the OpenAI and Gemini schema transforms.
    """
    out = copy.deepcopy(schema)
    defs = out.pop("$defs", {})

    def resolve(node: Any, visiting: set[str]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                if name in visiting:
                    return {"type": "object", "additionalProperties": False}
                target = copy.deepcopy(defs.get(name, {}))
                return resolve(target, visiting | {name})
            return {k: resolve(v, visiting) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(i, visiting) for i in node]
        return node

    return resolve(out, set())


def _to_openai_strict_schema(schema: dict) -> dict:
    """Transform a pydantic ``model_json_schema()`` into an OpenAI strict schema."""
    out = _inline_refs(schema)
    _strictify(out)
    return out


# JSON Schema keywords OpenAI strict mode does NOT support.
_UNSUPPORTED_STRICT_KEYS = (
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "format", "multipleOf",
    "minItems", "maxItems", "uniqueItems", "contains",
    "minProperties", "maxProperties", "propertyNames",
    "unevaluatedItems", "unevaluatedProperties",
)


def _strictify(node: Any) -> None:
    """In-place recursive transform (see _to_openai_strict_schema)."""
    if isinstance(node, dict):
        for bad in _UNSUPPORTED_STRICT_KEYS:
            node.pop(bad, None)

        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            null_idx = next(
                (i for i, s in enumerate(any_of) if isinstance(s, dict) and s.get("type") == "null"),
                None,
            )
            if null_idx is not None:
                other = any_of[1 - null_idx]
                other_type = other.get("type") if isinstance(other, dict) else None
                if other_type in _PRIMITIVE_TYPES:
                    collapsed: dict = {"type": [other_type, "null"]}
                    if "description" in node:
                        collapsed["description"] = node["description"]
                    if "default" in node:
                        collapsed["default"] = node["default"]
                    node.clear()
                    node.update(collapsed)
                    return
                _strictify(other)
            for s in any_of:
                _strictify(s)

        if "properties" in node and isinstance(node["properties"], dict):
            node["additionalProperties"] = False
            node["required"] = sorted(node["properties"].keys())
            for value in node["properties"].values():
                _strictify(value)

        if "$defs" in node and isinstance(node["$defs"], dict):
            for def_node in node["$defs"].values():
                _strictify(def_node)

        if "items" in node:
            _strictify(node["items"])

        for key, value in node.items():
            if key in ("properties", "$defs", "anyOf", "items"):
                continue
            if isinstance(value, dict):
                _strictify(value)
            elif isinstance(value, list):
                for item in value:
                    _strictify(item)


class LLMClient(BaseLLMClient):
    """OpenAI-backed LLM client.

    Implements the provider seam (`_generate`, `_cost`); cache / agent_runs /
    retry orchestration is inherited from BaseLLMClient.
    """

    def __init__(self, conn, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        super().__init__(conn)
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _cost(self, model: str, tokens_in: int, cached_tokens: int, tokens_out: int) -> float:
        return compute_cost(model, tokens_in, cached_tokens, tokens_out)

    def _generate(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
        max_tokens: int,
    ) -> Generation:
        """Call chat.completions.create with exponential backoff, return normalized."""
        kwargs: dict[str, Any] = {
            "model": model,
            # gpt-5.x / o-series reject `max_tokens`; `max_completion_tokens` is
            # the unified param accepted across current chat-completion models.
            "max_completion_tokens": max_tokens,
            "messages": messages,
        }
        if output_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_schema.__name__,
                    "strict": True,
                    "schema": _to_openai_strict_schema(output_schema.model_json_schema()),
                },
            }

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except _RETRYABLE:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise
        else:  # pragma: no cover — loop always breaks or raises
            raise RuntimeError("Exhausted retries without success or exception")

        choice = response.choices[0]
        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(details, "cached_tokens", None) or 0
        return Generation(
            text=choice.message.content or "",
            finish_reason=getattr(choice, "finish_reason", None) or "stop",
            tokens_in=prompt_tokens,
            tokens_out=completion_tokens,
            cached_tokens=cached_tokens,
            model=model,
        )
