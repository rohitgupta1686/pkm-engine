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
from unittest.mock import MagicMock, patch

import pytest

from pkm.pipeline.ingest import _has_prior_agent_runs, run_ingest
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


# ---------------------------------------------------------------------------
# Regression tests for CR-03, CR-02, CR-04 (gap-closure plan 03-04)
# ---------------------------------------------------------------------------


class TestPartialRunRecovery:
    """CR-03: _has_prior_agent_runs must require ALL four agents, not just one."""

    def test_has_prior_agent_runs_requires_all_four(self, db_conn):
        """Unit test: 1, 2, 3 agents -> False; all 4 -> True."""
        from pkm.ingest.hashing import sha256_content, source_id_from_hash
        from pkm.store.registry import upsert_source

        raw_text = _load_raw_text()
        content_hash = sha256_content(raw_text)
        source_id = source_id_from_hash(content_hash)
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

        # Insert the source row so FK constraints pass
        upsert_source(db_conn, {
            "id": source_id,
            "content_hash": content_hash,
            "type": "Article",
            "title": "Test",
            "author": "",
            "url": "",
            "date_saved": now,
            "raw_path": "raw/test.md",
            "status": "captured",
            "created_at": now,
            "updated_at": now,
        })

        all_roles = ("reader_agent", "summarizer_agent", "concept_extractor", "kg_agent")

        # 0 agents -> False
        assert _has_prior_agent_runs(db_conn, source_id) is False

        # Insert 1, 2, 3 agents and verify still False each time
        for i, role in enumerate(all_roles[:3]):
            run_id = "run_" + uuid.uuid4().hex[:20]
            db_conn.execute(
                "INSERT OR REPLACE INTO agent_runs "
                "(id, agent, source_id, input_hash, model, "
                "tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, role, source_id, f"hash_{role}", "mock", 1, 1, 0.0, "ok", None, now, now),
            )
            db_conn.commit()
            assert _has_prior_agent_runs(db_conn, source_id) is False, (
                f"Expected False with {i + 1} agent(s), got True"
            )

        # Insert the 4th agent -> True
        run_id = "run_" + uuid.uuid4().hex[:20]
        db_conn.execute(
            "INSERT OR REPLACE INTO agent_runs "
            "(id, agent, source_id, input_hash, model, "
            "tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "kg_agent", source_id, "hash_kg_agent", "mock", 1, 1, 0.0, "ok", None, now, now),
        )
        db_conn.commit()
        assert _has_prior_agent_runs(db_conn, source_id) is True

    def test_partial_run_not_skipped_on_new_only(self, db_conn, tmp_path):
        """CR-03: A source with only reader_agent ok is NOT short-circuited (deduped=False)."""
        from pkm.ingest.hashing import sha256_content, source_id_from_hash
        from pkm.store.registry import upsert_source

        raw_text = _load_raw_text()
        content_hash = sha256_content(raw_text)
        source_id = source_id_from_hash(content_hash)
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        (vault_root / "wiki" / "sources").mkdir(parents=True)
        (vault_root / "wiki" / "concepts").mkdir(parents=True)

        # Manually insert source row + one reader_agent ok row (simulates interrupted run)
        upsert_source(db_conn, {
            "id": source_id,
            "content_hash": content_hash,
            "type": "Article",
            "title": "Operating Leverage and Business Scalability",
            "author": "",
            "url": "",
            "date_saved": now,
            "raw_path": "raw/2026/06/e2e_article.md",
            "status": "captured",
            "created_at": now,
            "updated_at": now,
        })
        run_id = "run_" + uuid.uuid4().hex[:20]
        db_conn.execute(
            "INSERT OR REPLACE INTO agent_runs "
            "(id, agent, source_id, input_hash, model, "
            "tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "reader_agent", source_id, "hash_reader", "mock", 1, 1, 0.0, "ok", None, now, now),
        )
        db_conn.commit()

        # Run ingest with multi-agent mock — should NOT short-circuit (deduped=False)
        mock_llm = _build_multi_agent_mock(db_conn)
        result = run_ingest(
            conn=db_conn,
            llm_client=mock_llm,
            vault_root=vault_root,
            raw_text=raw_text,
            raw_path="raw/2026/06/e2e_article.md",
            new_only=True,
        )
        assert result["deduped"] is False, (
            "Expected deduped=False for partial run (only reader_agent), "
            f"but got deduped={result['deduped']}"
        )


