"""
Regression tests for finish_reason=="length" truncation handling in LLMClient.

Prior to the fix, a long article whose structured-JSON output exceeded 4096 tokens
caused `json.loads` to raise JSONDecodeError (the output was cut mid-JSON).  The
repair-retry only caught ValidationError, so the pipeline crashed.

These tests verify:
1. finish_reason=="length" on first response → retry fires with higher token ceiling
   → second response succeeds → valid pydantic output returned.
2. JSONDecodeError on first response (truncated without finish_reason) → same retry.
3. Retry also truncates (finish_reason=="length") → RuntimeError with clear message.
4. Retry produces bad JSON → RuntimeError with clear message.
5. Original ValidationError path still works (not broken by the refactor).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from pkm.llm.client import LLMClient, _DEFAULT_MAX_COMPLETION_TOKENS, _RETRY_MAX_COMPLETION_TOKENS
from pkm.llm.models import MINI
from pkm.schemas.agent_io import SummarizerOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SUMMARY = {
    "thesis": "Anthropic's commercial success is astonishing.",
    "key_claims": [],
    "caveats": [],
    "summary_confidence": 0.9,
}


def _resp(content: str, finish_reason: str = "stop"):
    """Build a minimal mock OpenAI response."""
    resp = MagicMock()
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    resp.usage.prompt_tokens_details.cached_tokens = 0
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    resp.choices = [choice]
    return resp


def _client(db_conn):
    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        client = LLMClient(db_conn, api_key="test-key")
        yield client, MockOpenAI.return_value.chat.completions.create


# ---------------------------------------------------------------------------
# Test 1: finish_reason=="length" on first call → retry succeeds
# ---------------------------------------------------------------------------

def test_truncation_finish_reason_length_retries(db_conn):
    """First response is truncated (finish_reason=length); retry with higher ceiling succeeds."""
    truncated_content = '{"thesis": "Anthropic'  # cut mid-JSON
    valid_content = json.dumps(_VALID_SUMMARY)

    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        mock_create = MockOpenAI.return_value.chat.completions.create
        mock_create.side_effect = [
            _resp(truncated_content, finish_reason="length"),
            _resp(valid_content, finish_reason="stop"),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        result = client.call(
            agent_name="summarizer_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "Summarize this long article..."}],
            input_text="long article text",
            output_schema=SummarizerOutput,
        )

    assert isinstance(result["result"], SummarizerOutput)
    assert result["result"].thesis == _VALID_SUMMARY["thesis"]

    # Verify the retry call used the higher token ceiling
    calls = mock_create.call_args_list
    assert len(calls) == 2
    first_kwargs = calls[0].kwargs if calls[0].kwargs else calls[0][1]
    second_kwargs = calls[1].kwargs if calls[1].kwargs else calls[1][1]
    assert first_kwargs.get("max_completion_tokens") == _DEFAULT_MAX_COMPLETION_TOKENS
    assert second_kwargs.get("max_completion_tokens") == _RETRY_MAX_COMPLETION_TOKENS


# ---------------------------------------------------------------------------
# Test 2: JSONDecodeError on first call (truncated without explicit finish_reason)
# ---------------------------------------------------------------------------

def test_truncation_json_decode_error_retries(db_conn):
    """First response is un-parseable JSON (truncated); retry succeeds."""
    truncated_content = '{"thesis": "AI is big", "key_claims": [{"statement": "foo"'  # cut
    valid_content = json.dumps(_VALID_SUMMARY)

    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        mock_create = MockOpenAI.return_value.chat.completions.create
        mock_create.side_effect = [
            _resp(truncated_content, finish_reason="stop"),  # stop but broken JSON
            _resp(valid_content, finish_reason="stop"),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        result = client.call(
            agent_name="summarizer_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "Summarize..."}],
            input_text="long article text",
            output_schema=SummarizerOutput,
        )

    assert isinstance(result["result"], SummarizerOutput)
    # Retry must use higher ceiling
    calls = mock_create.call_args_list
    assert len(calls) == 2
    second_kwargs = calls[1].kwargs if calls[1].kwargs else calls[1][1]
    assert second_kwargs.get("max_completion_tokens") == _RETRY_MAX_COMPLETION_TOKENS


# ---------------------------------------------------------------------------
# Test 3: Retry also truncates → RuntimeError
# ---------------------------------------------------------------------------

def test_truncation_retry_also_truncated_raises(db_conn):
    """Both first and retry responses are finish_reason=length → RuntimeError."""
    truncated = '{"thesis": "cut'

    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        mock_create = MockOpenAI.return_value.chat.completions.create
        mock_create.side_effect = [
            _resp(truncated, finish_reason="length"),
            _resp(truncated, finish_reason="length"),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        with pytest.raises(RuntimeError, match="still truncated after retry"):
            client.call(
                agent_name="summarizer_agent",
                model=MINI,
                prompt_version="v1",
                messages=[{"role": "user", "content": "..."}],
                input_text="extremely long article",
                output_schema=SummarizerOutput,
            )

    # The error row must be recorded in agent_runs
    row = db_conn.execute(
        "SELECT status, error FROM agent_runs WHERE agent = 'summarizer_agent'"
    ).fetchone()
    assert row is not None
    assert row[0] == "error"
    assert "still truncated" in row[1]


# ---------------------------------------------------------------------------
# Test 4: Retry produces bad JSON → RuntimeError (not silent crash)
# ---------------------------------------------------------------------------

def test_truncation_retry_bad_json_raises(db_conn):
    """Retry response is not valid JSON → RuntimeError with clear message."""
    truncated = '{"thesis": "cut'
    bad_retry = "Sorry, I cannot complete this."  # plain text, not JSON

    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        mock_create = MockOpenAI.return_value.chat.completions.create
        mock_create.side_effect = [
            _resp(truncated, finish_reason="length"),
            _resp(bad_retry, finish_reason="stop"),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        with pytest.raises(RuntimeError, match="JSON parse failed after truncation retry"):
            client.call(
                agent_name="summarizer_agent",
                model=MINI,
                prompt_version="v1",
                messages=[{"role": "user", "content": "..."}],
                input_text="very long article",
                output_schema=SummarizerOutput,
            )


# ---------------------------------------------------------------------------
# Test 5: ValidationError path still works (not broken by refactor)
# ---------------------------------------------------------------------------

def test_validation_error_repair_retry_still_works(db_conn):
    """Regression: existing ValidationError repair-retry path is unchanged."""
    invalid_content = json.dumps({"bad_field": "wrong"})
    valid_content = json.dumps(_VALID_SUMMARY)

    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        mock_create = MockOpenAI.return_value.chat.completions.create
        mock_create.side_effect = [
            _resp(invalid_content, finish_reason="stop"),
            _resp(valid_content, finish_reason="stop"),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        result = client.call(
            agent_name="summarizer_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "Summarize..."}],
            input_text="article text",
            output_schema=SummarizerOutput,
        )

    assert isinstance(result["result"], SummarizerOutput)
    # Repair retry uses default ceiling (not the higher _RETRY_MAX_COMPLETION_TOKENS)
    calls = mock_create.call_args_list
    assert len(calls) == 2
    second_kwargs = calls[1].kwargs if calls[1].kwargs else calls[1][1]
    # Repair uses default (not the truncation retry ceiling)
    assert second_kwargs.get("max_completion_tokens") == _DEFAULT_MAX_COMPLETION_TOKENS
