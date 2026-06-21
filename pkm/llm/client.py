import copy
import datetime
import hashlib
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

import openai
from pydantic import BaseModel, ValidationError

# Default and maximum completion token ceilings.
# 4096 was the original value and is too small for long structured-JSON outputs
# from the concept-extractor / summarizer on long articles (causes finish_reason
# == "length" truncation → JSONDecodeError).  16384 is well within gpt-5.4-mini's
# output window and cheap (~$0.0003 extra per article at worst).
_DEFAULT_MAX_COMPLETION_TOKENS = 16384
# Hard ceiling used on truncation-retry; avoids unbounded spend on a single call.
_RETRY_MAX_COMPLETION_TOKENS = 32768

from pkm.llm.models import MINI  # noqa: F401 — re-exported for callers
from pkm.llm.pricing import compute_cost

# OpenAI transient errors worth retrying with exponential backoff.
_RETRYABLE = (
    openai.RateLimitError,           # 429
    openai.InternalServerError,       # 5xx (incl. the old Anthropic 529 "overloaded" analog)
    openai.APIConnectionError,
    openai.APITimeoutError,
)

# Primitive JSON schema types whose pydantic anyOf:[{type:T},{type:"null"}] can be
# collapsed to OpenAI-strict-friendly {"type": [T, "null"]}.
_PRIMITIVE_TYPES = {"string", "integer", "number", "boolean"}


