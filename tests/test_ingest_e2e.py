"""
End-to-end ingest test for the PKM pipeline.

Tests:
  1. test_ingest_full_chain  — full pipeline: source page + concept pages + candidate claims + log
  2. test_ingest_rerun_is_noop — idempotent no-op: 0 new rows/files/LLM calls, deduped=True

Uses mocked LLM (no real API calls) and an in-memory SQLite DB (from db_conn fixture).
"""

from __future__ import annotations

import datetime
import re
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pkm.pipeline.ingest import run_ingest
from pkm.schemas.agent_io import (
    ConceptExtractorOutput,
    ConceptMatch,
    GraphNode,
    KGAgentOutput,
    KeyClaim,
    SummarizerOutput,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FIXTURE_RAW = Path(__file__).parent / "fixtures" / "e2e_article.md"

# Fixed source hash from the fixture article
# (computed from the content — must match sha256_content of the file text)


def _load_raw_text() -> str:
    return _FIXTURE_RAW.read_text(encoding="utf-8")


def _make_summarizer_output(chunk_id_str: str) -> SummarizerOutput:
    """Build a SummarizerOutput with real chunk_ids derived from the source."""
    return SummarizerOutput(
        thesis="High operating leverage businesses convert revenue growth into outsized profit gains.",
        key_claims=[
            KeyClaim(
                statement="Operating leverage measures how revenue growth translates to operating income growth.",
                subject="operating leverage",
                predicate="measures",
                object="revenue-to-income translation",
                claim_type="definition",
                chunk_id=chunk_id_str,
                confidence=0.9,
            ),
            KeyClaim(
                statement="Software companies exhibit high operating leverage due to near-zero marginal cost.",
                subject="software companies",
                predicate="exhibit",
                object="high operating leverage",
                claim_type="fact",
                chunk_id=chunk_id_str,
                confidence=0.85,
            ),
        ],
        caveats=["Based on general business analysis, not a specific company."],
        summary_confidence=0.88,
    )


def _make_extractor_output(chunk_id_str: str) -> ConceptExtractorOutput:
    """Build a ConceptExtractorOutput with at least one concept match."""
    return ConceptExtractorOutput(
        claims=[
            KeyClaim(
                statement="Operating leverage amplifies profit growth when fixed costs are covered.",
                subject="operating leverage",
                predicate="amplifies",
                object="profit growth",
                claim_type="causal",
                chunk_id=chunk_id_str,
                confidence=0.87,
            ),
        ],
        concept_matches=[
            ConceptMatch(
                concept_name="Operating Leverage",
                claim_indices=[0],
                confidence=0.92,
            ),
        ],
    )


def _make_kg_output() -> KGAgentOutput:
    """Build a minimal KGAgentOutput."""
    return KGAgentOutput(
        nodes=[
            GraphNode(
                id="n_operating_leverage",
                label="Concept",
                name="Operating Leverage",
                properties={"domain": "finance"},
                confidence=0.9,
                provenance=["e2e_article"],
            ),
        ],
        relationships=[],
    )


def _build_multi_agent_mock(conn) -> MagicMock:
    """
    Build a MagicMock LLM client whose .call() returns the correct result
    per agent_name kwarg.

    Uses a side_effect that branches on agent_name and writes real agent_runs rows
    (mimicking build_mock_llm_client from test_agents.py).
    """
    from pkm.ingest.hashing import sha256_content, source_id_from_hash, chunk_id

    # We need the chunk_id to build realistic outputs.
    # Compute the source's hash and first chunk_id from the fixture article.
    raw_text = _load_raw_text()
    content_hash = sha256_content(raw_text)
    source_hash12 = content_hash[:12]
    first_chunk_id = chunk_id(source_hash12, 0)

    # Pre-build agent outputs
    summarizer_result = _make_summarizer_output(first_chunk_id)
    extractor_result = _make_extractor_output(first_chunk_id)
    kg_result = _make_kg_output()

    # Map agent name -> result
    results_by_agent = {
        "reader_agent": raw_text,  # Reader returns a plain string
        "summarizer_agent": summarizer_result,
        "concept_extractor": extractor_result,
        "kg_agent": kg_result,
    }

    mock_client = MagicMock()

    def _mock_call(**kwargs):
        agent_name = kwargs.get("agent_name", "unknown_agent")
        run_id = "run_" + uuid.uuid4().hex[:20]
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        source_id = kwargs.get("source_id")
        conn.execute(
            "INSERT OR REPLACE INTO agent_runs "
            "(id, agent, source_id, input_hash, model, "
            "tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                agent_name,
                source_id,
                "e2e_test_hash_" + agent_name[:8],
                "mock_model",
                10,
                20,
                0.0,
                "ok",
                None,
                now,
                now,
            ),
        )
        conn.commit()
        result = results_by_agent.get(agent_name, "")
        return {
            "cached": False,
            "input_hash": "e2e_test_hash_" + agent_name[:8],
            "result": result,
            "tokens_in": 10,
            "tokens_out": 20,
        }

    mock_client.call.side_effect = _mock_call
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestFullChain:
    """Test the full pipeline end-to-end with a mock LLM."""

    def test_ingest_full_chain(self, db_conn, tmp_path):
        """Run the full ingest and verify all outputs exist and are correct."""
        # Arrange
        raw_text = _load_raw_text()
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        (vault_root / "wiki" / "sources").mkdir(parents=True)
        (vault_root / "wiki" / "concepts").mkdir(parents=True)

        mock_llm = _build_multi_agent_mock(db_conn)

        # Act
        result = run_ingest(
            conn=db_conn,
            llm_client=mock_llm,
            vault_root=vault_root,
            raw_text=raw_text,
            raw_path="raw/2026/06/e2e_article.md",
            new_only=True,
        )

        # Assert: result shape
        assert result["deduped"] is False
        assert result["source_id"].startswith("src_")
        assert result["wiki_path"].startswith("wiki/sources/")
        assert result["n_claims"] >= 1
        assert result["n_concepts"] >= 1

        # Assert: exactly 1 sources row
        sources = db_conn.execute("SELECT id FROM sources").fetchall()
        assert len(sources) == 1

        # Assert: >=1 chunks row
        chunks = db_conn.execute("SELECT id FROM chunks WHERE source_id = ?", (result["source_id"],)).fetchall()
        assert len(chunks) >= 1

        # Assert: >=1 claims row, all with status='candidate'
        claims = db_conn.execute(
            "SELECT id, status FROM claims WHERE source_id = ?", (result["source_id"],)
        ).fetchall()
        assert len(claims) >= 1
        for _claim_id, status in claims:
            assert status == "candidate", f"Expected status='candidate', got '{status}'"

        # Assert: source page file exists
        source_page = vault_root / result["wiki_path"]
        assert source_page.exists(), f"Source page not found: {source_page}"
        source_content = source_page.read_text(encoding="utf-8")

        # Assert: source page has ## Key Claims section
        assert "## Key Claims" in source_content

        # Assert: every claim bullet matches ^cite:<source_id>#<chunk_id>
        source_id = result["source_id"]
        claim_pattern = re.compile(r"\^cite:src_[a-f0-9]+#")
        claim_lines = [
            line for line in source_content.splitlines()
            if line.startswith("- ") and "^cite:" in line
        ]
        assert len(claim_lines) >= 1, "No claim lines with ^cite: found in source page"
        for line in claim_lines:
            assert claim_pattern.search(line), (
                f"Claim line does not match ^cite:src_<hex># pattern: {line!r}"
            )

        # Assert: ## Extracted Concepts section has [[wikilink]]
        assert "## Extracted Concepts" in source_content
        assert "[[" in source_content, "Source page has no [[wikilink]] in Extracted Concepts"

        # Assert: >=1 concept page file exists under wiki/concepts/
        concept_files = list((vault_root / "wiki" / "concepts").glob("*.md"))
        assert len(concept_files) >= 1, "No concept pages written under wiki/concepts/"

        # Assert: log.md exists and has exactly 1 line
        log_path = vault_root / "log.md"
        assert log_path.exists(), "log.md not created"
        log_lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(log_lines) == 1, f"Expected 1 log line, got {len(log_lines)}: {log_lines}"