class TestSourceTypeNormalization:
    """CR-02: source_type must normalize to a CHECK-valid value before DB insert."""

    def _run_with_type(self, raw_type: str, db_conn, tmp_path) -> str:
        """Build a minimal raw document with the given type field and run ingest."""
        raw_text = (
            f"---\ntitle: Type Test\ntype: {raw_type}\ndate_saved: 2026-01-01T00:00:00Z\n---\n"
            "Some body content for type normalization test.\n"
        )
        vault_root = tmp_path / "vault"
        vault_root.mkdir(exist_ok=True)
        (vault_root / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (vault_root / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)

        mock_llm = _build_multi_agent_mock_for_text(db_conn, raw_text)
        result = run_ingest(
            conn=db_conn,
            llm_client=mock_llm,
            vault_root=vault_root,
            raw_text=raw_text,
            raw_path=f"raw/type_test_{raw_type.replace(' ', '_')}.md",
            new_only=False,
        )
        row = db_conn.execute(
            "SELECT type FROM sources WHERE id = ?", (result["source_id"],)
        ).fetchone()
        assert row is not None
        return row[0]

    def test_lowercase_type_normalizes(self, db_conn, tmp_path):
        """CR-02: 'article' (lowercase) normalizes to 'Article'."""
        result_type = self._run_with_type("article", db_conn, tmp_path)
        assert result_type == "Article", f"Expected 'Article', got '{result_type}'"

    def test_invalid_type_falls_back_to_article(self, db_conn, tmp_path):
        """CR-02: 'Blog Post' (not in CHECK set) normalizes to 'Article'."""
        result_type = self._run_with_type("Blog Post", db_conn, tmp_path)
        assert result_type == "Article", f"Expected 'Article' fallback, got '{result_type}'"


class TestRollbackAtomicity:
    """CR-04: A mid-run failure must roll back ALL DB writes from Steps 4-8."""

    def test_chunk_rollback_on_claim_insert_failure(self, db_conn, tmp_path):
        """CR-04: chunks inserted in Step 4 are rolled back when insert_claim raises."""
        from pkm.ingest.hashing import sha256_content, source_id_from_hash

        raw_text = _load_raw_text()
        content_hash = sha256_content(raw_text)
        source_id = source_id_from_hash(content_hash)

        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        (vault_root / "wiki" / "sources").mkdir(parents=True)
        (vault_root / "wiki" / "concepts").mkdir(parents=True)

        mock_llm = _build_multi_agent_mock(db_conn)

        # Patch insert_claim to raise on first call (Step 6 — after chunks written in Step 4)
        with patch("pkm.pipeline.ingest.insert_claim", side_effect=RuntimeError("forced failure")):
            with pytest.raises(RuntimeError, match="forced failure"):
                run_ingest(
                    conn=db_conn,
                    llm_client=mock_llm,
                    vault_root=vault_root,
                    raw_text=raw_text,
                    raw_path="raw/2026/06/e2e_article.md",
                    new_only=False,
                )

        # Chunks should have been rolled back (0 rows despite Step 4 executing first)
        chunk_count = db_conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE source_id = ?", (source_id,)
        ).fetchone()[0]
        assert chunk_count == 0, (
            f"Expected 0 chunks after rollback, got {chunk_count} — partial state was committed"
        )


# ---------------------------------------------------------------------------
# Helper: multi-agent mock for arbitrary raw text (used by source_type tests)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Regression tests for CR-01 (gap-closure plan 03-05)
# ---------------------------------------------------------------------------


