"""OpenAI-compatible implementation of the LLM client.

Transport + OpenAI-strict-schema only; all (optional) cache / agent_runs / retry
orchestration lives in pkm.llm.base_client.BaseLLMClient. The single-call
pipeline constructs this directly with conn=None (DB-free); see
pkm.cli._build_synthesis_client. The default endpoint is Z.AI's OpenAI-compatible
GLM-5.2 API, while OpenAI remains usable by overriding OPENAI_BASE_URL/model.
"""
import copy
import io
import json
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
    """OpenAI-compatible LLM client.

    Implements the provider seam (`_generate`, `_cost`); cache / agent_runs /
    retry orchestration is inherited from BaseLLMClient.
    """

    def __init__(self, conn, api_key: str, base_url: str = "https://api.z.ai/api/paas/v4/") -> None:
        super().__init__(conn)
        self.base_url = base_url.rstrip("/")
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _cost(self, model: str, tokens_in: int, cached_tokens: int, tokens_out: int) -> float:
        return compute_cost(model, tokens_in, cached_tokens, tokens_out)

    def _chat_kwargs(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build the chat.completions request body shared by the sync and batch paths.

        The sync path passes this straight to ``chat.completions.create``; the Batch
        API path serializes it as the ``body`` of each JSONL request line, so both
        paths send byte-identical request payloads.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        token_param = "max_tokens" if self._uses_legacy_max_tokens(model) else "max_completion_tokens"
        kwargs[token_param] = max_tokens
        # Gemini 3 defaults to high internal reasoning. OCR is straightforward
        # transcription, so use its OpenAI-compat mapping to Gemini's minimal
        # thinking level; this preserves output tokens and lowers latency/cost.
        if model.startswith("gemini-3-") and "generativelanguage.googleapis.com" in self.base_url:
            kwargs["reasoning_effort"] = "minimal"
        if output_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_schema.__name__,
                    "strict": True,
                    "schema": _to_openai_strict_schema(output_schema.model_json_schema()),
                },
            }
        return kwargs

    def _generate(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
        max_tokens: int,
    ) -> Generation:
        """Call chat.completions.create with exponential backoff, return normalized."""
        kwargs = self._chat_kwargs(model, messages, output_schema, max_tokens)

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

    # --- OpenAI Batch API (async, 50% discount) --------------------------------
    #
    # The article-ingest path submits all its synthesis calls as one batch instead
    # of N synchronous calls. Flow: build_batch_request (one per source) → submit_batch
    # (upload JSONL + create batch) → poll_batch (block until terminal) → collect_batch
    # (download + parse results by custom_id). See pkm.pipeline.batch_ingest.

    def build_batch_request(
        self,
        custom_id: str,
        model: str,
        messages: list[dict],
        max_tokens: int = _RETRY_MAX_COMPLETION_TOKENS,
        output_schema: type[BaseModel] | None = None,
    ) -> dict:
        """One JSONL line for the /v1/chat/completions batch endpoint.

        ``max_tokens`` defaults to the higher truncation-retry ceiling because the
        async batch path can't do the sync path's on-the-fly truncation retry — a
        generous ceiling minimizes ``finish_reason == "length"`` failures.
        """
        return {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": self._chat_kwargs(model, messages, output_schema, max_tokens),
        }

    def submit_batch(self, requests: list[dict]) -> str:
        """Upload the JSONL and create a 24h batch job; return the batch id."""
        jsonl = "\n".join(json.dumps(r) for r in requests).encode("utf-8")
        upload = self.client.files.create(
            file=("batch.jsonl", io.BytesIO(jsonl)),
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=upload.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        logger.info("submit_batch: created batch %s (%d requests)", batch.id, len(requests))
        return batch.id

    def poll_batch(self, batch_id: str, interval: int, timeout: int):
        """Block until the batch reaches a terminal status or ``timeout`` seconds pass.

        On timeout the batch is cancelled (so it can't keep billing without a note
        being committed) and the last-retrieved batch object is returned — the caller
        treats any non-``completed`` status as a failure and re-submits next run.
        """
        terminal = {"completed", "failed", "expired", "cancelled"}
        deadline = time.monotonic() + timeout
        while True:
            batch = self.client.batches.retrieve(batch_id)
            if batch.status in terminal:
                logger.info("poll_batch: batch %s reached status=%s", batch_id, batch.status)
                return batch
            if time.monotonic() >= deadline:
                logger.warning(
                    "poll_batch: batch %s still %s after %ds — cancelling",
                    batch_id, batch.status, timeout,
                )
                try:
                    self.client.batches.cancel(batch_id)
                except Exception:  # noqa: BLE001 — best-effort; report the timeout regardless
                    logger.exception("poll_batch: cancel failed for %s", batch_id)
                return self.client.batches.retrieve(batch_id)
            time.sleep(interval)

    def collect_batch(self, batch) -> dict[str, dict]:
        """Parse a completed batch's output (+ error) files, keyed by custom_id.

        Each successful entry is ``{text, tokens_in, tokens_out, cached_tokens}``.
        A request that errored, returned a non-200, or hit the output-token ceiling
        (``finish_reason == "length"``) is recorded as ``{error: <reason>}`` — the
        caller skips writing its note so it's retried on the next run.
        """
        results: dict[str, dict] = {}

        output_file_id = getattr(batch, "output_file_id", None)
        if output_file_id:
            for line in self._read_jsonl_file(output_file_id):
                custom_id = line.get("custom_id")
                if custom_id is None:
                    continue
                response = line.get("response") or {}
                if line.get("error") or response.get("status_code") != 200:
                    results[custom_id] = {"error": line.get("error") or response.get("status_code")}
                    continue
                body = response.get("body") or {}
                choice = (body.get("choices") or [{}])[0]
                finish_reason = choice.get("finish_reason")
                text = ((choice.get("message") or {}).get("content")) or ""
                if finish_reason == "length" or not text.strip():
                    results[custom_id] = {"error": f"finish_reason={finish_reason}"}
                    continue
                usage = body.get("usage") or {}
                details = usage.get("prompt_tokens_details") or {}
                results[custom_id] = {
                    "text": text,
                    "tokens_in": usage.get("prompt_tokens", 0) or 0,
                    "tokens_out": usage.get("completion_tokens", 0) or 0,
                    "cached_tokens": details.get("cached_tokens", 0) or 0,
                }

        error_file_id = getattr(batch, "error_file_id", None)
        if error_file_id:
            for line in self._read_jsonl_file(error_file_id):
                custom_id = line.get("custom_id")
                if custom_id is not None and custom_id not in results:
                    results[custom_id] = {"error": line.get("error") or "batch_error"}

        return results

    def _read_jsonl_file(self, file_id: str) -> list[dict]:
        """Download an OpenAI file and parse it as JSONL (one object per line)."""
        content = self.client.files.content(file_id)
        text = content.text if hasattr(content, "text") else content.read().decode("utf-8")
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]

    def _uses_legacy_max_tokens(self, model: str) -> bool:
        """Compatibility hosts that expect ``max_tokens``, not OpenAI's newer name."""
        return (
            model.startswith("glm-")
            or "api.z.ai" in self.base_url
            or "generativelanguage.googleapis.com" in self.base_url
        )
