"""
Agent integration tests — golden-fixture tests for all PKM pipeline agents.

Structure:
  - TestReaderAgent: golden-fixture + agent_runs write tests (plan 02-02)
  - TestSummarizerAgent: placeholder (plan 02-03)
  - TestConceptExtractor: placeholder (plan 02-03)
  - TestKGAgent: placeholder (plan 02-04)
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pkm.agents.reader_agent import ReaderAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


def build_mock_llm_client(conn, result_text_or_model, tokens_in: int = 10, tokens_out: int = 20):
    """
    Build a MagicMock that mimics LLMClient.call() without hitting the real API.

    The mock's .call() method:
      - Returns the expected dict (cached=False, result=result_text_or_model, tokens)
      - Writes a real agent_runs row to conn so downstream assertions work

    Args:
        conn: libsql connection (from db_conn fixture) for writing agent_runs
        result_text_or_model: the value placed in result["result"]
        tokens_in: simulated input token count
        tokens_out: simulated output token count
    """
    mock_client = MagicMock()

    def _mock_call(**kwargs):
        agent_name = kwargs.get("agent_name", "unknown_agent")
        run_id = "run_" + uuid.uuid4().hex[:20]
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        conn.execute(
            "INSERT OR REPLACE INTO agent_runs "
            "(id, agent, source_id, input_hash, model, "
            "tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                agent_name,
                None,
                "hash123",
                "mock_model",
                tokens_in,
                tokens_out,
                0.0,
                "ok",
                None,
                now,
                now,
            ),
        )
        conn.commit()
        return {
            "cached": False,
            "input_hash": "hash123",
            "result": result_text_or_model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    mock_client.call.side_effect = _mock_call
    return mock_client


def build_cache_hit_mock():
    """Build a MagicMock whose .call() returns a cache hit (cached=True)."""
    mock_client = MagicMock()
    mock_client.call.return_value = {"cached": True, "input_hash": "x"}
    return mock_client


# ---------------------------------------------------------------------------
# TestReaderAgent
# ---------------------------------------------------------------------------


class TestReaderAgent:
    def test_reader_agent_golden(self, db_conn):
        """
        Golden-fixture test: mock LLM returns golden output → ReaderAgent.run()
        returns a non-empty string containing front matter delimiters, and
        agent_runs has a row with agent='reader_agent' and status='ok'.
        """
        golden_text = (_FIXTURES / "golden_reader_output.md").read_text()
        mock_llm_client = build_mock_llm_client(db_conn, golden_text)

        agent = ReaderAgent()
        result = agent.run(
            mock_llm_client,
            input_text=(_FIXTURES / "sample_raw.md").read_text(),
        )

        assert isinstance(result, str), "ReaderAgent.run() must return a string"
        assert "---" in result, "Result must contain YAML front matter delimiters"

        row = db_conn.execute(
            "SELECT status FROM agent_runs WHERE agent='reader_agent'"
        ).fetchone()
        assert row is not None, "agent_runs must contain a row for reader_agent"
        assert row[0] == "ok", f"Expected status='ok', got {row[0]!r}"

    def test_reader_agent_agent_runs_write(self, db_conn):
        """
        Verify tokens_in and tokens_out are written correctly to agent_runs.
        """
        mock_llm_client = build_mock_llm_client(
            db_conn, "---\nid: x\n---\nbody", tokens_in=42, tokens_out=17
        )
        agent = ReaderAgent()
        agent.run(mock_llm_client, input_text="some text")

        row = db_conn.execute(
            "SELECT tokens_in, tokens_out FROM agent_runs WHERE agent='reader_agent'"
        ).fetchone()
        assert row is not None, "agent_runs row missing"
        assert row[0] == 42, f"Expected tokens_in=42, got {row[0]}"
        assert row[1] == 17, f"Expected tokens_out=17, got {row[1]}"

    def test_reader_agent_cache_hit_raises(self, db_conn):
        """
        A cache-hit response must raise RuntimeError so the pipeline knows to
        retrieve the prior result from agent_runs instead of re-processing.
        """
        mock_llm_client = build_cache_hit_mock()
        agent = ReaderAgent()
        with pytest.raises(RuntimeError):
            agent.run(mock_llm_client, input_text="some text")


# ---------------------------------------------------------------------------
# Placeholder classes for future plans
# ---------------------------------------------------------------------------


class TestSummarizerAgent:
    pass


class TestConceptExtractor:
    pass


class TestKGAgent:
    pass
