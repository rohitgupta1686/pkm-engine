"""
Tests for pkm/lint.py (Phase 7 Plan 01 — GUARD-01).

Covers: broken [[wikilinks]], orphan notes, claims missing chunk_id provenance,
and the log.md clean/failure write contract.
"""
from __future__ import annotations

import pathlib
import tempfile
from datetime import datetime, timezone

import pytest

from pkm.config import Settings
from pkm.lint import lint_vault, LintReport
from pkm.store.registry import connect, insert_claim, insert_chunks, upsert_source


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_conn():
    """Fresh auto-migrated DB per test."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(pathlib.Path(tmp_dir) / "test.db")
        s = Settings(openai_api_key="test-key", db_path=db_path)
        conn = connect(s)
        yield conn


@pytest.fixture()
def vault_root(tmp_path):
    """Minimal vault tree with wiki/sources and wiki/concepts dirs + empty log.md."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    (tmp_path / "log.md").write_text("")
    return tmp_path


def _write_page(vault_root: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    """Write a markdown page at vault_root/<rel> and return its path."""
    p = vault_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _make_source(conn, source_id="src_linttest0001", content_hash="lint" * 4):
    record = {
        "id": source_id,
        "content_hash": content_hash,
        "type": "Article",
        "title": "Lint Test Article",
        "date_saved": "2026-01-01T00:00:00Z",
        "raw_path": "raw/2026/01/lint-test.md",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    upsert_source(conn, record)
    return source_id


# ---------------------------------------------------------------------------
# Broken wikilinks
# ---------------------------------------------------------------------------


class TestBrokenWikilinks:
    def test_broken_wikilink_detected(self, db_conn, vault_root):
        _write_page(
            vault_root,
            "wiki/sources/my-article.md",
            "## Extracted Concepts\n\n[[nonexistent-concept]]\n",
        )
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert len(report.broken_wikilinks) == 1
        entry = report.broken_wikilinks[0]
        assert entry["page"] == "wiki/sources/my-article.md"
        assert entry["link"] == "nonexistent-concept"
        assert not report.is_clean

    def test_broken_wikilink_clean(self, db_conn, vault_root):
        _write_page(vault_root, "wiki/concepts/real-concept.md", "# Real Concept\n")
        _write_page(
            vault_root,
            "wiki/sources/my-article.md",
            "## Extracted Concepts\n\n[[real-concept]]\n",
        )
        # List the source page in index.md so it is not an orphan; the concept
        # page is referenced from the source page. Vault is fully clean.
        (vault_root / "index.md").write_text("- [[my-article]]\n", encoding="utf-8")
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert report.broken_wikilinks == []
        assert report.is_clean

    def test_pipe_alias_target_resolved(self, db_conn, vault_root):
        """[[real-concept|Display]] should resolve to the 'real-concept' page, not be broken."""
        _write_page(vault_root, "wiki/concepts/real-concept.md", "# Real\n")
        _write_page(
            vault_root,
            "wiki/sources/my-article.md",
            "[[real-concept|Operating Leverage]]\n",
        )
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert report.broken_wikilinks == []


# ---------------------------------------------------------------------------
# Orphans
# ---------------------------------------------------------------------------


class TestOrphans:
    def test_orphan_detected(self, db_conn, vault_root):
        # A concept page nobody links to and not in index.md
        _write_page(vault_root, "wiki/concepts/lonely.md", "# Lonely Concept\n")
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert "wiki/concepts/lonely.md" in report.orphans

    def test_orphan_not_flagged_when_linked(self, db_conn, vault_root):
        _write_page(vault_root, "wiki/concepts/linked.md", "# Linked\n")
        _write_page(
            vault_root,
            "wiki/sources/my-article.md",
            "## Extracted Concepts\n\n[[linked]]\n",
        )
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert "wiki/concepts/linked.md" not in report.orphans

    def test_orphan_not_flagged_when_in_index(self, db_conn, vault_root):
        _write_page(vault_root, "wiki/concepts/indexed.md", "# Indexed\n")
        (vault_root / "index.md").write_text("- [[indexed]]\n", encoding="utf-8")
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert "wiki/concepts/indexed.md" not in report.orphans


# ---------------------------------------------------------------------------
# Missing provenance
# ---------------------------------------------------------------------------


class TestMissingProvenance:
    def test_missing_provenance_detected(self, db_conn, vault_root):
        sid = _make_source(db_conn)
        # claim with no chunk_id -> NULL provenance
        insert_claim(
            db_conn,
            {
                "source_id": sid,
                "chunk_id": None,
                "statement": "Untraceable claim with no span.",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert len(report.missing_provenance) == 1
        item = report.missing_provenance[0]
        assert item["statement"] == "Untraceable claim with no span."
        assert item["source_id"] == sid
        assert item["claim_id"].startswith("clm_")

    def test_missing_provenance_clean(self, db_conn, vault_root):
        sid = _make_source(db_conn)
        insert_chunks(
            db_conn,
            sid,
            [
                {
                    "id": "chk_src_linttest_000",
                    "ordinal": 0,
                    "char_start": 0,
                    "char_end": 10,
                    "text": "some text",
                }
            ],
        )
        insert_claim(
            db_conn,
            {
                "source_id": sid,
                "chunk_id": "chk_src_linttest_000",
                "statement": "Traceable claim.",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        report = lint_vault(db_conn, vault_root, write_log=False)
        assert report.missing_provenance == []


# ---------------------------------------------------------------------------
# log.md write contract
# ---------------------------------------------------------------------------


class TestLogWrite:
    def test_log_md_appended_on_failures(self, db_conn, vault_root):
        _write_page(vault_root, "wiki/concepts/lonely.md", "# Lonely\n")
        now = datetime(2026, 6, 21, 3, 0, 0, tzinfo=timezone.utc)
        lint_vault(db_conn, vault_root, write_log=True, now=now)
        log = (vault_root / "log.md").read_text(encoding="utf-8")
        assert "2026-06-21T03:00:00Z lint FAIL" in log
        assert "broken=0" in log
        assert "orphan=1" in log
        assert "missing_provenance=0" in log
        # A detail line for the orphan is present
        assert "- orphan: wiki/concepts/lonely.md" in log

    def test_log_md_clean_path_no_failure_lines(self, db_conn, vault_root):
        # Clean vault: a concept page linked from a source page (so concept is not
        # an orphan), the source page listed in index.md (so it is not an orphan),
        # and no missing-provenance claims.
        _write_page(vault_root, "wiki/concepts/linked.md", "# Linked\n")
        _write_page(vault_root, "wiki/sources/my-article.md", "[[linked]]\n")
        (vault_root / "index.md").write_text("- [[my-article]]\n", encoding="utf-8")
        now = datetime(2026, 6, 21, 3, 0, 0, tzinfo=timezone.utc)
        lint_vault(db_conn, vault_root, write_log=True, now=now)
        log = (vault_root / "log.md").read_text(encoding="utf-8")
        # Exactly one line: the "lint ok" confirmation.
        lines = [ln for ln in log.splitlines() if ln.strip()]
        assert lines == ["2026-06-21T03:00:00Z lint ok"]
        assert "FAIL" not in log
        assert "broken=" not in log

    def test_write_log_false_does_not_touch_log(self, db_conn, vault_root):
        _write_page(vault_root, "wiki/concepts/lonely.md", "# Lonely\n")
        lint_vault(db_conn, vault_root, write_log=False)
        assert (vault_root / "log.md").read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


class TestReportShape:
    def test_fresh_report_is_clean(self):
        assert LintReport().is_clean is True

    def test_dirty_report_not_clean(self):
        r = LintReport(broken_wikilinks=[{"page": "x", "link": "y"}])
        assert r.is_clean is False