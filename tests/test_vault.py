"""
Vault writer + ingest helper test suite — Phase 3 Plan 02.

Covers:
  Task 1: hashing, chunker, registry CRUD helpers
  Task 2: vault.py — idempotent source/concept pages, ^cite anchors, wikilinks, log.md
"""
import pathlib
import re
import tempfile
from datetime import datetime

import pytest

from pkm.store.registry import connect
from pkm.config import Settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_conn():
    """Fresh auto-migrated DB per test."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(pathlib.Path(tmp_dir) / "test.db")
        s = Settings(anthropic_api_key="test-key", db_path=db_path)
        conn = connect(s)
        yield conn


@pytest.fixture()
def vault_root(tmp_path):
    """Create a minimal vault directory tree in tmp_path."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    log = tmp_path / "log.md"
    log.write_text("")
    return tmp_path


# ---------------------------------------------------------------------------
# Task 1: hashing
# ---------------------------------------------------------------------------

class TestHashing:
    def test_sha256_content_deterministic(self):
        from pkm.ingest.hashing import sha256_content
        h1 = sha256_content("hello world")
        h2 = sha256_content("hello world")
        assert h1 == h2
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_sha256_content_different(self):
        from pkm.ingest.hashing import sha256_content
        assert sha256_content("foo") != sha256_content("bar")

    def test_source_id_from_hash(self):
        from pkm.ingest.hashing import sha256_content, source_id_from_hash
        h = sha256_content("test text")
        sid = source_id_from_hash(h)
        assert sid.startswith("src_")
        assert len(sid) == 4 + 12  # "src_" + 12 hex chars

    def test_slugify_basic(self):
        from pkm.ingest.hashing import slugify
        assert slugify("Operating Leverage") == "operating-leverage"

    def test_slugify_special_chars(self):
        from pkm.ingest.hashing import slugify
        assert slugify("Hello, World! (2024)") == "hello-world-2024"

    def test_slugify_multiple_spaces(self):
        from pkm.ingest.hashing import slugify
        assert slugify("  foo   bar  ") == "foo-bar"

    def test_concept_id(self):
        from pkm.ingest.hashing import concept_id
        assert concept_id("Operating Leverage") == "cpt_operating-leverage"

    def test_chunk_id_format(self):
        from pkm.ingest.hashing import chunk_id
        cid = chunk_id("a1b2c3d4e5f6", 7)
        assert cid == "chk_a1b2c3d4e5f6_007"

    def test_chunk_id_zero_padded(self):
        from pkm.ingest.hashing import chunk_id
        assert chunk_id("abc123", 0) == "chk_abc123_000"
        assert chunk_id("abc123", 999) == "chk_abc123_999"


# ---------------------------------------------------------------------------
# Task 1: chunker
# ---------------------------------------------------------------------------

class TestChunker:
    def test_single_chunk_short_text(self):
        from pkm.ingest.chunker import chunk_text
        chunks = chunk_text("hello world", target_tokens=1200)
        assert len(chunks) >= 1
        assert chunks[0]["char_start"] == 0
        assert chunks[-1]["char_end"] == len("hello world")

    def test_contiguous_ranges(self):
        from pkm.ingest.chunker import chunk_text
        text = "a" * 10000
        chunks = chunk_text(text)
        assert chunks[0]["char_start"] == 0
        assert chunks[-1]["char_end"] == 10000
        for i in range(len(chunks) - 1):
            assert chunks[i]["char_end"] == chunks[i + 1]["char_start"], (
                f"Gap between chunk {i} and {i+1}: "
                f"{chunks[i]['char_end']} != {chunks[i+1]['char_start']}"
            )

    def test_deterministic(self):
        from pkm.ingest.chunker import chunk_text
        text = "word " * 3000
        c1 = chunk_text(text)
        c2 = chunk_text(text)
        assert c1 == c2

    def test_ordinal_sequential(self):
        from pkm.ingest.chunker import chunk_text
        text = "paragraph\n\n" * 500
        chunks = chunk_text(text)
        ordinals = [c["ordinal"] for c in chunks]
        assert ordinals == list(range(len(chunks)))

    def test_text_slice_correct(self):
        from pkm.ingest.chunker import chunk_text
        text = "hello world foo bar baz " * 200
        chunks = chunk_text(text)
        for c in chunks:
            assert text[c["char_start"]:c["char_end"]] == c["text"]

    def test_token_count_approx(self):
        from pkm.ingest.chunker import chunk_text
        text = "word " * 100
        chunks = chunk_text(text)
        for c in chunks:
            assert "token_count" in c
            assert c["token_count"] >= 0