def _inline_refs(schema: dict) -> dict:
    """Resolve every ``$ref`` to a ``$defs`` entry in place, then drop ``$defs``.

    Returns a fully self-contained schema with no ``$ref``/``$defs``. OpenAI
    strict mode validates ``$defs`` entries against the root context in some
    cases (it reported GraphNode's ``required`` as "extra required keys" at
    context=()), so inlining refs sidesteps that entirely. Cycles are guarded
    with a visited set; our agent schemas are acyclic, but the guard prevents
    infinite recursion on a self-referential model.
    """
    out = copy.deepcopy(schema)
    defs = out.pop("$defs", {})

    def resolve(node: Any, visiting: set[str]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                if name in visiting:
                    # Cycle: leave a minimal object rather than loop forever.
                    return {"type": "object", "additionalProperties": False}
                target = copy.deepcopy(defs.get(name, {}))
                return resolve(target, visiting | {name})
            return {k: resolve(v, visiting) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(i, visiting) for i in node]
        return node

    return resolve(out, set())


def _to_openai_strict_schema(schema: dict) -> dict:
    """Transform a pydantic ``model_json_schema()`` into an OpenAI strict-compliant schema.

    OpenAI strict json_schema requires, at every object level:
      - ``additionalProperties: false``
      - every property listed in ``required``
    and represents nullable fields as ``{"type": [T, "null"]}`` rather than
    pydantic's ``anyOf: [{type: T}, {type: "null"}]``.

    This walks a deep copy of the schema recursively:
      - object nodes (have ``properties``): set additionalProperties=False,
        set required = all property names.
      - ``anyOf: [{type: X}, {type: "null"}]`` (X primitive): collapse to
        ``{type: [X, "null"]}``.
      - ``anyOf`` with a non-primitive or $ref non-null branch + null: kept as
        anyOf; the non-null branch is recursed.
      - recurses into ``$defs`` entries, property values, and array ``items``.
    """
    out = _inline_refs(schema)
    _strictify(out)
    return out


# JSON Schema keywords OpenAI strict mode does NOT support. The OpenAI SDK's
# own to_strict_json_schema strips these; our transform must too, else the API
# rejects the schema. Field(ge=...)/Field(le=...) emit minimum/maximum, which
# are the ones we hit in practice (confidence, strength).
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
        # Strip unsupported strict-mode constraint keywords at this node; nested
        # nodes are recursed by the property/$defs/items/anyOf/catch-all blocks
        # below, so they get stripped too.
        for bad in _UNSUPPORTED_STRICT_KEYS:
            node.pop(bad, None)

        # Collapse pydantic nullable anyOf -> type:[T,"null"] where possible.
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
                    # Collapse to type:[T,"null"], preserving a description if present.
                    collapsed: dict = {"type": [other_type, "null"]}
                    if "description" in node:
                        collapsed["description"] = node["description"]
                    if "default" in node:
                        collapsed["default"] = node["default"]
                    node.clear()
                    node.update(collapsed)
                    return
                # Non-primitive nullable: keep anyOf, recurse the non-null branch.
                _strictify(other)
            # else: anyOf that isn't a nullable pair — recurse each branch.
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

        # Recurse into any remaining dict values we haven't handled.
        for key, value in node.items():
            if key in ("properties", "$defs", "anyOf", "items"):
                continue
            if isinstance(value, dict):
                _strictify(value)
            elif isinstance(value, list):
                for item in value:
                    _strictify(item)


class LLMClient:
    """
    Wraps the OpenAI SDK with:
    - SHA-256 hash cache: skips API call when (agent, input_hash, status='ok') row already exists
    - Structured output via response_format json_schema (strict) when output_schema is provided
    - One-shot repair-retry on ValidationError
    - Exponential backoff on 429 / 5xx / connection / timeout (up to 3 attempts)
    - Real per-call cost_usd computed from token usage (pkm.llm.pricing)
    - agent_runs write on both success and failure paths
    """

    def __init__(self, conn, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.conn = conn
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _make_input_hash(self, agent_name: str, model: str, prompt_version: str, input_text: str) -> str:
        """SHA-256 hex digest of (agent_name + model + prompt_version + input_text).

        The model string is part of the cache key — changing the model busts the
        entire cache (accepted one-time re-ingest per DECISIONS.md [T1-02]).
        """
        return hashlib.sha256((agent_name + model + prompt_version + input_text).encode()).hexdigest()

    def _check_cache(self, agent_name: str, input_hash: str) -> dict | None:
        """
        Query agent_runs for a matching (agent, input_hash, status='ok') row.
        Returns {"id": ..., "status": ..., "output_json": ...} if found, else None.

        output_json is the serialized validated output for rows written after the
        004 migration; it is NULL for legacy rows (and for the rare ok-row whose
        output failed to serialize). Callers use it to restore the real result on
        a cache hit (B-05-02 durable-summary fix).
        """
        row = self.conn.execute(
            "SELECT id, status, output_json FROM agent_runs "
            "WHERE agent = ? AND input_hash = ? AND status = 'ok'",
            (agent_name, input_hash),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "status": row[1], "output_json": row[2]}

    def _write_run(
        self,
        run_id: str,
        agent_name: str,
        source_id: str | None,
        input_hash: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        status: str,
        error: str | None,
        started_at: str,
        finished_at: str,
        output_json: str | None = None,
    ) -> None:
        """
        Upsert a row into agent_runs.
        INSERT OR REPLACE ensures an ok-row overwrites a prior error-row for the same
        (agent, input_hash) — INSERT OR IGNORE would silently drop the ok-row, causing
        indefinite re-execution.

        output_json: serialized validated output for ok-rows (None for error-rows);
        lets a later cache hit restore the real result with no API call (B-05-02).
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO agent_runs
                (id, agent, source_id, input_hash, model, tokens_in, tokens_out,
                 cost_usd, status, error, started_at, finished_at, output_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                agent_name,
                source_id,
                input_hash,
                model,
                tokens_in,
                tokens_out,
                cost_usd,
                status,
                error,
                started_at,
                finished_at,
                output_json,
            ),
        )
        self.conn.commit()

    def _call_api(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
        max_completion_tokens: int = _DEFAULT_MAX_COMPLETION_TOKENS,
    ) -> tuple[object, int, int, int]:
        """
        Call chat.completions.create with exponential backoff on retryable errors.

        Returns (response, prompt_tokens, completion_tokens, cached_tokens).
        cached_tokens is the cached portion of prompt_tokens (0 if absent).

        max_completion_tokens defaults to _DEFAULT_MAX_COMPLETION_TOKENS (16384).
        Pass a higher value on truncation-retry (see _extract_result).
        """
        kwargs: dict[str, Any] = {
            "model": model,
            # gpt-5.x / o-series reject `max_tokens` (400 unsupported_parameter);
            # `max_completion_tokens` is the unified param OpenAI accepts across all
            # current chat-completion models. See 04-03 live-dispatch verification.
            "max_completion_tokens": max_completion_tokens,
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
                usage = response.usage
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                details = getattr(usage, "prompt_tokens_details", None)
                cached_tokens = getattr(details, "cached_tokens", None) or 0
                return response, prompt_tokens, completion_tokens, cached_tokens
            except _RETRYABLE:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise
            # Non-retryable errors raise immediately.

        # Should not reach here, but satisfy type checker
        raise RuntimeError("Exhausted retries without success or raised exception")

    def _extract_result(
        self,
        response: object,
        output_schema: type[BaseModel] | None,
        messages: list[dict],
        model: str,
    ) -> Any:
        """
        Extract and validate the result from the API response.

        If output_schema is None: returns the message content string (text path).
        If output_schema is provided: parses the JSON string in message.content,
        validates it, and attempts one repair-retry on:
          - finish_reason == "length" (output truncated — retry with doubled token ceiling)
          - JSONDecodeError (truncated/malformed JSON — same retry path as above)
          - ValidationError (valid JSON but wrong schema — send repair prompt)
        Any error on the second attempt propagates with a clear message.
        """
        choice = response.choices[0]
        content = choice.message.content
        finish_reason = getattr(choice, "finish_reason", None)

        if output_schema is None:
            return content or ""

        # --- Truncation path: finish_reason=="length" or un-parseable JSON --------
        # Both indicate the model hit the token ceiling mid-output.  Retry with a
        # higher ceiling (_RETRY_MAX_COMPLETION_TOKENS) from scratch (not as a
        # repair conversation — a truncated JSON assistant turn confuses the model).
        truncated = (finish_reason == "length")
        if not truncated:
            try:
                raw_data = json.loads(content)
            except json.JSONDecodeError:
                truncated = True

        if truncated:
            logger.warning(
                "_extract_result: output truncated (finish_reason=%r, content_len=%d); "
                "retrying with max_completion_tokens=%d",
                finish_reason,
                len(content or ""),
                _RETRY_MAX_COMPLETION_TOKENS,
            )
            retry_response, _, _, _ = self._call_api(
                model, messages, output_schema,
                max_completion_tokens=_RETRY_MAX_COMPLETION_TOKENS,
            )
            retry_choice = retry_response.choices[0]
            retry_finish = getattr(retry_choice, "finish_reason", None)
            retry_content = retry_choice.message.content
            if retry_finish == "length":
                raise RuntimeError(
                    f"_extract_result: output still truncated after retry "
                    f"(max_completion_tokens={_RETRY_MAX_COMPLETION_TOKENS}). "
                    "Input may be too large; consider chunking before agent call."
                )
            try:
                raw_data = json.loads(retry_content)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"_extract_result: JSON parse failed after truncation retry: {exc}. "
                    f"content[:200]={retry_content[:200]!r}"
                ) from exc

        # --- Schema-validation path -----------------------------------------------
        try:
            return output_schema(**raw_data)
        except ValidationError as first_err:
            # One repair-retry: feed the invalid response back + a fix instruction.
            repair_messages = list(messages) + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        f"Your response failed schema validation: {first_err}. "
                        "Return ONLY a valid JSON object matching the schema. "
                        "Do not include any text outside the JSON object."
                    ),
                },
            ]
            repair_response, _, _, _ = self._call_api(model, repair_messages, output_schema)
            repair_content = repair_response.choices[0].message.content
            try:
                repair_data = json.loads(repair_content)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"_extract_result: JSON parse failed on validation-repair retry: {exc}. "
                    f"content[:200]={repair_content[:200]!r}"
                ) from exc
            # If this also raises ValidationError, propagate — no further retries
            return output_schema(**repair_data)

    @staticmethod
    def _serialize_result(result: Any) -> str | None:
        """Serialize a validated agent result for persistence in agent_runs.output_json.

        - pydantic BaseModel -> model_dump_json()
        - plain string (text-path agents, output_schema=None) -> the string itself
        - anything else / failure -> None (the row is still written; the cache hit
          just won't be restorable and falls back to the legacy RuntimeError path)
        """
        try:
            if isinstance(result, BaseModel):
                return result.model_dump_json()
            if isinstance(result, str):
                return result
        except Exception:  # noqa: BLE001 — serialization is best-effort
            return None
        return None

    @staticmethod
    def _restore_cached_result(
        output_json: str | None, output_schema: type[BaseModel] | None
    ) -> Any | None:
        """Reconstruct an agent result from a cached output_json string.

        Returns None (caller treats as "nothing to restore") when output_json is
        absent, or when validation/parse fails — never raises, so a corrupt cache
        row degrades to the legacy cache-hit behavior rather than crashing ingest.
        """
        if output_json is None:
            return None
        if output_schema is None:
            # Text-path agent: the stored string IS the result.
            return output_json
        try:
            return output_schema.model_validate_json(output_json)
        except Exception:  # noqa: BLE001 — corrupt/legacy cache degrades gracefully
            return None

    def call(
        self,
        agent_name: str,
        model: str,
        prompt_version: str,
        messages: list[dict],
        input_text: str,
        source_id: str | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> dict:
        """
        Main entry point. Returns:
          {"cached": True, "input_hash": ..., "result": <restored>?} on cache hit
            ("result" is present only when a serialized output_json could be
            restored — i.e. the row was written after the 004 migration and an
            output_schema is supplied to deserialize it), or
          {"cached": False, "input_hash": ..., "result": ..., "tokens_in": ..., "tokens_out": ...} on live call.
        Always writes to agent_runs (ok or error row).
        """
        input_hash = self._make_input_hash(agent_name, model, prompt_version, input_text)

        cached = self._check_cache(agent_name, input_hash)
        if cached is not None:
            restored = self._restore_cached_result(cached.get("output_json"), output_schema)
            if restored is not None:
                # B-05-02 durable-summary fix: hand the real result back so the
                # pipeline rebuilds the page from cache with $0 API calls.
                return {"cached": True, "input_hash": input_hash, "result": restored}
            # Legacy ok-row (pre-004) or no output_schema: no output to restore.
            # Preserve the historical contract — caller raises/handles cache hit.
            return {"cached": True, "input_hash": input_hash}

        started_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

        try:
            response, tokens_in, tokens_out, cached_tokens = self._call_api(model, messages, output_schema)
            result = self._extract_result(response, output_schema, messages, model)
            cost_usd = compute_cost(model, tokens_in, cached_tokens, tokens_out)
            finished_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
            run_id = "run_" + uuid.uuid4().hex[:20]
            self._write_run(
                run_id,
                agent_name,
                source_id,
                input_hash,
                model,
                tokens_in,
                tokens_out,
                cost_usd,
                "ok",
                None,
                started_at,
                finished_at,
                output_json=self._serialize_result(result),
            )
            return {
                "cached": False,
                "input_hash": input_hash,
                "result": result,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
        except Exception as e:
            finished_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
            run_id = "run_" + uuid.uuid4().hex[:20]
            self._write_run(
                run_id,
                agent_name,
                source_id,
                input_hash,
                model,
                0,
                0,
                0.0,
                "error",
                str(e),
                started_at,
                finished_at,
            )
            raise