class TestConceptFrontMatterKeyOrder:
    """CR-01: _render_front_matter must iterate key_order, not the hardcoded source tuple."""

    def test_render_front_matter_respects_key_order(self):
        """key_order controls emission order; keys outside key_order are omitted."""
        from pkm.store.vault import _render_front_matter

        output = _render_front_matter(
            {"id": "x", "title": "t"},
            key_order=("title", "id"),
        )
        title_pos = output.index("title:")
        id_pos = output.index("id:")
        assert title_pos < id_pos, (
            f"Expected 'title:' before 'id:' with key_order=('title','id'), "
            f"but title_pos={title_pos} >= id_pos={id_pos}"
        )

    def test_render_front_matter_omits_keys_not_in_order(self):
        """A field present in fields but absent from key_order is NOT emitted."""
        from pkm.store.vault import _render_front_matter

        output = _render_front_matter(
            {"id": "x", "title": "t"},
            key_order=("id",),
        )
        # 'title' must not appear in the body lines (the --- delimiters are OK)
        body_lines = [ln for ln in output.splitlines() if ln.startswith("title")]
        assert not body_lines, (
            f"'title' appeared in output despite not being in key_order: {output!r}"
        )

    def test_concept_page_follows_concept_key_order(self, db_conn, tmp_path, monkeypatch):
        """write_concept_page passes _FRONT_MATTER_KEYS_CONCEPT to _render_front_matter.

        Monkeypatch _FRONT_MATTER_KEYS_CONCEPT to a reordered tuple (swap id/title).
        Assert the rendered concept page reflects the patched order, not the source order.
        """
        import datetime
        import pkm.store.vault as vault_mod
        from pkm.store.vault import _FRONT_MATTER_KEYS_CONCEPT, _FRONT_MATTER_KEYS_SOURCE
        from pkm.store.registry import upsert_concept

        # Build a patched concept tuple with title before id (swapped from the default)
        patched_concept_keys = ("title", "id") + tuple(
            k for k in _FRONT_MATTER_KEYS_CONCEPT if k not in ("title", "id")
        )
        # Confirm source tuple still starts with id (so the orders diverge)
        assert _FRONT_MATTER_KEYS_SOURCE[0] == "id", (
            "Precondition failed: source tuple should start with 'id'"
        )

        monkeypatch.setattr(vault_mod, "_FRONT_MATTER_KEYS_CONCEPT", patched_concept_keys)

        # Seed a concept row
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        concept_id = "cpt_operating-leverage"
        upsert_concept(db_conn, {
            "id": concept_id,
            "name": "Operating Leverage",
            "definition": "",
            "domain": "finance",
            "wiki_path": "",
            "created_at": now,
            "updated_at": now,
        })

        vault_root = tmp_path / "vault"
        (vault_root / "wiki" / "concepts").mkdir(parents=True)

        vault_mod.write_concept_page(
            conn=db_conn,
            vault_root=vault_root,
            concept_id=concept_id,
            name="Operating Leverage",
            source_slug="some-source",
        )

        concept_file = vault_root / "wiki" / "concepts" / "operating-leverage.md"
        assert concept_file.exists(), "Concept page was not written"
        content = concept_file.read_text(encoding="utf-8")

        # Under the patched concept key order, 'title:' must appear before 'id:'
        title_pos = content.index("title:")
        id_pos = content.index("id:")
        assert title_pos < id_pos, (
            f"Concept page did NOT follow the patched concept key order "
            f"(title_pos={title_pos}, id_pos={id_pos}). "
            f"This means write_concept_page is using the source key order instead."
        )


# ---------------------------------------------------------------------------
# Helper: multi-agent mock for arbitrary raw text (used by source_type tests)
# ---------------------------------------------------------------------------

def _build_multi_agent_mock_for_text(conn, raw_text: str) -> MagicMock:
    """Like _build_multi_agent_mock but accepts arbitrary raw_text instead of fixture."""
    from pkm.ingest.hashing import sha256_content, source_id_from_hash, chunk_id as _chunk_id

    content_hash = sha256_content(raw_text)
    source_hash12 = content_hash[:12]
    first_chunk_id = _chunk_id(source_hash12, 0)

    summarizer_result = _make_summarizer_output(first_chunk_id)
    extractor_result = _make_extractor_output(first_chunk_id)
    kg_result = _make_kg_output()

    results_by_agent = {
        "reader_agent": raw_text,
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
                run_id, agent_name, source_id,
                "test_hash_" + agent_name[:8],
                "mock_model", 10, 20, 0.0, "ok", None, now, now,
            ),
        )
        conn.commit()
        result = results_by_agent.get(agent_name, "")
        return {
            "cached": False,
            "input_hash": "test_hash_" + agent_name[:8],
            "result": result,
            "tokens_in": 10,
            "tokens_out": 20,
        }

    mock_client.call.side_effect = _mock_call
    return mock_client
