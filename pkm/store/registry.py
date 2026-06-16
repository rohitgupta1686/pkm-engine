import pathlib
import uuid

import libsql_experimental as libsql

from pkm.config import Settings


def get_migrations_dir() -> pathlib.Path:
    """Return the path to the migrations/sqlite directory."""
    return pathlib.Path(__file__).parent.parent.parent / "migrations" / "sqlite"


def _run_migrations(conn) -> None:
    """Execute both migration files in order. IF NOT EXISTS guards make this idempotent."""
    migrations_dir = get_migrations_dir()
    for filename in ("001_init.sql", "002_graph_tables.sql"):
        migration_path = migrations_dir / filename
        sql = migration_path.read_text()
        conn.executescript(sql)


def connect(settings: Settings | None = None):
    """
    Return a libsql connection with auto-migration applied.

    If settings is None, the module-level singleton from pkm.config is used.
    If settings.turso_url is truthy, connects to Turso cloud with auth_token.
    Otherwise opens a local SQLite file at settings.db_path.
    """
    if settings is None:
        from pkm.config import settings as _settings
        settings = _settings

    if settings.turso_url:
        conn = libsql.connect(database=settings.turso_url, auth_token=settings.turso_token)
    else:
        conn = libsql.connect(settings.db_path)

    _run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def upsert_source(conn, record: dict) -> tuple[str, bool]:
    """INSERT OR IGNORE a sources row, return (source_id, created: bool).

    Security (T-03-03): All SQL uses parameterized ? placeholders — no
    f-string value interpolation.
    Immutability (T-03-05): Never updates raw_path.

    Args:
        conn:   libsql connection.
        record: Dict with keys: id, content_hash, type, title, author, url,
                date_saved, raw_path, status, created_at, updated_at.
                Optional: publisher, date_published, wiki_path, credibility, tags.

    Returns:
        (source_id, True) if a new row was inserted, (source_id, False) if already existed.
    """
    source_id = record["id"]

    # Pre-check to detect existing row (INSERT OR IGNORE makes rowcount unreliable
    # across libsql versions for detecting new vs. existing)
    existing = conn.execute(
        "SELECT id FROM sources WHERE content_hash = ?",
        (record["content_hash"],),
    ).fetchone()
    if existing is not None:
        return source_id, False

    conn.execute(
        """
        INSERT OR IGNORE INTO sources
            (id, content_hash, type, title, author, url, publisher,
             date_published, date_saved, raw_path, wiki_path, credibility,
             tags, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            record["content_hash"],
            record.get("type", "Article"),
            record.get("title"),
            record.get("author"),
            record.get("url"),
            record.get("publisher"),
            record.get("date_published"),
            record["date_saved"],
            record["raw_path"],
            record.get("wiki_path"),
            record.get("credibility", 0.5),
            record.get("tags"),
            record.get("status", "captured"),
            record["created_at"],
            record["updated_at"],
        ),
    )
    conn.commit()
    return source_id, True


def insert_chunks(conn, source_id: str, chunks: list[dict]) -> int:
    """INSERT OR IGNORE chunk rows, return count of rows actually inserted.

    Security (T-03-03): parameterized ? placeholders throughout.

    Args:
        conn:      libsql connection.
        source_id: Parent source id.
        chunks:    List of dicts with keys: id, ordinal, char_start, char_end,
                   text, token_count.

    Returns:
        Count of new rows inserted (0 on re-run with identical chunks).
    """
    inserted = 0
    for chunk in chunks:
        # Pre-check for idempotency (INSERT OR IGNORE rowcount unreliable)
        existing = conn.execute(
            "SELECT id FROM chunks WHERE source_id = ? AND ordinal = ?",
            (source_id, chunk["ordinal"]),
        ).fetchone()
        if existing is not None:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO chunks
                (id, source_id, ordinal, char_start, char_end, token_count, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk["id"],
                source_id,
                chunk["ordinal"],
                chunk["char_start"],
                chunk["char_end"],
                chunk.get("token_count", 0),
                chunk["text"],
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def insert_claim(conn, claim: dict) -> str:
    """INSERT a claims row with status='candidate', return the new claim id.

    ID format: "clm_" + uuid4().hex (uuid7 library not a dep; uuid4 documented
    in DECISIONS.md as the Phase 3 choice — sufficient for uniqueness at MVP scale).

    Security (T-03-03): parameterized ? placeholders throughout.

    Args:
        conn:  libsql connection.
        claim: Dict with keys: source_id, chunk_id, statement, subject, predicate,
               object, claim_type, confidence, created_at.

    Returns:
        The new claim id string.
    """
    claim_id = "clm_" + uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO claims
            (id, source_id, chunk_id, statement, subject, predicate, object,
             claim_type, confidence, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
        """,
        (
            claim_id,
            claim["source_id"],
            claim.get("chunk_id"),
            claim["statement"],
            claim.get("subject"),
            claim.get("predicate"),
            claim.get("object"),
            claim.get("claim_type"),
            claim.get("confidence", 0.5),
            claim["created_at"],
        ),
    )
    conn.commit()
    return claim_id


def upsert_concept(conn, concept: dict) -> tuple[str, bool]:
    """INSERT OR IGNORE a concepts row, return (concept_id, created: bool).

    Security (T-03-03): parameterized ? placeholders throughout.

    Args:
        conn:    libsql connection.
        concept: Dict with keys: id, name, definition, domain, wiki_path,
                 created_at, updated_at.

    Returns:
        (concept_id, True) if new, (concept_id, False) if already existed.
    """
    concept_id = concept["id"]
    existing = conn.execute(
        "SELECT id FROM concepts WHERE id = ?",
        (concept_id,),
    ).fetchone()
    if existing is not None:
        return concept_id, False

    conn.execute(
        """
        INSERT OR IGNORE INTO concepts
            (id, name, definition, domain, wiki_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            concept_id,
            concept["name"],
            concept.get("definition"),
            concept.get("domain"),
            concept.get("wiki_path", ""),
            concept["created_at"],
            concept["updated_at"],
        ),
    )
    conn.commit()
    return concept_id, True


def link_claim_concept(conn, claim_id: str, concept_id: str) -> None:
    """INSERT OR IGNORE a claim_concepts row (idempotent).

    Security (T-03-03): parameterized ? placeholders throughout.
    """
    conn.execute(
        "INSERT OR IGNORE INTO claim_concepts (claim_id, concept_id) VALUES (?, ?)",
        (claim_id, concept_id),
    )
    conn.commit()


def update_source_wiki_path(conn, source_id: str, wiki_path: str) -> None:
    """Update the wiki_path column for a source row.

    wiki_path is mutable (only raw_path has the immutability trigger).
    Security (T-03-03): parameterized ? placeholders.
    """
    conn.execute(
        "UPDATE sources SET wiki_path = ? WHERE id = ?",
        (wiki_path, source_id),
    )
    conn.commit()
