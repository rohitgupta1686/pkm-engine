"""Provider-agnostic LLM orchestration.

`BaseLLMClient` owns everything that does NOT depend on which vendor serves the
call: the SHA-256 hash cache, the ``agent_runs`` writes, the
validate → truncation-retry → repair-retry loop, and result (de)serialization.

A concrete provider subclass implements just the transport seam:
  - ``_generate(model, messages, output_schema, max_tokens) -> Generation``
  - ``_cost(model, tokens_in, cached_tokens, tokens_out) -> float``

This keeps the public ``call(...)`` contract stable. The OpenAI implementation
lives in ``pkm.llm.client.LLMClient``. The single-call pipeline runs it DB-free
(``conn=None``); cache/agent_runs are only used when a connection is supplied.
"""
import datetime
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Default and maximum completion-token ceilings (shared across providers).
# 16384 is well within current Flash/mini output windows; 32768 is the
# truncation-retry ceiling that bounds spend/latency on a single call.
DEFAULT_MAX_COMPLETION_TOKENS = 16384
RETRY_MAX_COMPLETION_TOKENS = 32768


@dataclass
class Generation:
    """Normalized result of one provider generation, vendor-shape-independent.

    finish_reason is normalized to "length" (hit the output-token ceiling),
    "stop" (completed), or another provider string. The orchestration layer only
    special-cases "length".
    """
    text: str
    finish_reason: str
    tokens_in: int
    tokens_out: int
    cached_tokens: int
    model: str  # the concrete model that actually served the request


