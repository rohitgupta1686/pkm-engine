"""
Unit tests for pkm/retrieval/embed.py.

All CF API calls are intercepted via unittest.mock.patch on urllib.request.urlopen
so no real Cloudflare account or network is required.

Tests:
  TestEmbedNoop         — no-op when creds are empty or claims list is empty
  TestEmbedHappyPath    — embeds claims, upserts to Vectorize, writes embeddings_meta
  TestEmbedIdempotency  — claims with existing embeddings_meta rows are skipped
  TestEmbedPerClaimFailure — a single embed failure is counted but does not abort
  TestVectorizeUpsertFailure — Vectorize upsert failure marks all as failed (no metadata written)
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from io import BytesIO
from unittest.mock import MagicMock, patch, call

import pytest

from pkm.config import Settings
from pkm.retrieval.embed import embed_claims, _EMBED_MODEL, _EMBED_DIM
from pkm.store.registry import connect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_VEC = [0.1] * _EMBED_DIM  # mock 768-dim embedding


def _make_claims(n: int = 2) -> list[dict]:
    return [
        {"id": f"clm_{i:04d}", "statement": f"Test claim statement number {i}."}
        for i in range(n)
    ]


def _ai_response(vec: list[float]) -> bytes:
    """Encode a Workers AI /run response body."""
    return json.dumps({
        "result": {"data": [vec], "shape": [1, _EMBED_DIM]},
        "success": True,
        "errors": [],
        "messages": [],
    }).encode()


def _vectorize_response(count: int) -> bytes:
    """Encode a Vectorize /upsert response body."""
    return json.dumps({
        "result": {"count": count},
        "success": True,
        "errors": [],
        "messages": [],
    }).encode()


class _FakeHTTPResponse:
    """Minimal urllib HTTP response stand-in."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _build_urlopen_mock(ai_vec: list[float] = None, vectorize_count: int = None):
    """Build a side_effect for urllib.request.urlopen.

    Dispatches on URL: Workers AI calls get the ai_vec response; Vectorize calls
    get the vectorize_count response. Raises ValueError for unknown URLs so tests
    catch unexpected calls quickly.
    """
    if ai_vec is None:
        ai_vec = _SAMPLE_VEC
    if vectorize_count is None:
        vectorize_count = 1

    def side_effect(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/ai/run/" in url:
            return _FakeHTTPResponse(_ai_response(ai_vec))
        if "/vectorize/v2/" in url:
            return _FakeHTTPResponse(_vectorize_response(vectorize_count))
        raise ValueError(f"Unexpected URL in test: {url}")

    return MagicMock(side_effect=side_effect)


@pytest.fixture
def db_conn():
    """Fresh in-memory-style DB per test (file in a tempdir so libsql accepts it)."""
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(openai_api_key="test", db_path=str(pathlib.Path(tmp) / "test.db"))
        conn = connect(s)
        yield conn


# ---------------------------------------------------------------------------
# Tests: no-op guard
# ---------------------------------------------------------------------------


class TestEmbedNoop:
    def test_no_op_when_account_id_empty(self, db_conn):
        result = embed_claims(
            conn=db_conn,
            claims=_make_claims(2),
            source_id="src_abc",
            raw_path="raw/test.md",
            cf_account_id="",
            cf_api_token="tok",
        )
        assert result == {"embedded": 0, "skipped": 0, "failed": 0}

    def test_no_op_when_api_token_empty(self, db_conn):
        result = embed_claims(
            conn=db_conn,
            claims=_make_claims(2),
            source_id="src_abc",
            raw_path="raw/test.md",
            cf_account_id="acct",
            cf_api_token="",
        )
        assert result == {"embedded": 0, "skipped": 0, "failed": 0}

    def test_no_op_when_claims_empty(self, db_conn):
        with patch("urllib.request.urlopen") as mock_open:
            result = embed_claims(
                conn=db_conn,
                claims=[],
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="acct",
                cf_api_token="tok",
            )
        assert result == {"embedded": 0, "skipped": 0, "failed": 0}
        mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestEmbedHappyPath:
    def test_embeds_and_writes_metadata(self, db_conn):
        claims = _make_claims(2)
        mock_open = _build_urlopen_mock()

        with patch("urllib.request.urlopen", mock_open):
            result = embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="acct123",
                cf_api_token="tok456",
            )

        assert result["embedded"] == 2
        assert result["skipped"] == 0
        assert result["failed"] == 0

        # embeddings_meta rows were written
        rows = db_conn.execute("SELECT object_id, object_kind, collection, model, dim FROM embeddings_meta").fetchall()
        assert len(rows) == 2
        ids = {r[0] for r in rows}
        assert ids == {"clm_0000", "clm_0001"}
        for r in rows:
            assert r[1] == "claim"
            assert r[2] == "pkm-claims"
            assert r[3] == _EMBED_MODEL
            assert r[4] == _EMBED_DIM

    def test_workers_ai_called_with_correct_url_and_body(self, db_conn):
        claims = [{"id": "clm_0000", "statement": "Test statement."}]
        captured_reqs = []

        def side_effect(req, timeout=None):
            captured_reqs.append(req)
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/ai/run/" in url:
                return _FakeHTTPResponse(_ai_response(_SAMPLE_VEC))
            return _FakeHTTPResponse(_vectorize_response(1))

        with patch("urllib.request.urlopen", side_effect=side_effect):
            embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="myacct",
                cf_api_token="mytoken",
            )

        # First request should be the Workers AI embed call
        ai_req = next(r for r in captured_reqs if "/ai/run/" in (r.full_url if hasattr(r, "full_url") else str(r)))
        assert f"/accounts/myacct/ai/run/{_EMBED_MODEL}" in (ai_req.full_url if hasattr(ai_req, "full_url") else str(ai_req))
        assert ai_req.get_header("Authorization") == "Bearer mytoken"
        body = json.loads(ai_req.data)
        assert body["text"] == "Test statement."

    def test_vectorize_upsert_called_with_ndjson(self, db_conn):
        claims = _make_claims(2)
        captured_vec_req = []

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/ai/run/" in url:
                return _FakeHTTPResponse(_ai_response(_SAMPLE_VEC))
            if "/vectorize/v2/" in url:
                captured_vec_req.append(req)
                return _FakeHTTPResponse(_vectorize_response(2))
            raise ValueError(f"unexpected URL: {url}")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_xyz",
                raw_path="raw/article.md",
                cf_account_id="acct",
                cf_api_token="tok",
            )

        assert len(captured_vec_req) == 1
        vec_req = captured_vec_req[0]
        assert "/vectorize/v2/indexes/pkm-claims/upsert" in (vec_req.full_url if hasattr(vec_req, "full_url") else str(vec_req))
        assert vec_req.get_header("Content-type") == "application/x-ndjson"

        # Each line is a valid JSON object with id, values, metadata
        lines = vec_req.data.decode().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "id" in obj
            assert "values" in obj
            assert len(obj["values"]) == _EMBED_DIM
            assert obj["metadata"]["source_id"] == "src_xyz"
            assert obj["metadata"]["raw_path"] == "raw/article.md"


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------


