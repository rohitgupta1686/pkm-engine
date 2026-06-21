import pathlib
import uuid
from datetime import datetime, timezone

import libsql_experimental as libsql

from pkm.config import Settings


def get_migrations_dir() -> pathlib.Path:
    """Return the path to the migrations/sqlite directory."""
    return pathlib.Path(__file__).parent.parent.parent / "migrations" / "sqlite"


def _run_migrations(conn) -> None:
    """Execute all migration files in order. IF NOT EXISTS guards make this idempotent.

    004 uses `ALTER TABLE ... ADD COLUMN`, which SQLite cannot guard with
    IF NOT EXISTS. On a re-connect against an already-migrated DB it raises
    "duplicate column name"; we swallow exactly that error so migrations stay
    idempotent. Any other error propagates.
    """
    migrations_dir = get_migrations_dir()
    for filename in (
        "001_init.sql",
        "002_graph_tables.sql",
        "003_dashboard_counters.sql",
        "004_agent_runs_output.sql",
        "005_concept_synthesis.sql",
    ):
        migration_path = migrations_dir / filename
        sql = migration_path.read_text()
        try:
            conn.executescript(sql)
        except Exception as exc:  # noqa: BLE001 — narrow check below, re-raise otherwise
            if "duplicate column name" in str(exc).lower():
                continue
            raise