class BaseLLMClient:
    """Shared cache / agent_runs / retry orchestration. Subclass per provider.

    ``conn`` is optional. The redesigned single-call pipeline runs DB-free
    (``conn=None``): no agent_runs cache read/write, idempotency handled upstream
    by the note file's existence. The retry/validate orchestration and cost
    computation are unaffected — ``call`` returns ``cost_usd`` so a caller can sum
    spend and enforce a per-run cap without a database.
    """

    def __init__(self, conn=None) -> None:
        self.conn = conn

    # ------------------------------------------------------------------ #
    # Provider seam — subclasses MUST implement these two.
    # ------------------------------------------------------------------ #
    def _generate(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
        max_tokens: int,
    ) -> Generation:
        raise NotImplementedError

    def _cost(
        self, model: str, tokens_in: int, cached_tokens: int, tokens_out: int
    ) -> float:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Cache + agent_runs persistence (provider-agnostic).
    # ------------------------------------------------------------------ #
    def _make_input_hash(
        self, agent_name: str, model: str, prompt_version: str, input_text: str
    ) -> str:
        """SHA-256 of (agent + model + prompt_version + input_text).

        The model string is part of the key, so changing it busts the cache. For
        Gemini we pass a STABLE logical id (e.g. "gemini-flash-auto") so that the
        version-ordered fallback picking a different concrete model does not bust
        the cache mid-corpus; the concrete model is still recorded in
        agent_runs.model for audit.
        """
        return hashlib.sha256(
            (agent_name + model + prompt_version + input_text).encode()
        ).hexdigest()

    def _check_cache(self, agent_name: str, input_hash: str) -> dict | None:
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
        """Upsert an agent_runs row. INSERT OR REPLACE so an ok-row overwrites a
        prior error-row for the same (agent, input_hash)."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO agent_runs
                (id, agent, source_id, input_hash, model, tokens_in, tokens_out,
                 cost_usd, status, error, started_at, finished_at, output_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, agent_name, source_id, input_hash, model,
                tokens_in, tokens_out, cost_usd, status, error,
                started_at, finished_at, output_json,
            ),
        )
        self.conn.commit()

    @staticmethod
    def _serialize_result(result: Any) -> str | None:
        """Serialize a validated result for agent_runs.output_json (best-effort)."""
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
        """Reconstruct a result from cached output_json (None if absent/corrupt)."""
        if output_json is None:
            return None
        if output_schema is None:
            return output_json
        try:
            return output_schema.model_validate_json(output_json)
        except Exception:  # noqa: BLE001 — corrupt/legacy cache degrades gracefully
            return None

    # ------------------------------------------------------------------ #
    # Validate → truncation-retry → repair-retry (provider-agnostic).
    # ------------------------------------------------------------------ #
    def _extract_and_validate(
        self,
        gen: Generation,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
    ) -> Any:
        """Turn a Generation into a validated result.

        Text path (no schema): return the text.
        Schema path: parse JSON, validate, with
          - truncation retry (finish_reason=="length" or un-parseable JSON) at a
            higher token ceiling, regenerated from scratch, and
          - one repair retry on ValidationError (feed the bad output back).
        """
        content = gen.text
        if output_schema is None:
            return content or ""

        # --- Truncation path -------------------------------------------------
        truncated = gen.finish_reason == "length"
        raw_data: Any = None
        if not truncated:
            try:
                raw_data = json.loads(content)
            except json.JSONDecodeError:
                truncated = True

        if truncated:
            logger.warning(
                "_extract_and_validate: output truncated (finish_reason=%r, "
                "content_len=%d); retrying with max_tokens=%d",
                gen.finish_reason, len(content or ""), RETRY_MAX_COMPLETION_TOKENS,
            )
            retry = self._generate(
                model, messages, output_schema, RETRY_MAX_COMPLETION_TOKENS
            )
            if retry.finish_reason == "length":
                raise RuntimeError(
                    "_extract_and_validate: output still truncated after retry "
                    f"(max_tokens={RETRY_MAX_COMPLETION_TOKENS}). Input may be too "
                    "large; consider chunking before the agent call."
                )
            try:
                raw_data = json.loads(retry.text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"_extract_and_validate: JSON parse failed after truncation "
                    f"retry: {exc}. content[:200]={retry.text[:200]!r}"
                ) from exc

        # --- Schema-validation path -----------------------------------------
        try:
            return output_schema(**raw_data)
        except ValidationError as first_err:
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
            repair = self._generate(
                model, repair_messages, output_schema, DEFAULT_MAX_COMPLETION_TOKENS
            )
            try:
                repair_data = json.loads(repair.text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"_extract_and_validate: JSON parse failed on repair retry: "
                    f"{exc}. content[:200]={repair.text[:200]!r}"
                ) from exc
            # If this also raises ValidationError, propagate — no further retries.
            return output_schema(**repair_data)

    # ------------------------------------------------------------------ #
    # Public entry point (identical contract across providers).
    # ------------------------------------------------------------------ #
    def call(
        self,
        agent_name: str,
        model: str,
        prompt_version: str,
        messages: list[dict],
        input_text: str,
        source_id: str | None = None,
        output_schema: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    ) -> dict:
        """Return a cache hit or a fresh result; always writes an agent_runs row.

        {"cached": True, "input_hash": ..., "result": <restored>?}  on cache hit
        {"cached": False, "input_hash": ..., "result": ...,
         "tokens_in": ..., "tokens_out": ...}                         on live call
        """
        input_hash = self._make_input_hash(agent_name, model, prompt_version, input_text)

        # Cache is consulted only when a DB is attached. DB-free runs (conn=None)
        # always make a live call; upstream note-file existence prevents redundancy.
        if self.conn is not None:
            cached = self._check_cache(agent_name, input_hash)
            if cached is not None:
                restored = self._restore_cached_result(
                    cached.get("output_json"), output_schema
                )
                if restored is not None:
                    return {"cached": True, "input_hash": input_hash, "result": restored}
                return {"cached": True, "input_hash": input_hash}

        started_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        try:
            gen = self._generate(model, messages, output_schema, max_tokens)
            result = self._extract_and_validate(gen, model, messages, output_schema)
            cost_usd = self._cost(
                gen.model, gen.tokens_in, gen.cached_tokens, gen.tokens_out
            )
            finished_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
            if self.conn is not None:
                self._write_run(
                    "run_" + uuid.uuid4().hex[:20],
                    agent_name, source_id, input_hash,
                    gen.model,  # record the CONCRETE model that served the call
                    gen.tokens_in, gen.tokens_out, cost_usd,
                    "ok", None, started_at, finished_at,
                    output_json=self._serialize_result(result),
                )
            return {
                "cached": False,
                "input_hash": input_hash,
                "result": result,
                "tokens_in": gen.tokens_in,
                "tokens_out": gen.tokens_out,
                "cost_usd": cost_usd,
            }
        except Exception as e:
            finished_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
            if self.conn is not None:
                self._write_run(
                    "run_" + uuid.uuid4().hex[:20],
                    agent_name, source_id, input_hash, model,
                    0, 0, 0.0, "error", str(e), started_at, finished_at,
                )
            raise
