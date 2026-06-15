import datetime
import hashlib
import time
import uuid
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from pkm.llm.models import HAIKU, SONNET, OPUS  # noqa: F401 — imported for callers; no model strings hardcoded here


class LLMClient:
    """
    Wraps the Anthropic SDK with:
    - SHA-256 hash cache: skips API call when (agent, input_hash, status='ok') row already exists
    - Structured output via tool-calling when output_schema is provided
    - One-shot repair-retry on ValidationError
    - Exponential backoff on 429/529 (up to 3 attempts)
    - agent_runs write on both success and failure paths
    """

    def __init__(self, conn, api_key: str) -> None:
        self.conn = conn
        self.client = anthropic.Anthropic(api_key=api_key)

    def _make_input_hash(self, agent_name: str, model: str, prompt_version: str, input_text: str) -> str:
        """SHA-256 hex digest of (agent_name + model + prompt_version + input_text)."""
        return hashlib.sha256((agent_name + model + prompt_version + input_text).encode()).hexdigest()

    def _check_cache(self, agent_name: str, input_hash: str) -> dict | None:
        """
        Query agent_runs for a matching (agent, input_hash, status='ok') row.
        Returns {"id": ..., "status": ...} if found, else None.
        """
        row = self.conn.execute(
            "SELECT id, status FROM agent_runs WHERE agent = ? AND input_hash = ? AND status = 'ok'",
            (agent_name, input_hash),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "status": row[1]}

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
    ) -> None:
        """
        Upsert a row into agent_runs.
        INSERT OR REPLACE ensures an ok-row overwrites a prior error-row for the same
        (agent, input_hash) — INSERT OR IGNORE would silently drop the ok-row, causing
        indefinite re-execution.
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO agent_runs
                (id, agent, source_id, input_hash, model, tokens_in, tokens_out,
                 cost_usd, status, error, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self.conn.commit()

    def _call_api(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
    ) -> tuple[object, int, int]:
        """
        Call messages.create with exponential backoff on 429/529.
        Returns (response, input_tokens, output_tokens).
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": messages,
        }

        if output_schema is not None:
            tool_def = {
                "name": "structured_output",
                "description": f"Return output matching the {output_schema.__name__} schema",
                "input_schema": output_schema.model_json_schema(),
            }
            kwargs["tools"] = [tool_def]
            kwargs["tool_choice"] = {"type": "tool", "name": "structured_output"}

        for attempt in range(3):
            try:
                response = self.client.messages.create(**kwargs)
                return response, response.usage.input_tokens, response.usage.output_tokens
            except anthropic.APIStatusError as exc:
                if exc.status_code in (429, 529):
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                raise

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
        If output_schema is None: returns the first text block's text.
        If output_schema is provided: extracts tool_use block, validates, and attempts
        one repair-retry on ValidationError.
        """
        if output_schema is None:
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        # Find the structured_output tool_use block
        tool_block = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "structured_output":
                tool_block = block
                break

        raw_data = tool_block.input

        try:
            return output_schema(**raw_data)
        except ValidationError as first_err:
            # One repair-retry: append error feedback and retry
            tool_def = {
                "name": "structured_output",
                "description": f"Return output matching the {output_schema.__name__} schema",
                "input_schema": output_schema.model_json_schema(),
            }
            repair_messages = list(messages) + [
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": (
                        f"Your response failed schema validation: {first_err}. "
                        "Fix it and call structured_output again."
                    ),
                },
            ]
            repair_response = self.client.messages.create(
                model=model,
                max_tokens=4096,
                messages=repair_messages,
                tools=[tool_def],
                tool_choice={"type": "tool", "name": "structured_output"},
            )

            repair_block = None
            for block in repair_response.content:
                if block.type == "tool_use" and block.name == "structured_output":
                    repair_block = block
                    break

            repair_data = repair_block.input
            # If this also raises ValidationError, propagate — no further retries
            return output_schema(**repair_data)

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
          {"cached": True, "input_hash": ...} on cache hit, or
          {"cached": False, "input_hash": ..., "result": ..., "tokens_in": ..., "tokens_out": ...} on live call.
        Always writes to agent_runs (ok or error row).
        """
        input_hash = self._make_input_hash(agent_name, model, prompt_version, input_text)

        cached = self._check_cache(agent_name, input_hash)
        if cached is not None:
            return {"cached": True, "input_hash": input_hash}

        started_at = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

        try:
            response, tokens_in, tokens_out = self._call_api(model, messages, output_schema)
            result = self._extract_result(response, output_schema, messages, model)
            cost_usd = 0.0  # placeholder; exact pricing not hardcoded
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
