"""
Tests for pkm.batch.batch_ingest — batch processing of raw/*.md files.

TDD RED phase: these tests MUST fail before batch_ingest is implemented.
"""

from __future__ import annotations

import pathlib
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from pkm.config import Settings
from pkm.store.registry import connect


@pytest.fixture
def vault_with_raw_files(tmp_path):
    """Create a minimal vault structure with raw/*.md files."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "article_a.md").write_text(
        textwrap.dedent("""\
            ---
            title: Article A
            ---
            Content of article A.
        """),
        encoding="utf-8",
    )
    (raw_dir / "article_b.md").write_text(
        textwrap.dedent("""\
            ---
            title: Article B
            ---
            Content of article B.
        """),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def vault_with_nested_raw(tmp_path):
    """Create a vault with nested raw/sub/dir/x.md."""
    nested = tmp_path / "raw" / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "x.md").write_text("Nested content.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def vault_with_non_raw_files(tmp_path):
    """Create a vault with files outside raw/ (wiki/, README) — these must NOT be ingested."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "valid.md").write_text("Valid raw content.", encoding="utf-8")
    # wiki file — should be ignored
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "concepts.md").write_text("Wiki content.", encoding="utf-8")
    # root README — should be ignored
    (tmp_path / "README.md").write_text("Root readme.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def empty_vault(tmp_path):
    """Vault with no raw/ directory at all."""
    return tmp_path


@pytest.fixture
def db_conn():
    """Auto-migrated in-memory DB for testing."""
    s = Settings(anthropic_api_key="test-key", db_path=":memory:")
    conn = connect(s)
    yield conn


def _mock_run_ingest(return_values):
    """Build a mock run_ingest that returns values in order, one per call.

    return_values: list of dicts or Exceptions.
      - dict -> successful run_ingest return
      - Exception -> will be raised
    """
    side_effects = list(return_values)
    mock_fn = MagicMock(side_effect=side_effects)
    return mock_fn


# ---------- Test: batch_ingest processes multiple files ----------

def test_batch_ingest_processes_multiple_files(vault_with_raw_files, db_conn):
    """Given a vault with 2 raw/*.md files, batch_ingest calls run_ingest exactly twice
    and returns processed=2, deduped=0."""
    from pkm.batch import batch_ingest

    mock_ingest = _mock_run_ingest([
        {"deduped": False, "source_id": "src_a", "wiki_path": "wiki/a.md", "n_claims": 1, "n_concepts": 0},
        {"deduped": False, "source_id": "src_b", "wiki_path": "wiki/b.md", "n_claims": 1, "n_concepts": 0},
    ])

    with patch("pkm.batch.run_ingest", mock_ingest):
        result = batch_ingest(
            conn=db_conn,
            llm_client=MagicMock(),
            vault_root=vault_with_raw_files,
            new_only=True,
        )

    assert result["processed"] == 2
    assert result["deduped"] == 0
    assert result["wrote"] == 2
    assert result["failed"] == 0
    assert result["failures"] == []
    assert mock_ingest.call_count == 2


# ---------- Test: batch_ingest idempotent re-run (all deduped) ----------

def test_batch_ingest_idempotent_rerun(vault_with_raw_files, db_conn):
    """Re-running over an unchanged vault where all files are deduped returns
    processed=2, deduped=2, wrote=0."""
    from pkm.batch import batch_ingest

    mock_ingest = _mock_run_ingest([
        {"deduped": True, "source_id": "src_a", "wiki_path": None, "n_claims": 0, "n_concepts": 0},
        {"deduped": True, "source_id": "src_b", "wiki_path": None, "n_claims": 0, "n_concepts": 0},
    ])

    with patch("pkm.batch.run_ingest", mock_ingest):
        result = batch_ingest(
            conn=db_conn,
            llm_client=MagicMock(),
            vault_root=vault_with_raw_files,
            new_only=True,
        )

    assert result["processed"] == 2
    assert result["deduped"] == 2
    assert result["wrote"] == 0
    assert result["failed"] == 0


# ---------- Test: nested raw files are discovered ----------

def test_batch_ingest_discovers_nested_files(vault_with_nested_raw, db_conn):
    """Nested raw/sub/dir/x.md is discovered via recursive glob."""
    from pkm.batch import batch_ingest

    mock_ingest = _mock_run_ingest([
        {"deduped": False, "source_id": "src_x", "wiki_path": "wiki/x.md", "n_claims": 0, "n_concepts": 0},
    ])

    with patch("pkm.batch.run_ingest", mock_ingest):
        result = batch_ingest(
            conn=db_conn,
            llm_client=MagicMock(),
            vault_root=vault_with_nested_raw,
            new_only=True,
        )

    assert result["processed"] == 1
    # Verify the call was made with vault-relative path
    call_args = mock_ingest.call_args
    assert call_args.kwargs.get("raw_path") == "raw/sub/dir/x.md" or call_args[1].get("raw_path") == "raw/sub/dir/x.md"


# ---------- Test: per-file exception does not abort batch ----------

def test_batch_ingest_continues_on_error(vault_with_raw_files, db_conn):
    """If run_ingest raises for one file, batch_ingest records it under failed
    and continues processing remaining files."""
    from pkm.batch import batch_ingest

    mock_ingest = _mock_run_ingest([
        RuntimeError("LLM timeout for article_a"),
        {"deduped": False, "source_id": "src_b", "wiki_path": "wiki/b.md", "n_claims": 1, "n_concepts": 0},
    ])

    with patch("pkm.batch.run_ingest", mock_ingest):
        result = batch_ingest(
            conn=db_conn,
            llm_client=MagicMock(),
            vault_root=vault_with_raw_files,
            new_only=True,
        )

    assert result["processed"] == 2
    assert result["failed"] == 1
    assert result["wrote"] == 1
    assert len(result["failures"]) == 1
    assert "article_a" in result["failures"][0]["raw_path"]
    assert "LLM timeout" in result["failures"][0]["error"]


# ---------- Test: files outside raw/ are never passed to run_ingest ----------

def test_batch_ingest_ignores_non_raw_files(vault_with_non_raw_files, db_conn):
    """Only raw/**/*.md files are processed; wiki/ and root-level files are skipped."""
    from pkm.batch import batch_ingest

    mock_ingest = _mock_run_ingest([
        {"deduped": False, "source_id": "src_valid", "wiki_path": "wiki/valid.md", "n_claims": 0, "n_concepts": 0},
    ])

    with patch("pkm.batch.run_ingest", mock_ingest):
        result = batch_ingest(
            conn=db_conn,
            llm_client=MagicMock(),
            vault_root=vault_with_non_raw_files,
            new_only=True,
        )

    # Only the one file in raw/ should be processed
    assert mock_ingest.call_count == 1
    assert result["processed"] == 1


# ---------- Test: empty vault (no raw/ dir) returns zero summary ----------

def test_batch_ingest_empty_vault(empty_vault, db_conn):
    """If vault_root has no raw/ directory, batch_ingest returns a zero summary
    without raising."""
    from pkm.batch import batch_ingest

    with patch("pkm.batch.run_ingest") as mock_ingest:
        result = batch_ingest(
            conn=db_conn,
            llm_client=MagicMock(),
            vault_root=empty_vault,
            new_only=True,
        )

    assert result["processed"] == 0
    assert result["wrote"] == 0
    assert result["deduped"] == 0
    assert result["failed"] == 0
    assert result["failures"] == []
    mock_ingest.assert_not_called()