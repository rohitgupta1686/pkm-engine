"""
Idempotency test suite — Phase 1 DoD gate.

Covers:
  DATA-03: Re-ingesting same content_hash = 0 new rows in sources
  DATA-04: LLM cache dedup — second call with same input hits cache, 0 API calls
  DATA-05: sources_raw_immutable trigger fires on UPDATE OF raw_path
  DATA-06: connect() auto-migrates empty DB; connect() twice is a no-op
"""
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from pkm.config import Settings
from pkm.llm.client import LLMClient
from pkm.llm.models import MINI
from pkm.store.registry import connect, insert_claim


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _insert_source(conn, source_id: str, content_hash: str, raw_path: str) -> None:
    """Insert a minimal sources row. Commits after insert."""
    conn.execute(
        """
        INSERT INTO sources
            (id, content_hash, type, date_saved, raw_path, created_at, updated_at)
        VALUES (?, ?, 'Article', '2026-01-01T00:00:00Z', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        (source_id, content_hash, raw_path),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_auto_migration(db_conn):
    """connect() on an empty DB auto-creates all required tables (DATA-06)."""
    rows = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "sources" in names, f"'sources' missing from tables: {names}"
    assert "agent_runs" in names, f"'agent_runs' missing from tables: {names}"
    assert "graph_nodes" in names, f"'graph_nodes' missing from tables: {names}"
    assert "graph_edges" in names, f"'graph_edges' missing from tables: {names}"


def test_idempotent_migration(tmp_path):
    """connect() called twice on the same db_path raises no exception (DATA-06)."""
    db_path = str(tmp_path / "idempotent.db")
    s = Settings(openai_api_key="test-key", db_path=db_path)

    # First connect — migrates from scratch
    conn1 = connect(s)
    # Second connect — migration guards must be idempotent (IF NOT EXISTS)
    conn2 = connect(s)

    # Tables still exist after second connect
    rows = conn2.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "sources" in names


def test_source_dedup(db_conn):
    """Re-inserting the same content_hash results in exactly 1 row (DATA-03)."""
    _insert_source(db_conn, "src_aaa111bbb222", "hash_unique_abc", "raw/test.md")

    # Second insert with same content_hash must raise (UNIQUE constraint)
    with pytest.raises(Exception):
        _insert_source(db_conn, "src_xxx999yyy888", "hash_unique_abc", "raw/test2.md")

    count = db_conn.execute(
        "SELECT COUNT(*) FROM sources WHERE content_hash='hash_unique_abc'"
    ).fetchone()[0]
    assert count == 1, f"Expected 1 row, got {count}"


def test_raw_path_immutable(db_conn):
    """UPDATE sources SET raw_path raises an exception with 'immutable' in the message (DATA-05)."""
    _insert_source(db_conn, "src_imm111aaa", "hash_immutable_1", "raw/original.md")

    try:
        db_conn.execute(
            "UPDATE sources SET raw_path='raw/changed.md' WHERE id='src_imm111aaa'"
        )
        db_conn.commit()
        pytest.fail("immutability trigger did not fire — UPDATE succeeded when it should have raised")
    except Exception as e:
        assert "immutable" in str(e).lower(), (
            f"Exception raised but 'immutable' not in message: {e!r}"
        )


def test_llm_cache_dedup(db_conn):
    """
    Calling LLMClient.call() twice with identical inputs:
      (a) mock API called exactly once
      (b) second call returns cached=True
      (c) agent_runs has exactly 1 row
    (DATA-04)
    """
    # Build a mock OpenAI Chat Completions response
    mock_response = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5
    mock_response.usage.prompt_tokens_details.cached_tokens = 0
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]

    with patch("pkm.llm.client.openai.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_response

        client = LLMClient(conn=db_conn, api_key="test-key")

        call_kwargs = dict(
            agent_name="reader_agent",
            model=MINI,
            prompt_version="v1",
            messages=[{"role": "user", "content": "test"}],
            input_text="hello world",
        )

        result1 = client.call(**call_kwargs)
        assert result1["cached"] is False, f"First call should not be cached, got: {result1}"

        result2 = client.call(**call_kwargs)
        assert result2["cached"] is True, f"Second call should be cached, got: {result2}"

        api_call_count = mock_openai_cls.return_value.chat.completions.create.call_count
        assert api_call_count == 1, (
            f"API should have been called exactly once, got: {api_call_count}"
        )

        row_count = db_conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
        assert row_count == 1, f"agent_runs should have exactly 1 row, got: {row_count}"

        # T1-02: real cost_usd must be persisted (regression for the old cost_usd=0.0 bug)
        cost_usd = db_conn.execute("SELECT cost_usd FROM agent_runs").fetchone()[0]
        assert cost_usd > 0.0, f"agent_runs.cost_usd should be > 0, got {cost_usd}"


def test_claim_null_chunk_id_sentinel_satisfies_fk(db_conn):
    """claims.chunk_id has an FK to chunks(id). The agent layer uses the string
    "null" as the sentinel for untraceable claims (Phase-2 contract). Storing the
    literal "null" string violates the FK on FK-enforcing DBs (Turso; libsql local
    also enforces FKs by default), crashing batch_ingest — found in 05-03 live
    deploy. insert_claim must normalize the "null" sentinel to SQL NULL so the
    nullable FK is satisfied, while a bogus real chunk_id must still be rejected.
    """
    _insert_source(db_conn, "src_fk_test_01", "hash_fk_test_01", "raw/fk.md")

    # The "null" sentinel must NOT raise — normalized to NULL, FK skipped.
    claim_id = insert_claim(
        db_conn,
        {
            "source_id": "src_fk_test_01",
            "chunk_id": "null",
            "statement": "untraceable claim",
            "created_at": "2026-01-01T00:00:00Z",
        },
        commit=True,
    )

    # Stored value must be SQL NULL, not the string "null".
    stored = db_conn.execute(
        "SELECT chunk_id FROM claims WHERE id = ?", (claim_id,)
    ).fetchone()[0]
    assert stored is None, f"expected NULL chunk_id, got {stored!r}"

    # None must also be accepted directly.
    insert_claim(
        db_conn,
        {
            "source_id": "src_fk_test_01",
            "chunk_id": None,
            "statement": "explicit null",
            "created_at": "2026-01-01T00:00:00Z",
        },
        commit=True,
    )

    # A bogus REAL chunk_id (not the sentinel) must still be rejected by the FK,
    # proving enforcement is intact and only the sentinel is normalized.
    with pytest.raises(Exception, match="FOREIGN KEY"):
        insert_claim(
            db_conn,
            {
                "source_id": "src_fk_test_01",
                "chunk_id": "chk_bogus_nonexistent",
                "statement": "bad ref",
                "created_at": "2026-01-01T00:00:00Z",
            },
            commit=True,
        )
