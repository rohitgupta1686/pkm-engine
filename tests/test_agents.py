"""
Agent integration tests — golden-fixture tests for all PKM pipeline agents.

Structure:
  - TestReaderAgent: golden-fixture + agent_runs write tests (plan 02-02)
  - TestSummarizerAgent: golden-fixture + chunk_id rule + repair-retry tests (plan 02-03)
  - TestConceptExtractor: golden-fixture test (plan 02-03)
  - TestKGAgent: golden-fixture test (plan 02-04)
"""

from __future__ import annotations

import datetime
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pydantic
import pytest

from pkm.agents.concept_extractor import ConceptExtractor
from pkm.agents.kg_agent import KGAgent
from pkm.agents.reader_agent import ReaderAgent
from pkm.agents.summarizer_agent import SummarizerAgent
from pkm.llm.models import SONNET
from pkm.schemas.agent_io import ConceptExtractorOutput, KGAgentOutput, SummarizerOutput

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
    def test_summarizer_agent_golden(self, db_conn):
        """
        Golden-fixture test: mock LLM returns a parsed SummarizerOutput instance;
        run() returns a SummarizerOutput; agent_runs row written with status='ok'.
        """
        fixture_text = (_FIXTURES / "golden_summarizer_output.json").read_text()
        golden = SummarizerOutput.model_validate(json.loads(fixture_text))

        mock_llm_client = build_mock_llm_client(db_conn, golden)
        agent = SummarizerAgent()
        result = agent.run(mock_llm_client, input_text="some text")

        assert isinstance(result, SummarizerOutput), "run() must return a SummarizerOutput"
        assert result.thesis, "thesis must be a non-empty string"

        row = db_conn.execute(
            "SELECT status FROM agent_runs WHERE agent='summarizer_agent'"
        ).fetchone()
        assert row is not None, "agent_runs must contain a row for summarizer_agent"
        assert row[0] == "ok", f"Expected status='ok', got {row[0]!r}"

    def test_summarizer_chunk_id_rule(self, db_conn):
        """
        Data contract (AGNT-02/spec AD-6): any KeyClaim with chunk_id == 'null'
        must have confidence <= 0.5.
        """
        fixture_text = (_FIXTURES / "golden_summarizer_output.json").read_text()
        golden = SummarizerOutput.model_validate(json.loads(fixture_text))

        mock_llm_client = build_mock_llm_client(db_conn, golden)
        agent = SummarizerAgent()
        result = agent.run(mock_llm_client, input_text="some text")

        for claim in result.key_claims:
            if claim.chunk_id == "null":
                assert claim.confidence <= 0.5, (
                    f"Claim with chunk_id='null' must have confidence <= 0.5, "
                    f"got {claim.confidence}: {claim.statement!r}"
                )

    def test_repair_retry_propagates_on_double_failure(self, db_conn):
        """
        When the API returns schema-invalid JSON both on initial call and repair attempt,
        LLMClient._extract_result must propagate the pydantic.ValidationError (AGNT-05).
        """
        from pkm.llm.client import LLMClient

        llm_client = LLMClient(db_conn, api_key="test-key")

        malformed_content = MagicMock()
        malformed_content.type = "tool_use"
        malformed_content.name = "structured_output"
        malformed_content.input = {"bad_field": "wrong"}

        fake_response = MagicMock()
        fake_response.usage.input_tokens = 5
        fake_response.usage.output_tokens = 5
        fake_response.content = [malformed_content]

        with patch("pkm.llm.client.anthropic.Anthropic") as MockAnthropic:
            mock_instance = MockAnthropic.return_value
            mock_instance.messages.create.return_value = fake_response

            # Re-create LLMClient so it uses the patched Anthropic
            patched_client = LLMClient(db_conn, api_key="test-key")

            with pytest.raises(pydantic.ValidationError):
                patched_client.call(
                    agent_name="summarizer_agent",
                    model=SONNET,
                    prompt_version="v1",
                    messages=[{"role": "user", "content": "test"}],
                    input_text="test",
                    output_schema=SummarizerOutput,
                )


class TestConceptExtractor:
    def test_concept_extractor_golden(self, db_conn):
        """
        Golden-fixture test: mock LLM returns a parsed ConceptExtractorOutput instance;
        run() returns a ConceptExtractorOutput; agent_runs row written with status='ok'.
        """
        fixture_text = (_FIXTURES / "golden_extractor_output.json").read_text()
        golden = ConceptExtractorOutput.model_validate(json.loads(fixture_text))

        mock_llm_client = build_mock_llm_client(db_conn, golden)
        agent = ConceptExtractor()
        result = agent.run(mock_llm_client, input_text="some text")

        assert isinstance(result, ConceptExtractorOutput), (
            "run() must return a ConceptExtractorOutput"
        )
        assert len(result.claims) >= 1, "claims list must have at least one entry"
        assert len(result.concept_matches) >= 1, "concept_matches must have at least one entry"

        row = db_conn.execute(
            "SELECT status FROM agent_runs WHERE agent='concept_extractor'"
        ).fetchone()
        assert row is not None, "agent_runs must contain a row for concept_extractor"
        assert row[0] == "ok", f"Expected status='ok', got {row[0]!r}"


class TestKGAgent:
    def test_kg_agent_golden(self, db_conn):
        """
        Golden-fixture test: mock LLM returns a parsed KGAgentOutput instance;
        run() returns a KGAgentOutput; agent_runs row written with status='ok'.
        """
        fixture_text = (_FIXTURES / "golden_kg_output.json").read_text()
        golden = KGAgentOutput.model_validate(json.loads(fixture_text))

        mock_llm_client = build_mock_llm_client(db_conn, golden)
        agent = KGAgent()
        result = agent.run(mock_llm_client, input_text="some claims text")

        assert isinstance(result, KGAgentOutput), "run() must return a KGAgentOutput"
        assert len(result.nodes) >= 1, "nodes list must have at least one entry"
        assert isinstance(result.relationships, list), "relationships must be a list"

        row = db_conn.execute(
            "SELECT status FROM agent_runs WHERE agent='kg_agent'"
        ).fetchone()
        assert row is not None, "agent_runs must contain a row for kg_agent"
        assert row[0] == "ok", f"Expected status='ok', got {row[0]!r}"
