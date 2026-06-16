"""
Sequential ingest coordinator for the PKM pipeline.

Runs a raw Markdown capture through the full agent pipeline and writes
the results to the vault and DB. Designed to be called from the CLI or
from tests (pure function — no global state).

Flow (tech spec §7.1):
  1. Hash content, derive source_id
  2. upsert_source (created: bool)
  3. If new_only and not created: short-circuit if agent_runs already has prior ok rows
  4. chunk_text, insert_chunks
  5. Run agents: Reader -> Summarizer -> ConceptExtractor -> KGAgent
  6. Persist claims + concepts + claim_concepts links
  7. Write vault pages: source page, concept pages
  8. Append one line to log.md
  9. Return result dict

Security (T-03-07, T-03-08, T-03-09):
  - raw_path is stored as-is (no shell interpolation); file is read by CLI before calling here
  - new_only + agent_runs cache ensure 0 API calls on re-ingest (spend-cap protection)
  - This module never logs or returns secrets; Settings is not passed in
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pkm.agents.concept_extractor import ConceptExtractor
from pkm.agents.kg_agent import KGAgent
from pkm.agents.reader_agent import ReaderAgent
from pkm.agents.summarizer_agent import SummarizerAgent
from pkm.ingest.chunker import chunk_text
from pkm.ingest.hashing import (
    chunk_id,
    concept_id as make_concept_id,
    sha256_content,
    slugify,
    source_id_from_hash,
)
from pkm.store.registry import (
    insert_chunks,
    insert_claim,
    link_claim_concept,
    upsert_concept,
    upsert_source,
)
from pkm.store.vault import append_log, resolve_concept, write_concept_page, write_source_page

logger = logging.getLogger(__name__)

# Agent names as declared in each agent's ClassVar 'role' — used for agent_runs queries.
_READER_ROLE = "reader_agent"
_SUMMARIZER_ROLE = "summarizer_agent"
_EXTRACTOR_ROLE = "concept_extractor"
_KG_ROLE = "kg_agent"

_ALL_AGENT_ROLES = (_READER_ROLE, _SUMMARIZER_ROLE, _EXTRACTOR_ROLE, _KG_ROLE)

# Locked set of valid source types matching the CHECK constraint in sources.type
_VALID_SOURCE_TYPES = frozenset({"Article", "Book", "Paper", "Newsletter", "Podcast", "Meeting", "Note"})


def _normalize_source_type(value: str | None) -> str:
    """Normalize a raw source type value to one of the 7 CHECK-valid values.

    Title-cases the trimmed value (maps 'article' -> 'Article', 'paper' -> 'Paper').
    Falls back to 'Article' for falsy or unrecognized values.
    """
    if not value:
        return "Article"
    normalized = value.strip().title()
    if normalized in _VALID_SOURCE_TYPES:
        return normalized
    return "Article"


def _now_iso(dt: datetime | None) -> str:
    """Return an ISO-8601 UTC timestamp string, defaulting to now if dt is None."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_prior_agent_runs(conn, source_id: str) -> bool:
    """Return True only when ALL four core agents have an ok row for this source.

    Uses COUNT(DISTINCT agent) so a source partially processed (e.g. only
    reader_agent completed) returns False and will NOT be short-circuited.
    """
    row = conn.execute(
        "SELECT COUNT(DISTINCT agent) FROM agent_runs "
        "WHERE source_id = ? AND status = 'ok' AND agent IN (?, ?, ?, ?)",
        (source_id, *_ALL_AGENT_ROLES),
    ).fetchone()
    count = row[0] if row else 0
    return count == len(_ALL_AGENT_ROLES)


def _parse_title_from_front_matter(raw_text: str) -> str | None:
    """Extract the title field from YAML front matter if present."""
    if not raw_text.startswith("---"):
        return None
    end = raw_text.find("---", 3)
    if end == -1:
        return None
    front_matter_block = raw_text[3:end]
    for line in front_matter_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            value = stripped[len("title:"):].strip().strip('"').strip("'")
            return value if value else None
    return None


def _parse_field_from_front_matter(raw_text: str, field: str) -> str | None:
    """Extract a named field from YAML front matter if present."""
    if not raw_text.startswith("---"):
        return None
    end = raw_text.find("---", 3)
    if end == -1:
        return None
    block = raw_text[3:end]
    prefix = f"{field}:"
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip().strip('"').strip("'")
            return value if value else None
    return None


