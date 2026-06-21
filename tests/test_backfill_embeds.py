"""
Tests for pkm/retrieval/embed.py:backfill_embeds (Phase 7 Plan 07-03).

backfill_embeds is the reusable, idempotent replacement for the throwaway Phase-6
Wave 3 backfill script: it embeds every claim lacking an embeddings_meta row.

All CF API calls are intercepted via unittest.mock.patch on urllib.request.urlopen.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from pkm.config import Settings
from pkm.retrieval.embed import backfill_embeds, _EMBED_DIM, _EMBED_MODEL
from pkm.store.registry import connect, insert_claim, upsert_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_VEC = [0.1] * _EMBED_DIM


def _ai_response(vec):
    return json.dumps({"result": {"data": [vec], "shape": [1, _EMBED_DIM]}, "success": True}).encode()


def _vec_response(count):
    return json.dumps({"result": {"count": count}, "success": True}).encode()


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _urlopen_mock(vec=_SAMPLE_VEC, fail_on_embed_call=None):
    """Mock urlopen; optionally raise on the Nth Workers AI call (1-indexed)."""
    state = {"ai_calls": 0}

    def side_effect(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/ai/run/" in url:
            state["ai_calls"] += 1
            if fail_on_embed_call is not None and state["ai_calls"] == fail_on_embed_call:
                import urllib.error
                raise urllib.error.URLError("simulated embed failure")
            return _FakeResp(_ai_response(vec))
        if "/vectorize/v2/" in url:
            return _FakeResp(_vec_response(10))
        raise ValueError(f"unexpected URL: {url}")

    return MagicMock(side_effect=side_effect)


@pytest.fixture(scope="function")
def db_conn():
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(openai_api_key="test", db_path=str(pathlib.Path(tmp) / "test.db"))
        conn = connect(s)
        yield conn


def _make_source(conn, source_id="src_bf00000001", content_hash="bf01" * 4, raw_path="raw/2026/01/source.md"):
    upsert_source(
        conn,
        {
            "id": source_id,
            "content_hash": content_hash,
            "type": "Article",
            "title": "Backfill Source",
            "date_saved": "2026-01-01T00:00:00Z",
            "raw_path": raw_path,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    return source_id


def _insert_claims(conn, source_id, n, prefix="clm_bf"):
    ids = []
    for i in range(n):
        cid = insert_claim(
            conn,
            {
                "source_id": source_id,
                "chunk_id": None,
                "statement": f"Backfill claim {i}.",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        ids.append(cid)
    return ids


def _embed_meta(conn, claim_id):
    conn.execute(
        "INSERT INTO embeddings_meta (object_id, object_kind, collection, model, dim, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (claim_id, "claim", "pkm-claims", _EMBED_MODEL, _EMBED_DIM, "2026-01-01T00:00:00Z"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBackfillNoop:
    def test_noop_no_creds(self, db_conn):
        sid = _make_source(db_conn)
        _insert_claims(db_conn, sid, 2)
        with patch("urllib.request.urlopen") as mock_open:
            result = backfill_embeds(db_conn, cf_account_id="", cf_api_token="")
        assert result == {"embedded": 0, "skipped": 0, "failed": 0}
        mock_open.assert_not_called()

    def test_noop_no_missing(self, db_conn):
        sid = _make_source(db_conn)
        ids = _insert_claims(db_conn, sid, 2)
        for cid in ids:
            _embed_meta(db_conn, cid)
        with patch("urllib.request.urlopen") as mock_open:
            result = backfill_embeds(db_conn, cf_account_id="acct", cf_api_token="tok")
        assert result["embedded"] == 0
        assert result["skipped"] == 2
        assert result["failed"] == 0
        mock_open.assert_not_called()


class TestBackfillEmbeds:
    def test_embeds_missing_claims(self, db_conn):
        sid = _make_source(db_conn)
        ids = _insert_claims(db_conn, sid, 2)
        mock_open = _urlopen_mock()
        with patch("urllib.request.urlopen", mock_open):
            result = backfill_embeds(db_conn, cf_account_id="acct", cf_api_token="tok")
        assert result["embedded"] == 2
        assert result["failed"] == 0
        # 2 embeddings_meta rows written
        n = db_conn.execute("SELECT COUNT(*) FROM embeddings_meta").fetchone()[0]
        assert n == 2
        # Exactly one Vectorize upsert call (both claims share one source).
        vec_calls = sum(
            1 for c in mock_open.call_args_list
            if "/vectorize/v2/" in (c.args[0].full_url if hasattr(c.args[0], "full_url") else str(c.args[0]))
        )
        assert vec_calls == 1

    def test_per_claim_failure(self, db_conn):
        sid = _make_source(db_conn)
        _insert_claims(db_conn, sid, 2)
        # Fail the second Workers AI embed call.
        mock_open = _urlopen_mock(fail_on_embed_call=2)
        with patch("urllib.request.urlopen", mock_open):
            result = backfill_embeds(db_conn, cf_account_id="acct", cf_api_token="tok")
        assert result["embedded"] == 1
        assert result["failed"] == 1
        # embeddings_meta only for the successful claim.
        n = db_conn.execute("SELECT COUNT(*) FROM embeddings_meta").fetchone()[0]
        assert n == 1

    def test_uses_claim_statement_and_raw_path(self, db_conn):
        raw_path = "raw/2026/01/special-article.md"
        sid = _make_source(db_conn, raw_path=raw_path)
        _insert_claims(db_conn, sid, 1)
        captured = []

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/ai/run/" in url:
                return _FakeResp(_ai_response(_SAMPLE_VEC))
            if "/vectorize/v2/" in url:
                captured.append(req)
                return _FakeResp(_vec_response(1))
            raise ValueError(f"unexpected: {url}")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            backfill_embeds(db_conn, cf_account_id="acct", cf_api_token="tok")

        assert len(captured) == 1
        line = captured[0].data.decode().strip().split("\n")[0]
        obj = json.loads(line)
        assert obj["metadata"]["raw_path"] == raw_path
        assert obj["metadata"]["source_id"] == sid