# ---------------------------------------------------------------------------
# Task 1: registry CRUD helpers
# ---------------------------------------------------------------------------

class TestRegistryCRUD:
    def _make_source_record(self, content_hash="deadbeef112233", title="Test Article"):
        from pkm.ingest.hashing import source_id_from_hash
        return {
            "id": source_id_from_hash(content_hash),
            "content_hash": content_hash,
            "type": "Article",
            "title": title,
            "author": "Test Author",
            "url": "https://example.com",
            "date_saved": "2026-01-01T00:00:00Z",
            "raw_path": "raw/2026/01/test-article.md",
            "status": "captured",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

    def test_upsert_source_creates(self, db_conn):
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        source_id, created = upsert_source(db_conn, record)
        assert created is True
        assert source_id == record["id"]

    def test_upsert_source_idempotent(self, db_conn):
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        _, created1 = upsert_source(db_conn, record)
        _, created2 = upsert_source(db_conn, record)
        assert created1 is True
        assert created2 is False
        count = db_conn.execute(
            "SELECT COUNT(*) FROM sources WHERE content_hash=?",
            (record["content_hash"],)
        ).fetchone()[0]
        assert count == 1

    def test_upsert_source_no_raw_path_update(self, db_conn):
        """Calling upsert_source must never update raw_path (immutability contract)."""
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        upsert_source(db_conn, record)
        # Verify raw_path in DB is unchanged
        row = db_conn.execute(
            "SELECT raw_path FROM sources WHERE id=?",
            (record["id"],)
        ).fetchone()
        assert row[0] == record["raw_path"]

    def test_insert_chunks_basic(self, db_conn):
        from pkm.store.registry import upsert_source, insert_chunks
        from pkm.ingest.hashing import chunk_id
        record = self._make_source_record()
        source_id, _ = upsert_source(db_conn, record)
        hash12 = record["content_hash"][:12]
        chunks = [
            {"id": chunk_id(hash12, 0), "ordinal": 0, "char_start": 0, "char_end": 100, "text": "a" * 100, "token_count": 25},
            {"id": chunk_id(hash12, 1), "ordinal": 1, "char_start": 100, "char_end": 200, "text": "b" * 100, "token_count": 25},
        ]
        inserted = insert_chunks(db_conn, source_id, chunks)
        assert inserted == 2

    def test_insert_chunks_idempotent(self, db_conn):
        from pkm.store.registry import upsert_source, insert_chunks
        from pkm.ingest.hashing import chunk_id
        record = self._make_source_record()
        source_id, _ = upsert_source(db_conn, record)
        hash12 = record["content_hash"][:12]
        chunks = [
            {"id": chunk_id(hash12, 0), "ordinal": 0, "char_start": 0, "char_end": 50, "text": "x" * 50, "token_count": 12},
        ]
        insert_chunks(db_conn, source_id, chunks)
        second_run = insert_chunks(db_conn, source_id, chunks)
        assert second_run == 0

    def test_insert_claim_status_candidate(self, db_conn):
        from pkm.store.registry import upsert_source, insert_claim
        record = self._make_source_record()
        source_id, _ = upsert_source(db_conn, record)
        claim = {
            "source_id": source_id,
            "chunk_id": None,
            "statement": "Test claim statement.",
            "subject": "Test",
            "predicate": "is",
            "object": "claim",
            "claim_type": "fact",
            "confidence": 0.8,
            "created_at": "2026-01-01T00:00:00Z",
        }
        claim_id = insert_claim(db_conn, claim)
        assert claim_id.startswith("clm_")
        row = db_conn.execute(
            "SELECT status FROM claims WHERE id=?", (claim_id,)
        ).fetchone()
        assert row[0] == "candidate"

    def test_upsert_concept(self, db_conn):
        from pkm.store.registry import upsert_concept
        from pkm.ingest.hashing import concept_id
        cid = concept_id("Operating Leverage")
        concept = {
            "id": cid,
            "name": "Operating Leverage",
            "definition": "The ratio of fixed costs to variable costs.",
            "domain": "finance",
            "wiki_path": "wiki/concepts/operating-leverage.md",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        returned_id, created = upsert_concept(db_conn, concept)
        assert created is True
        assert returned_id == cid
        # second call
        _, created2 = upsert_concept(db_conn, concept)
        assert created2 is False

    def test_link_claim_concept(self, db_conn):
        from pkm.store.registry import upsert_source, insert_claim, upsert_concept, link_claim_concept
        from pkm.ingest.hashing import concept_id
        record = self._make_source_record()
        source_id, _ = upsert_source(db_conn, record)
        claim_id = insert_claim(db_conn, {
            "source_id": source_id, "chunk_id": None, "statement": "X",
            "subject": None, "predicate": None, "object": None,
            "claim_type": "fact", "confidence": 0.5, "created_at": "2026-01-01T00:00:00Z",
        })
        cid = concept_id("Test Concept")
        upsert_concept(db_conn, {
            "id": cid, "name": "Test Concept", "definition": "",
            "domain": "", "wiki_path": "wiki/concepts/test-concept.md",
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        })
        link_claim_concept(db_conn, claim_id, cid)
        # idempotent
        link_claim_concept(db_conn, claim_id, cid)
        count = db_conn.execute(
            "SELECT COUNT(*) FROM claim_concepts WHERE claim_id=? AND concept_id=?",
            (claim_id, cid)
        ).fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# Task 2: vault.py
# ---------------------------------------------------------------------------

class TestVaultWriter:
    def _make_source_record(self, content_hash="aabbccdd112233"):
        from pkm.ingest.hashing import source_id_from_hash
        return {
            "id": source_id_from_hash(content_hash),
            "content_hash": content_hash,
            "type": "Article",
            "title": "Test Article on Operating Leverage",
            "author": "Jane Smith",
            "url": "https://example.com/article",
            "publisher": "Test Publisher",
            "date_published": "2026-01-01",
            "date_saved": "2026-01-01T00:00:00Z",
            "raw_path": "raw/2026/01/test-article.md",
            "status": "summarized",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

    def _make_summary(self):
        from pkm.schemas.agent_io import SummarizerOutput, KeyClaim
        return SummarizerOutput(
            thesis="Operating leverage amplifies margin expansion at scale.",
            key_claims=[
                KeyClaim(
                    statement="High fixed costs create operating leverage.",
                    subject="fixed costs",
                    predicate="create",
                    object="operating leverage",
                    claim_type="fact",
                    chunk_id="chk_aabbccdd1122_000",
                    confidence=0.9,
                ),
                KeyClaim(
                    statement="Scale benefits compound over time.",
                    subject="scale",
                    predicate="compounds",
                    object="benefits",
                    claim_type="causal",
                    chunk_id="null",  # sentinel
                    confidence=0.4,
                ),
            ],
            caveats=["Assumes stable revenue mix."],
            summary_confidence=0.85,
        )

    def test_write_source_page_creates_file(self, db_conn, vault_root):
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        upsert_source(db_conn, record)
        summary = self._make_summary()
        claims = [
            {"statement": c.statement, "chunk_id": c.chunk_id}
            for c in summary.key_claims
        ]
        wiki_path = write_source_page(
            db_conn, vault_root, record, summary, claims, ["Operating Leverage"]
        )
        page = vault_root / wiki_path
        assert page.exists(), f"Source page not created at {page}"
        content = page.read_text()
        assert "## Key Claims" in content

    def test_write_source_page_cite_anchors(self, db_conn, vault_root):
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        upsert_source(db_conn, record)
        summary = self._make_summary()
        claims = [
            {"statement": c.statement, "chunk_id": c.chunk_id}
            for c in summary.key_claims
        ]
        wiki_path = write_source_page(
            db_conn, vault_root, record, summary, claims, ["Operating Leverage"]
        )
        content = (vault_root / wiki_path).read_text()
        # All claim lines must have ^cite: anchors
        anchor_pattern = re.compile(r"\^cite:src_[a-f0-9]+#")
        claims_section = content.split("## Key Claims")[1].split("##")[0]
        bullet_lines = [
            line.strip() for line in claims_section.splitlines()
            if line.strip().startswith("-")
        ]
        assert len(bullet_lines) >= 1
        for line in bullet_lines:
            assert anchor_pattern.search(line), f"No ^cite anchor in: {line!r}"

    def test_write_source_page_wikilinks(self, db_conn, vault_root):
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        upsert_source(db_conn, record)
        summary = self._make_summary()
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wiki_path = write_source_page(
            db_conn, vault_root, record, summary, claims, ["Operating Leverage", "Scale Effects"]
        )
        content = (vault_root / wiki_path).read_text()
        assert "[[" in content, "Expected [[wikilinks]] in source page"

    def test_write_source_page_idempotent(self, db_conn, vault_root):
        from pkm.store.vault import write_source_page
        from pkm.store.registry import upsert_source
        record = self._make_source_record()
        upsert_source(db_conn, record)
        summary = self._make_summary()
        claims = [{"statement": c.statement, "chunk_id": c.chunk_id} for c in summary.key_claims]
        wp1 = write_source_page(db_conn, vault_root, record, summary, claims, ["Operating Leverage"])
        bytes1 = (vault_root / wp1).read_bytes()
        wp2 = write_source_page(db_conn, vault_root, record, summary, claims, ["Operating Leverage"])
        bytes2 = (vault_root / wp2).read_bytes()
        assert bytes1 == bytes2, "write_source_page produced different bytes on second call"

    def test_resolve_concept_exact_match(self, db_conn):
        from pkm.store.vault import resolve_concept
        from pkm.store.registry import upsert_concept
        from pkm.ingest.hashing import concept_id
        cid = concept_id("Operating Leverage")
        upsert_concept(db_conn, {
            "id": cid,
            "name": "Operating Leverage",
            "definition": "test",
            "domain": "finance",
            "wiki_path": "wiki/concepts/operating-leverage.md",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        result = resolve_concept(db_conn, "Operating Leverage")
        assert result == cid

    def test_resolve_concept_alias_match(self, db_conn):
        from pkm.store.vault import resolve_concept
        from pkm.store.registry import upsert_concept
        from pkm.ingest.hashing import concept_id
        cid = concept_id("Operating Leverage")
        upsert_concept(db_conn, {
            "id": cid,
            "name": "Operating Leverage",
            "definition": "test",
            "domain": "finance",
            "wiki_path": "wiki/concepts/operating-leverage.md",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        # Insert alias
        db_conn.execute(
            "INSERT INTO concept_aliases (alias, concept_id) VALUES (?, ?)",
            ("op leverage", cid)
        )
        db_conn.commit()
        result = resolve_concept(db_conn, "op leverage")
        assert result == cid

    def test_resolve_concept_miss(self, db_conn):
        from pkm.store.vault import resolve_concept
        result = resolve_concept(db_conn, "Nonexistent Concept")
        assert result is None

    def test_write_concept_page_creates(self, db_conn, vault_root):
        from pkm.store.vault import write_concept_page
        from pkm.store.registry import upsert_concept
        from pkm.ingest.hashing import concept_id, slugify
        cid = concept_id("Operating Leverage")
        upsert_concept(db_conn, {
            "id": cid,
            "name": "Operating Leverage",
            "definition": "Ratio of fixed to variable costs.",
            "domain": "finance",
            "wiki_path": "wiki/concepts/operating-leverage.md",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        wiki_path = write_concept_page(
            db_conn, vault_root, cid, "Operating Leverage", "test-article"
        )
        page = vault_root / wiki_path
        assert page.exists(), f"Concept page not created at {page}"
        content = page.read_text()
        assert "[[test-article]]" in content

    def test_write_concept_page_idempotent(self, db_conn, vault_root):
        from pkm.store.vault import write_concept_page
        from pkm.store.registry import upsert_concept
        from pkm.ingest.hashing import concept_id
        cid = concept_id("Operating Leverage")
        upsert_concept(db_conn, {
            "id": cid,
            "name": "Operating Leverage",
            "definition": "Ratio of fixed to variable costs.",
            "domain": "finance",
            "wiki_path": "wiki/concepts/operating-leverage.md",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        write_concept_page(db_conn, vault_root, cid, "Operating Leverage", "test-article")
        write_concept_page(db_conn, vault_root, cid, "Operating Leverage", "test-article")
        content = (vault_root / "wiki/concepts/operating-leverage.md").read_text()
        # [[test-article]] must appear exactly once
        assert content.count("[[test-article]]") == 1, (
            f"Expected exactly 1 [[test-article]], found {content.count('[[test-article]]')}"
        )

    def test_append_log_increments(self, vault_root):
        from pkm.store.vault import append_log
        log_path = vault_root / "log.md"
        initial_lines = log_path.read_text().splitlines()
        append_log(vault_root, "2026-01-01T00:00:00Z ingest src_abc -> wiki/sources/test.md (2 claims, 1 concepts)\n")
        lines_after = log_path.read_text().splitlines()
        assert len(lines_after) == len(initial_lines) + 1

    def test_append_log_multiple_calls(self, vault_root):
        from pkm.store.vault import append_log
        log_path = vault_root / "log.md"
        for i in range(3):
            append_log(vault_root, f"line {i}\n")
        lines = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