def run_ingest(
    conn,
    llm_client: Any,
    vault_root: Path,
    raw_text: str,
    raw_path: str,
    new_only: bool = True,
    now: datetime | None = None,
) -> dict:
    """Run the full ingest pipeline for a single raw Markdown capture.

    Args:
        conn:       libsql connection (auto-migrated, from registry.connect).
        llm_client: LLMClient instance with .call() method.
        vault_root: pathlib.Path to the vault root directory.
        raw_text:   Full text of the raw capture (including front matter).
        raw_path:   The file path that was read (stored in sources.raw_path).
        new_only:   If True, short-circuit when source has already been processed.
        now:        Optional fixed timestamp for deterministic testing; defaults to UTC now.

    Returns:
        dict with keys:
            deduped     (bool)   — True if this was a no-op re-run
            source_id   (str)
            wiki_path   (str | None)  — None when deduped=True and no prior wiki_path
            n_claims    (int)    — 0 when deduped=True
            n_concepts  (int)    — 0 when deduped=True
    """
    now_str = _now_iso(now)

    # -------------------------------------------------------------------------
    # Step 1: Hash + derive IDs
    # -------------------------------------------------------------------------
    content_hash = sha256_content(raw_text)
    source_id = source_id_from_hash(content_hash)
    source_hash12 = content_hash[:12]

    # Parse title and other metadata from front matter
    title = _parse_title_from_front_matter(raw_text) or raw_path
    author = _parse_field_from_front_matter(raw_text, "author") or ""
    url = _parse_field_from_front_matter(raw_text, "url") or ""
    date_saved = _parse_field_from_front_matter(raw_text, "date_saved") or now_str
    source_type = _normalize_source_type(_parse_field_from_front_matter(raw_text, "type"))

    # -------------------------------------------------------------------------
    # Step 2: Upsert source
    # -------------------------------------------------------------------------
    source_record: dict = {
        "id": source_id,
        "content_hash": content_hash,
        "type": source_type,
        "title": title,
        "author": author,
        "url": url,
        "date_saved": date_saved,
        "raw_path": raw_path,
        "status": "captured",
        "created_at": now_str,
        "updated_at": now_str,
    }
    _, created = upsert_source(conn, source_record)

    # -------------------------------------------------------------------------
    # Step 3: Short-circuit for new_only mode when source already fully processed
    # -------------------------------------------------------------------------
    if new_only and not created:
        if _has_prior_agent_runs(conn, source_id):
            # Retrieve the existing wiki_path from DB
            row = conn.execute(
                "SELECT wiki_path FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            existing_wiki_path = row[0] if row and row[0] else None
            logger.debug(
                "run_ingest: deduped source %s (new_only short-circuit)", source_id
            )
            return {
                "deduped": True,
                "source_id": source_id,
                "wiki_path": existing_wiki_path,
                "n_claims": 0,
                "n_concepts": 0,
            }

    # -------------------------------------------------------------------------
    # Step 4: Chunk text and insert chunks
    # -------------------------------------------------------------------------
    raw_chunks = chunk_text(raw_text)
    # Build chunk dicts with IDs for DB insert
    chunk_records = []
    for c in raw_chunks:
        cid = chunk_id(source_hash12, c["ordinal"])
        chunk_records.append({
            "id": cid,
            "ordinal": c["ordinal"],
            "char_start": c["char_start"],
            "char_end": c["char_end"],
            "text": c["text"],
            "token_count": c.get("token_count", 0),
        })
    insert_chunks(conn, source_id, chunk_records)

    # Build a lookup: ordinal -> chunk_id for claim mapping
    ordinal_to_chunk_id = {c["ordinal"]: c["id"] for c in chunk_records}

    # -------------------------------------------------------------------------
    # Step 5: Run agents (cache hit = RuntimeError = treat as already done)
    # -------------------------------------------------------------------------
    try:
        clean_md = ReaderAgent().run(llm_client, raw_text, source_id)
    except RuntimeError:
        # Cache hit — already processed; use raw_text as fallback
        logger.debug("ReaderAgent cache hit for source %s", source_id)
        clean_md = raw_text

    try:
        summarizer_output = SummarizerAgent().run(llm_client, clean_md, source_id)
    except RuntimeError:
        logger.debug("SummarizerAgent cache hit for source %s", source_id)
        summarizer_output = None

    try:
        extractor_output = ConceptExtractor().run(llm_client, clean_md, source_id)
    except RuntimeError:
        logger.debug("ConceptExtractor cache hit for source %s", source_id)
        extractor_output = None

    # KGAgent input: a text representation of the claims
    if extractor_output is not None and extractor_output.claims:
        claims_text = "\n".join(
            f"- {c.statement} (chunk_id: {c.chunk_id})" for c in extractor_output.claims
        )
    else:
        claims_text = clean_md

    try:
        kg_output = KGAgent().run(llm_client, claims_text, source_id)
    except RuntimeError:
        logger.debug("KGAgent cache hit for source %s", source_id)
        kg_output = None

    # -------------------------------------------------------------------------
    # Step 6: Persist claims, concepts, and links
    # -------------------------------------------------------------------------
    persisted_claims: list[dict] = []  # dicts with statement, chunk_id, claim_id

    if extractor_output is not None:
        claims_list = extractor_output.claims
    elif summarizer_output is not None:
        claims_list = summarizer_output.key_claims
    else:
        claims_list = []

    for claim in claims_list:
        claim_row = {
            "source_id": source_id,
            "chunk_id": claim.chunk_id,
            "statement": claim.statement,
            "subject": claim.subject,
            "predicate": claim.predicate,
            "object": claim.object,
            "claim_type": claim.claim_type,
            "confidence": claim.confidence,
            "status": "candidate",  # status_mapping_contract: initial claims.status is 'candidate'
            "created_at": now_str,
        }
        claim_id_str = insert_claim(conn, claim_row)
        persisted_claims.append({
            "id": claim_id_str,
            "statement": claim.statement,
            "chunk_id": claim.chunk_id,
        })

    # Collect concept names from extractor output
    concept_names: list[str] = []
    concept_id_map: dict[str, str] = {}  # name -> concept_id in DB

    if extractor_output is not None:
        for cm in extractor_output.concept_matches:
            name = cm.concept_name
            concept_names.append(name)

            # Resolve or create concept
            existing_cid = resolve_concept(conn, name)
            if existing_cid is None:
                cid = make_concept_id(name)
                slug = slugify(name)
                upsert_concept(conn, {
                    "id": cid,
                    "name": name,
                    "wiki_path": f"wiki/concepts/{slug}.md",
                    "created_at": now_str,
                    "updated_at": now_str,
                })
                concept_id_map[name] = cid
            else:
                concept_id_map[name] = existing_cid

            # Link the referenced claims to this concept
            for idx in cm.claim_indices:
                if idx < len(persisted_claims):
                    link_claim_concept(conn, persisted_claims[idx]["id"], concept_id_map[name])

    # -------------------------------------------------------------------------
    # Step 7: Write vault pages
    # -------------------------------------------------------------------------
    # Guard: write_source_page requires a non-None summary (for summary.thesis).
    # If summarizer_output is None (cache hit on a forced re-run), use a minimal stub.
    if summarizer_output is None:
        from pkm.schemas.agent_io import SummarizerOutput as _SO
        summarizer_output = _SO(
            thesis="(summary unavailable — cached run)", key_claims=[], caveats=[], summary_confidence=0.0
        )

    source_slug = slugify(title)
    wiki_path = write_source_page(
        conn, vault_root, source_record, summarizer_output, persisted_claims, concept_names
    )

    for name in concept_names:
        cid = concept_id_map.get(name, make_concept_id(name))
        write_concept_page(conn, vault_root, cid, name, source_slug)

    # -------------------------------------------------------------------------
    # Step 8: Append log line
    # -------------------------------------------------------------------------
    n_claims = len(persisted_claims)
    n_concepts = len(concept_names)
    log_line = (
        f"{now_str} ingest {source_id} -> {wiki_path} "
        f"({n_claims} claims, {n_concepts} concepts)\n"
    )
    append_log(vault_root, log_line)

    # -------------------------------------------------------------------------
    # Step 9: Return result
    # -------------------------------------------------------------------------
    return {
        "deduped": False,
        "source_id": source_id,
        "wiki_path": wiki_path,
        "n_claims": n_claims,
        "n_concepts": n_concepts,
    }
