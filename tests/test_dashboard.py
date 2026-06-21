"""
Tests for Phase 7 Plan 07-02 — dashboard counters (GUARD-03) + dashboard
regenerator (GUARD-02).

Task 1: migration 003 + counter helpers + bumps wired into insert paths
        (idempotent re-ingest must not bump counters).
Task 2: pkm/dashboard.py renders all six required sections from counter rows
        + lint counts, with no full-table COUNT(*) scans.
"""
from __future__ import annotations

import pathlib
import re
import tempfile
from datetime import datetime, timezone

import pytest

from pkm.config import Settings
from pkm.dashboard import generate_dashboard, write_dashboard
from pkm.store.registry import (
    bump_counter,
    connect,
    insert_claim,
    insert_chunks,
    read_all_counters,
    read_counter,
    upsert_concept,
    upsert_source,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_conn():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(pathlib.Path(tmp_dir) / "test.db")
        s = Settings(openai_api_key="test-key", db_path=db_path)
        conn = connect(s)
        yield conn


@pytest.fixture()
def vault_root(tmp_path):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    return tmp_path


def _source_record(content_hash="dash" * 4, source_id="src_dash0000001"):
    return {
        "id": source_id,
        "content_hash": content_hash,
        "type": "Article",
        "title": "Dashboard Test Article",
        "date_saved": "2026-01-01T00:00:00Z",
        "raw_path": "raw/2026/01/dash.md",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Task 1: counters table + helpers + bumps
# ---------------------------------------------------------------------------


class TestCountersTable:
    def test_counters_table_created(self, db_conn):
        cols = db_conn.execute("PRAGMA table_info(dashboard_counters)").fetchall()
        names = {r[1] for r in cols}
        assert {"key", "value", "updated_at"} <= names


class TestCounterHelpers:
    def test_bump_counter_increments(self, db_conn):
        assert bump_counter(db_conn, "sources_total", 1) == 1
        assert read_counter(db_conn, "sources_total") == 1
        assert bump_counter(db_conn, "sources_total", 1) == 2

    def test_bump_counter_creates_row(self, db_conn):
        # Fresh key lazy-creates a row whose value equals the delta.
        assert bump_counter(db_conn, "claims_total", 5) == 5
        assert read_counter(db_conn, "claims_total") == 5

    def test_read_counter_missing_is_zero(self, db_conn):
        assert read_counter(db_conn, "does_not_exist") == 0

    def test_read_all_counters(self, db_conn):
        bump_counter(db_conn, "a", 1)
        bump_counter(db_conn, "b", 2)
        assert read_all_counters(db_conn) == {"a": 1, "b": 2}


class TestCounterBumpsWired:
    def test_upsert_source_bumps_on_new(self, db_conn):
        upsert_source(db_conn, _source_record())
        assert read_counter(db_conn, "sources_total") == 1

    def test_upsert_source_no_bump_on_existing(self, db_conn):
        upsert_source(db_conn, _source_record())
        # Same content_hash -> created=False, no bump.
        upsert_source(db_conn, _source_record(content_hash="dash" * 4, source_id="src_other9999999"))
        assert read_counter(db_conn, "sources_total") == 1

    def test_insert_claim_bumps(self, db_conn):
        sid = upsert_source(db_conn, _source_record())[0]
        insert_claim(
            db_conn,
            {"source_id": sid, "chunk_id": None, "statement": "x", "created_at": "2026-01-01T00:00:00Z"},
        )
        assert read_counter(db_conn, "claims_total") == 1
        insert_claim(
            db_conn,
            {"source_id": sid, "chunk_id": None, "statement": "y", "created_at": "2026-01-01T00:00:00Z"},
        )
        assert read_counter(db_conn, "claims_total") == 2

    def test_upsert_concept_bumps_only_on_new(self, db_conn):
        concept = {
            "id": "cpt_operating-leverage",
            "name": "Operating Leverage",
            "definition": "d",
            "domain": "",
            "wiki_path": "",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        upsert_concept(db_conn, concept)
        assert read_counter(db_conn, "concepts_total") == 1
        # Same id -> created=False, no bump.
        upsert_concept(db_conn, concept)
        assert read_counter(db_conn, "concepts_total") == 1


class TestIdempotentReingestCountersStable:
    def test_reingest_leaves_counters_stable(self, db_conn):
        # First ingest: 1 source, 1 concept, 1 claim.
        sid = upsert_source(db_conn, _source_record())[0]
        concept = {
            "id": "cpt_operating-leverage",
            "name": "Operating Leverage",
            "definition": "d",
            "domain": "",
            "wiki_path": "",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        upsert_concept(db_conn, concept)
        insert_claim(
            db_conn,
            {"source_id": sid, "chunk_id": None, "statement": "x", "created_at": "2026-01-01T00:00:00Z"},
        )
        before = read_all_counters(db_conn)
        # Re-ingest: same content_hash source (created=False), same concept id (created=False).
        # (Claims are not re-inserted by a deduped re-ingest — the pipeline's new_only
        # path skips already-processed sources entirely.)
        upsert_source(db_conn, _source_record(content_hash="dash" * 4, source_id="src_other9999999"))
        upsert_concept(db_conn, concept)
        after = read_all_counters(db_conn)
        assert before == after
        assert before["sources_total"] == 1
        assert before["concepts_total"] == 1
        assert before["claims_total"] == 1


# ---------------------------------------------------------------------------
# Task 2: dashboard rendering
# ---------------------------------------------------------------------------


class _ExecuteSpy:
    """Wrap a connection, recording every execute() SQL string, delegating to the real conn."""

    def __init__(self, conn):
        self._conn = conn
        self.sqls: list[str] = []

    def execute(self, sql, *args, **kwargs):
        self.sqls.append(sql)
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestDashboardRender:
    def test_dashboard_renders_all_sections(self, db_conn, vault_root):
        bump_counter(db_conn, "sources_total", 3)
        bump_counter(db_conn, "claims_total", 10)
        bump_counter(db_conn, "concepts_total", 4)
        md = generate_dashboard(db_conn, vault_root, actions_minutes=42, now=datetime(2026, 6, 21, 3, 0, 0, tzinfo=timezone.utc))
        for heading in (
            "## Sources",
            "## Claims",
            "## Concepts",
            "## Insights accepted",
            "## Actions minutes",
            "## Orphans / stale",
        ):
            assert heading in md
        assert "3" in md
        assert "10" in md
        assert "4" in md
        assert "42" in md
        assert "2026-06-21T03:00:00Z" in md

    def test_dashboard_uses_counters_not_scans(self, db_conn, vault_root):
        bump_counter(db_conn, "sources_total", 1)
        spy = _ExecuteSpy(db_conn)
        generate_dashboard(spy, vault_root, actions_minutes=5)
        assert len(spy.sqls) > 0  # actually issued queries (via read_all_counters + lint)
        forbidden = re.compile(r"COUNT\(\*\) FROM (sources|claims|concepts)", re.IGNORECASE)
        offenders = [s for s in spy.sqls if forbidden.search(s)]
        assert offenders == [], f"full-table scan issued: {offenders}"

    def test_dashboard_orphans_from_lint(self, db_conn, vault_root):
        # A concept page nobody links to and not in index.md -> one orphan.
        (vault_root / "wiki" / "concepts" / "lonely.md").write_text("# Lonely\n", encoding="utf-8")
        md = generate_dashboard(db_conn, vault_root, actions_minutes=None)
        assert "orphans: 1" in md

    def test_dashboard_insights_accepted_default_zero(self, db_conn, vault_root):
        md = generate_dashboard(db_conn, vault_root, actions_minutes=None)
        assert "## Insights accepted" in md
        # The section value is 0 (no approval path yet).
        assert re.search(r"## Insights accepted\s*\n+\s*0\s", md)

    def test_dashboard_actions_minutes_optional(self, db_conn, vault_root):
        md = generate_dashboard(db_conn, vault_root, actions_minutes=None)
        assert "## Actions minutes" in md
        assert "N/A" in md

    def test_dashboard_write_to_file(self, db_conn, vault_root):
        path = write_dashboard(db_conn, vault_root, actions_minutes=7, now=datetime(2026, 6, 21, 3, 0, 0, tzinfo=timezone.utc))
        assert path == "dashboard.md"
        written = (vault_root / "dashboard.md").read_text(encoding="utf-8")
        assert "# PKM Dashboard" in written
        assert "7" in written