def _now_iso() -> str:
    """UTC timestamp string for counter updated_at."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
# Dashboard counter helpers (GUARD-03 — incrementally-maintained counter rows)
# ---------------------------------------------------------------------------

def bump_counter(conn, key: str, delta: int = 1, commit: bool = True) -> int:
    """Increment a dashboard counter by delta (UPSERT), return the new value.

    Lazy-creates the row on first bump. Security (T-07-02-01): parameterized ?
    placeholders + INSERT ... ON CONFLICT UPDATE — no f-string value interpolation.
    """
    now = _now_iso()
    conn.execute(
        "INSERT INTO dashboard_counters (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value, "
        "updated_at = excluded.updated_at",
        (key, delta, now),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT value FROM dashboard_counters WHERE key = ?",
        (key,),
    ).fetchone()
    return int(row[0]) if row else 0


def read_counter(conn, key: str) -> int:
    """Return a counter value (0 if the row does not exist yet)."""
    row = conn.execute(
        "SELECT value FROM dashboard_counters WHERE key = ?",
        (key,),
    ).fetchone()
    return int(row[0]) if row else 0


def read_all_counters(conn) -> dict[str, int]:
    """Return all counter rows as a {key: value} dict."""
    rows = conn.execute("SELECT key, value FROM dashboard_counters").fetchall()
    return {r[0]: int(r[1]) for r in rows}


def seed_counters_from_live_counts(conn, commit: bool = True) -> dict[str, int]:
    """One-time backfill: set dashboard_counters to absolute live-table COUNT(*).

    Closes the Phase-7 carry-in (STATE.md "Known follow-up"): dashboard_counters
    rows only bump on new inserts, so pre-Phase-7 data (~160 claims) was never
    counted and the dashboard read 0 for Sources/Claims/Concepts. This writes
    absolute values via INSERT OR REPLACE — idempotent (re-running yields
    identical values) — NOT increments. Do not use bump_counter here (it
    increments).

    Only seeds the counter keys already used by bump_counter in the insert
    paths (sources_total / claims_total / concepts_total), from their
    corresponding live-table COUNT(*).

    Security (T-02-08): parameterized ? placeholders; counter keys and table
    names are hardcoded constants, not user input.
    """
    seeding = {
        "sources_total": "SELECT COUNT(*) FROM sources",
        "claims_total": "SELECT COUNT(*) FROM claims",
        "concepts_total": "SELECT COUNT(*) FROM concepts",
    }
    now = _now_iso()
    result: dict[str, int] = {}
    for key, count_sql in seeding.items():
        count = int(conn.execute(count_sql).fetchone()[0])
        conn.execute(
            "INSERT OR REPLACE INTO dashboard_counters (key, value, updated_at) "
            "VALUES (?, ?, ?)",
            (key, count, now),
        )
        result[key] = count
    if commit:
        conn.commit()
    return result


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def upsert_source(conn, record: dict, commit: bool = True) -> tuple[str, bool]:
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
    # GUARD-03: bump sources_total only for newly-created rows (created=True).
    bump_counter(conn, "sources_total", 1, commit=False)
    if commit:
        conn.commit()
    return source_id, True


def insert_chunks(conn, source_id: str, chunks: list[dict], commit: bool = True) -> int:
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
    if commit:
        conn.commit()
    return inserted


def insert_claim(conn, claim: dict, commit: bool = True) -> str:
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
    # The agent layer uses the string "null" as the chunk_id sentinel for
    # untraceable claims (Phase-2 contract; see test_summarizer_chunk_id_rule).
    # claims.chunk_id has an FK to chunks(id), and no chunks row with id="null"
    # exists, so storing the literal "null" string throws FOREIGN KEY constraint
    # failed on Turso (FKs enforced; local test SQLite does not enforce FKs by
    # default, so the suite missed it — found in 05-03 live deploy). Normalize the
    # sentinel to SQL NULL at the insert boundary; vault.py renders None back to
    # "null" for citations, preserving the provenance-anchor contract.
    chunk_id = claim.get("chunk_id")
    if isinstance(chunk_id, str) and chunk_id == "null":
        chunk_id = None
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
            chunk_id,
            claim["statement"],
            claim.get("subject"),
            claim.get("predicate"),
            claim.get("object"),
            claim.get("claim_type"),
            claim.get("confidence", 0.5),
            claim["created_at"],
        ),
    )
    # GUARD-03: claims are always new rows → bump claims_total on every insert.
    bump_counter(conn, "claims_total", 1, commit=False)
    if commit:
        conn.commit()
    return claim_id


def upsert_concept(conn, concept: dict, commit: bool = True) -> tuple[str, bool]:
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
    # GUARD-03: bump concepts_total only for newly-created rows (created=True).
    bump_counter(conn, "concepts_total", 1, commit=False)
    if commit:
        conn.commit()
    return concept_id, True


def link_claim_concept(conn, claim_id: str, concept_id: str, commit: bool = True) -> None:
    """INSERT OR IGNORE a claim_concepts row (idempotent).

    Security (T-03-03): parameterized ? placeholders throughout.
    """
    conn.execute(
        "INSERT OR IGNORE INTO claim_concepts (claim_id, concept_id) VALUES (?, ?)",
        (claim_id, concept_id),
    )
    if commit:
        conn.commit()


def update_concept_synthesis(
    conn,
    concept_id: str,
    claim_hash: str,
    explanation: str,
    related: list,
    evidence: list,
    commit: bool = True,
) -> None:
    """Update concept synthesis columns after a ConceptSynthesisAgent run.

    Security (T-03-03): parameterized ? placeholders throughout.

    Args:
        conn:        libsql connection.
        concept_id:  Concept id (cpt_<slug>).
        claim_hash:  SHA-256 of sorted claim ID set (idempotency key).
        explanation: Prose explanation from ConceptSynthesisOutput.
        related:     List of related concept name strings.
        evidence:    List of verbatim evidence claim strings.
        commit:      Whether to commit immediately.
    """
    import json
    now = _now_iso()
    conn.execute(
        "UPDATE concepts SET synthesis_claim_hash = ?, synthesis_explanation = ?, "
        "synthesis_related = ?, synthesis_evidence = ?, updated_at = ? WHERE id = ?",
        (claim_hash, explanation, json.dumps(related), json.dumps(evidence), now, concept_id),
    )
    if commit:
        conn.commit()


def update_source_wiki_path(conn, source_id: str, wiki_path: str, commit: bool = True) -> None:
    """Update the wiki_path column for a source row.

    wiki_path is mutable (only raw_path has the immutability trigger).
    Security (T-03-03): parameterized ? placeholders.
    """
    conn.execute(
        "UPDATE sources SET wiki_path = ? WHERE id = ?",
        (wiki_path, source_id),
    )
    if commit:
        conn.commit()