class TestIngestRerUnIsNoop:
    """Test that re-running ingest on the same content is a no-op."""

    def test_ingest_rerun_is_noop(self, db_conn, tmp_path):
        """Second call with same inputs produces 0 new rows, files, LLM calls, deduped=True."""
        # Arrange
        raw_text = _load_raw_text()
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        (vault_root / "wiki" / "sources").mkdir(parents=True)
        (vault_root / "wiki" / "concepts").mkdir(parents=True)

        mock_llm = _build_multi_agent_mock(db_conn)

        # Act: first run
        result1 = run_ingest(
            conn=db_conn,
            llm_client=mock_llm,
            vault_root=vault_root,
            raw_text=raw_text,
            raw_path="raw/2026/06/e2e_article.md",
            new_only=True,
        )
        assert result1["deduped"] is False

        # Record state after first run
        source_count_1 = db_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        chunk_count_1 = db_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        claim_count_1 = db_conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        wiki_files_1 = set(
            str(p.relative_to(vault_root))
            for p in vault_root.rglob("*.md")
        )
        log_lines_1 = [
            l for l in (vault_root / "log.md").read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        call_count_after_run1 = mock_llm.call.call_count

        # Act: second run (same inputs, new_only=True)
        result2 = run_ingest(
            conn=db_conn,
            llm_client=mock_llm,
            vault_root=vault_root,
            raw_text=raw_text,
            raw_path="raw/2026/06/e2e_article.md",
            new_only=True,
        )

        # Assert: deduped=True
        assert result2["deduped"] is True
        assert result2["source_id"] == result1["source_id"]

        # Assert: no new sources/chunks/claims rows
        source_count_2 = db_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        chunk_count_2 = db_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        claim_count_2 = db_conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        assert source_count_2 == source_count_1, "Unexpected new sources rows on re-run"
        assert chunk_count_2 == chunk_count_1, "Unexpected new chunks rows on re-run"
        assert claim_count_2 == claim_count_1, "Unexpected new claims rows on re-run"

        # Assert: no new files under vault
        wiki_files_2 = set(
            str(p.relative_to(vault_root))
            for p in vault_root.rglob("*.md")
        )
        assert wiki_files_2 == wiki_files_1, (
            f"New files appeared on re-run: {wiki_files_2 - wiki_files_1}"
        )

        # Assert: log.md still has exactly 1 line (no second append on no-op path)
        log_lines_2 = [
            l for l in (vault_root / "log.md").read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert len(log_lines_2) == 1, (
            f"Expected 1 log line after re-run, got {len(log_lines_2)}: {log_lines_2}"
        )

        # Assert: 0 new LLM calls on the second run
        call_count_after_run2 = mock_llm.call.call_count
        new_llm_calls = call_count_after_run2 - call_count_after_run1
        assert new_llm_calls == 0, (
            f"Expected 0 new LLM calls on re-run, got {new_llm_calls}"
        )