class TestEmbedIdempotency:
    def test_already_embedded_claims_are_skipped(self, db_conn):
        claims = _make_claims(2)

        # Pre-insert embeddings_meta for the first claim
        db_conn.execute(
            "INSERT INTO embeddings_meta (object_id, object_kind, collection, model, dim, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("clm_0000", "claim", "pkm-claims", _EMBED_MODEL, _EMBED_DIM, "2026-01-01T00:00:00Z"),
        )
        db_conn.commit()

        mock_open = _build_urlopen_mock()

        with patch("urllib.request.urlopen", mock_open):
            result = embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="acct",
                cf_api_token="tok",
            )

        assert result["embedded"] == 1  # only clm_0001 was new
        assert result["skipped"] == 1   # clm_0000 was already present
        assert result["failed"] == 0

        # Exactly 2 urlopen calls: 1 Workers AI embed + 1 Vectorize upsert.
        # (clm_0000 was pre-inserted, so no embed call for it.)
        assert mock_open.call_count == 2

    def test_all_already_embedded_returns_all_skipped(self, db_conn):
        claims = _make_claims(2)
        for c in claims:
            db_conn.execute(
                "INSERT INTO embeddings_meta (object_id, object_kind, collection, model, dim, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (c["id"], "claim", "pkm-claims", _EMBED_MODEL, _EMBED_DIM, "2026-01-01T00:00:00Z"),
            )
        db_conn.commit()

        with patch("urllib.request.urlopen") as mock_open:
            result = embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="acct",
                cf_api_token="tok",
            )

        assert result == {"embedded": 0, "skipped": 2, "failed": 0}
        mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: per-claim embed failure
# ---------------------------------------------------------------------------


class TestEmbedPerClaimFailure:
    def test_one_failed_embed_does_not_abort_rest(self, db_conn):
        claims = _make_claims(3)
        call_count = [0]

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/ai/run/" in url:
                call_count[0] += 1
                if call_count[0] == 2:
                    raise urllib_error_factory()
                return _FakeHTTPResponse(_ai_response(_SAMPLE_VEC))
            return _FakeHTTPResponse(_vectorize_response(2))

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="acct",
                cf_api_token="tok",
            )

        assert result["embedded"] == 2
        assert result["failed"] == 1
        assert result["skipped"] == 0
        # Only 2 metadata rows written (the successful ones)
        count = db_conn.execute("SELECT COUNT(*) FROM embeddings_meta").fetchone()[0]
        assert count == 2


def urllib_error_factory():
    """Return a URLError-like exception for per-claim failure tests."""
    import urllib.error
    return urllib.error.URLError("simulated Workers AI timeout")


# ---------------------------------------------------------------------------
# Tests: Vectorize upsert failure
# ---------------------------------------------------------------------------


class TestVectorizeUpsertFailure:
    def test_vectorize_failure_marks_all_as_failed_no_metadata_written(self, db_conn):
        claims = _make_claims(2)

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/ai/run/" in url:
                return _FakeHTTPResponse(_ai_response(_SAMPLE_VEC))
            if "/vectorize/v2/" in url:
                raise RuntimeError("Vectorize unavailable")
            raise ValueError(f"unexpected: {url}")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = embed_claims(
                conn=db_conn,
                claims=claims,
                source_id="src_abc",
                raw_path="raw/test.md",
                cf_account_id="acct",
                cf_api_token="tok",
            )

        assert result["embedded"] == 0
        assert result["failed"] == 2
        assert result["skipped"] == 0
        # No metadata rows must be written when Vectorize fails
        count = db_conn.execute("SELECT COUNT(*) FROM embeddings_meta").fetchone()[0]
        assert count == 0
