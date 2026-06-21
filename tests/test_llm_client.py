"""
Dedicated unit tests for the OpenAI-backed LLMClient and per-run cost cap.

Covers the two load-bearing shapes introduced in plan 04-04:
  - _to_openai_strict_schema (pydantic -> OpenAI strict json_schema)
  - pkm.llm.pricing.compute_cost + batch_ingest per-run cost/token cap
Plus a regression test for the old cost_usd=0.0 bug (client.py:220).
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from pkm.batch import batch_ingest
from pkm.llm.client import LLMClient, _to_openai_strict_schema
from pkm.llm.models import MINI
from pkm.llm.pricing import compute_cost
from pkm.schemas.agent_io import SummarizerOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_object_nodes(schema: dict) -> list[dict]:
    """Return every dict node in the schema that has a 'properties' key."""
    nodes: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if "properties" in node:
                nodes.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return nodes


def _openai_response(content: str, prompt_tokens=10, completion_tokens=5, cached=0):
    resp = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.prompt_tokens_details.cached_tokens = cached
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


# ---------------------------------------------------------------------------
# _to_openai_strict_schema
# ---------------------------------------------------------------------------

def test_strict_schema_sets_additional_properties_false_and_required_everywhere():
    schema = _to_openai_strict_schema(SummarizerOutput.model_json_schema())
    for node in _collect_object_nodes(schema):
        assert node.get("additionalProperties") is False, (
            f"object node missing additionalProperties=false: {list(node.get('properties', {}))}"
        )
        assert set(node["required"]) == set(node["properties"].keys()), (
            f"required must list every property: {node['required']} vs {list(node['properties'])}"
        )


def test_strict_schema_collapses_nullable_optional():
    class M(BaseModel):
        x: int | None = None
        y: str = "y"

    schema = _to_openai_strict_schema(M.model_json_schema())
    props = schema["properties"]
    # x must be required (strict) and nullable as type:[integer,null]
    assert "x" in schema["required"]
    assert props["x"]["type"] == ["integer", "null"], props["x"]


# ---------------------------------------------------------------------------
# compute_cost
# ---------------------------------------------------------------------------

def test_compute_cost_known_model():
    # 1000 prompt (200 cached), 500 completion
    # = 800*0.75/1e6 + 200*0.075/1e6 + 500*4.50/1e6
    expected = (800 * 0.75 + 200 * 0.075 + 500 * 4.50) / 1_000_000
    assert compute_cost(MINI, 1000, 200, 500) == pytest.approx(expected)


def test_compute_cost_cached_only():
    expected = 1000 * 0.075 / 1_000_000
    assert compute_cost(MINI, 1000, 1000, 0) == pytest.approx(expected)


def test_compute_cost_unknown_model_raises():
    with pytest.raises(KeyError):
        compute_cost("does-not-exist", 10, 0, 5)


# ---------------------------------------------------------------------------
# call() writes real cost_usd (regression for client.py:220 cost_usd=0.0 bug)
# ---------------------------------------------------------------------------

def test_call_writes_real_cost(db_conn):
    resp = _openai_response("ok")
    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = resp
        client = LLMClient(db_conn, api_key="test-key")
        client.call(
            agent_name="reader_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "test"}],
            input_text="hello",
        )
    cost = db_conn.execute("SELECT cost_usd FROM agent_runs").fetchone()[0]
    assert cost > 0.0, f"cost_usd must be real (>0), got {cost}"


# ---------------------------------------------------------------------------
# Repair-retry: success on second attempt
# ---------------------------------------------------------------------------

def test_repair_retry_success_on_second(db_conn):
    valid = json.dumps({
        "thesis": "t", "key_claims": [], "caveats": [], "summary_confidence": 0.5,
    })
    invalid = '{"bad_field": "wrong"}'
    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = [
            _openai_response(invalid), _openai_response(valid),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        result = client.call(
            agent_name="summarizer_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "test"}],
            input_text="test",
            output_schema=SummarizerOutput,
        )
    assert isinstance(result["result"], SummarizerOutput)


# ---------------------------------------------------------------------------
# B-05-02 durable-summary fix: cache hit restores the real output (output_json)
# ---------------------------------------------------------------------------

def test_cache_hit_restores_real_output(db_conn):
    """A second call (cache hit) returns the REAL SummarizerOutput, not a placeholder.

    Regression for the "(summary unavailable — cached run)" bug: agent_runs now
    persists output_json so a cache hit reconstructs the validated result with no
    API call.
    """
    valid = json.dumps({
        "thesis": "Anthropic is a target precisely because it is succeeding.",
        "key_claims": [], "caveats": [], "summary_confidence": 0.9,
    })
    with patch("pkm.llm.client.openai.OpenAI") as MockOpenAI:
        # Only ONE API response is provided — a second create() call would raise
        # StopIteration, proving the cache hit makes zero API calls.
        MockOpenAI.return_value.chat.completions.create.side_effect = [
            _openai_response(valid),
        ]
        client = LLMClient(db_conn, api_key="test-key")
        kwargs = dict(
            agent_name="summarizer_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "x"}],
            input_text="some article text",
            output_schema=SummarizerOutput,
        )
        first = client.call(**kwargs)
        second = client.call(**kwargs)

    assert first["cached"] is False
    assert second["cached"] is True
    # The cache hit carries the restored, validated result — the load-bearing fix.
    assert "result" in second, "cache hit must restore the stored output_json"
    assert isinstance(second["result"], SummarizerOutput)
    assert second["result"].thesis == "Anthropic is a target precisely because it is succeeding."
    # And output_json was actually persisted on the ok-row.
    stored = db_conn.execute(
        "SELECT output_json FROM agent_runs WHERE agent = 'summarizer_agent' AND status = 'ok'"
    ).fetchone()[0]
    assert stored is not None and "Anthropic is a target" in stored


def test_legacy_cache_row_without_output_json_still_signals_cache_hit(db_conn):
    """An ok-row with NULL output_json (pre-004 legacy) yields a cache hit with no result.

    Preserves the historical contract so BaseAgent.run() still raises RuntimeError
    and the pipeline's own recovery path runs.
    """
    now = "2026-01-01T00:00:00Z"
    db_conn.execute(
        "INSERT INTO agent_runs (id, agent, source_id, input_hash, model, tokens_in, "
        "tokens_out, cost_usd, status, error, started_at, finished_at, output_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("run_legacy", "summarizer_agent", None,
         "legacyhash", MINI, 1, 1, 0.0, "ok", None, now, now, None),
    )
    db_conn.commit()
    with patch("pkm.llm.client.openai.OpenAI"):
        client = LLMClient(db_conn, api_key="test-key")
        # Force the same input_hash by monkeypatching the hash to the legacy value.
        client._make_input_hash = lambda *a, **k: "legacyhash"  # type: ignore[method-assign]
        out = client.call(
            agent_name="summarizer_agent", model=MINI, prompt_version="v1",
            messages=[{"role": "user", "content": "x"}], input_text="x",
            output_schema=SummarizerOutput,
        )
    assert out["cached"] is True
    assert "result" not in out


# ---------------------------------------------------------------------------
# Per-run cost/token cap (batch_ingest)
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path, n_files: int = 2) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    for i in range(n_files):
        (raw / f"f{i}.md").write_text(f"content {i}")
    return tmp_path


def _insert_run(conn, cost_usd: float, tokens: int) -> None:
    """Insert an agent_runs row attributed to 'now' so it lands in the run window."""
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO agent_runs (id, agent, source_id, input_hash, model, tokens_in, "
        "tokens_out, cost_usd, status, error, started_at, finished_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("run_test", "reader_agent", None, "h" + str(tokens), MINI,
         tokens, 0, cost_usd, "ok", None, now, now),
    )
    conn.commit()


def test_cap_abort_cost(db_conn, tmp_path):
    vault = _make_vault(tmp_path)

    def fake_run_ingest(conn, llm_client, vault_root, raw_text, raw_path, new_only, **kwargs):
        _insert_run(conn, cost_usd=1.0, tokens=10)
        return {"deduped": False, "source_id": "s", "wiki_path": "w", "n_claims": 0, "n_concepts": 0, "embed": {}}

    with patch("pkm.batch.run_ingest", fake_run_ingest):
        result = batch_ingest(db_conn, MagicMock(), vault, run_cost_cap_usd=0.5)
    assert result["aborted"] is True
    assert result["abort_reason"] == "cost_cap"
    assert result["processed"] == 1  # first file processed, then cap trips on 2nd


def test_cap_abort_tokens(db_conn, tmp_path):
    vault = _make_vault(tmp_path)

    def fake_run_ingest(conn, llm_client, vault_root, raw_text, raw_path, new_only, **kwargs):
        _insert_run(conn, cost_usd=0.01, tokens=20)
        return {"deduped": False, "source_id": "s", "wiki_path": "w", "n_claims": 0, "n_concepts": 0, "embed": {}}

    with patch("pkm.batch.run_ingest", fake_run_ingest):
        result = batch_ingest(db_conn, MagicMock(), vault, run_token_cap=10)
    assert result["aborted"] is True
    assert result["abort_reason"] == "token_cap"
    assert result["processed"] == 1


def test_cap_not_tripped_under_limit(db_conn, tmp_path):
    vault = _make_vault(tmp_path, n_files=2)

    def fake_run_ingest(conn, llm_client, vault_root, raw_text, raw_path, new_only, **kwargs):
        _insert_run(conn, cost_usd=0.01, tokens=5)
        return {"deduped": False, "source_id": "s", "wiki_path": "w", "n_claims": 0, "n_concepts": 0, "embed": {}}

    with patch("pkm.batch.run_ingest", fake_run_ingest):
        result = batch_ingest(db_conn, MagicMock(), vault,
                              run_cost_cap_usd=10.0, run_token_cap=1_000_000)
    assert result["aborted"] is False
    assert result["processed"] == 2