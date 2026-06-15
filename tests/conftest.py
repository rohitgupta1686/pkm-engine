import os
import pathlib
import tempfile

import pytest

from pkm.config import Settings
from pkm.store.registry import connect


@pytest.fixture(scope="function")
def db_conn():
    """Create a fresh auto-migrated DB per test function using a temp directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(pathlib.Path(tmp_dir) / "test.db")
        s = Settings(anthropic_api_key="test-key", db_path=db_path)
        conn = connect(s)
        yield conn


@pytest.fixture
def sample_content():
    """Return a dict with canonical sample content fields for idempotency tests."""
    return {
        "content_hash": "abc123deadbeef01",
        "raw_path": "raw/2026/06/test_article.md",
        "source_id": "src_abc123deadbee",
        "type": "Article",
        "date_saved": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
