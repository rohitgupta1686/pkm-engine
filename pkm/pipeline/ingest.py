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
import re
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
    update_concept_synthesis,
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


# Matches positional paragraph labels the LLM emits for claim provenance, e.g.
# "para_1", "para_2". The LLM cannot know the deterministic chk_<hash>_NNN ids.
_PARA_RE = re.compile(r"^para_(\d+)$")


def _resolve_claim_chunk_id(
    raw: str | None,
    valid_chunk_ids: set[str],
    ordinal_to_chunk_id: dict[int, str],
) -> str | None:
    """Map an LLM-emitted claim chunk_id to a real chunks.id, else None.

    claims.chunk_id has a hard FK to chunks(id) (AD-6). The summarizer /
    extractor prompts instruct the model to emit positional labels ("para_1")
    or the "null" sentinel because it cannot see the deterministic chunk ids.
    Any non-null value that isn't a real chunks.id would crash ingest on the FK
    (05-03 live bug). Resolve BEFORE insert so the FK contract is always
    satisfied:

      - None / "null" sentinel -> None  (nullable FK satisfied; registry.py
                                          also coerces "null"->None, this is
                                          defense-in-depth at the call site)
      - a real chunks.id       -> kept verbatim
      - "para_N"               -> ordinal N-1's chunk id when in range,
                                  else None (provenance best-effort; chunks are
                                  ~1200-token windows, not paragraphs, so the
                                  mapping is heuristic — see DECISIONS T2-05-04)
      - anything else          -> None
    """
    if raw is None or not isinstance(raw, str):
        return None
    if raw == "null":
        return None
    if raw in valid_chunk_ids:
        return raw
    m = _PARA_RE.match(raw)
    if m:
        ordinal = int(m.group(1)) - 1  # para_1 -> ordinal 0
        return ordinal_to_chunk_id.get(ordinal)
    return None


def _run_concept_synthesis(
    conn,
    llm_client: Any,
    vault_root: Path,
    concept_names: list[str],
    concept_id_map: dict[str, str],
    source_slug: str,
    now_str: str,
) -> None:
    """Run ConceptSynthesisAgent for each concept linked to a source (post-commit).

    Idempotent: skips concepts whose claim set hasn't changed since last synthesis.
    Best-effort: exceptions are logged and do not propagate (source page already written).

    Args:
        conn:            libsql connection (claims must already be committed).
        llm_client:      LLMClient instance.
        vault_root:      pathlib.Path to vault root.
        concept_names:   Names of concepts linked to the source just ingested.
        concept_id_map:  Map from concept name -> concept_id in DB.
        source_slug:     Slug of the source page (used as provenance link).
        now_str:         ISO timestamp string for this run.
    """
    import hashlib
    import json

    from pkm.agents.concept_synthesis_agent import ConceptSynthesisAgent

    _concept_synthesis_agent = ConceptSynthesisAgent()

    for name in concept_names:
        cid = concept_id_map.get(name, make_concept_id(name))

        # Gather all claims for this concept (across all sources)
        rows = conn.execute(
            "SELECT cl.statement FROM claims cl "
            "JOIN claim_concepts cc ON cc.claim_id = cl.id "
            "WHERE cc.concept_id = ?",
            (cid,)
        ).fetchall()
        claim_statements = [r[0] for r in rows]

        if not claim_statements:
            continue

        # Idempotency: hash the sorted set of claim IDs
        claim_id_rows = conn.execute(
            "SELECT cl.id FROM claims cl "
            "JOIN claim_concepts cc ON cc.claim_id = cl.id "
            "WHERE cc.concept_id = ? ORDER BY cl.id",
            (cid,)
        ).fetchall()
        claim_ids_sorted = [r[0] for r in claim_id_rows]
        new_hash = hashlib.sha256(json.dumps(claim_ids_sorted).encode()).hexdigest()

        # Check existing synthesis hash
        row = conn.execute(
            "SELECT synthesis_claim_hash FROM concepts WHERE id = ?", (cid,)
        ).fetchone()
        existing_hash = row[0] if row and row[0] else None

        if existing_hash == new_hash:
            # Claim set unchanged — skip synthesis (idempotent, no cost)
            logger.debug(
                "_run_concept_synthesis: concept %s unchanged (hash=%s), skipping", name, new_hash[:8]
            )
            continue

        # Build input text for the agent
        claims_block = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(claim_statements))
        concept_input = f"CONCEPT: {name}\n\nCLAIMS:\n{claims_block}"

        try:
            synthesis_output = _concept_synthesis_agent.run(llm_client, concept_input, source_id=cid)
        except RuntimeError:
            # Cache hit with no restorable output — skip
            logger.debug(
                "_run_concept_synthesis: concept %s had cache hit with no restorable output", name
            )
            continue
        except Exception as exc:
            logger.warning(
                "_run_concept_synthesis: synthesis failed for concept %s: %s", name, exc
            )
            continue

        # Validate the result is a ConceptSynthesisOutput — if the mock/client
        # returned something else (e.g. an empty string), skip gracefully.
        from pkm.schemas.agent_io import ConceptSynthesisOutput
        if not isinstance(synthesis_output, ConceptSynthesisOutput):
            logger.debug(
                "_run_concept_synthesis: concept %s returned unexpected type %s, skipping",
                name, type(synthesis_output).__name__,
            )
            continue

        try:
            # Persist synthesis to DB (own commit — outside main transaction)
            update_concept_synthesis(
                conn, cid, new_hash,
                synthesis_output.explanation,
                synthesis_output.related_concepts,
                synthesis_output.evidence_claims,
                commit=True,
            )

            # Re-render the concept page with synthesis
            write_concept_page(
                conn, vault_root, cid, name, source_slug,
                synthesis=synthesis_output,
            )
        except Exception as exc:
            logger.warning(
                "_run_concept_synthesis: failed to persist synthesis for concept %s: %s", name, exc
            )
            continue


def run_ingest(
    conn,
    llm_client: Any,
    vault_root: Path,
    raw_text: str,
    raw_path: str,
    new_only: bool = True,
    now: datetime | None = None,
    cf_account_id: str = "",
    cf_api_token: str = "",
) -> dict:
    """Run the full ingest pipeline for a single raw Markdown capture.

    Args:
        conn:           libsql connection (auto-migrated, from registry.connect).
        llm_client:     LLMClient instance with .call() method.
        vault_root:     pathlib.Path to the vault root directory.
        raw_text:       Full text of the raw capture (including front matter).
        raw_path:       The file path that was read (stored in sources.raw_path).
        new_only:       If True, short-circuit when source has already been processed.
        now:            Optional fixed timestamp for deterministic testing; defaults to UTC now.
        cf_account_id:  Cloudflare account ID for Workers AI + Vectorize (Phase 6).
                        Empty string = skip embed step (safe for local dev / tests).
        cf_api_token:   CF API token with Workers AI:Read + Vectorize:Edit scope.
                        Empty string = skip embed step.

    Returns:
        dict with keys:
            deduped     (bool)   — True if this was a no-op re-run
            source_id   (str)
            wiki_path   (str | None)  — None when deduped=True and no prior wiki_path
            n_claims    (int)    — 0 when deduped=True
            n_concepts  (int)    — 0 when deduped=True
            embed       (dict)   — {embedded, skipped, failed}; all zeros when deduped=True
                                   or CF creds are not configured
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
            if existing_wiki_path is not None:
                # Fully processed: all agent runs complete AND wiki page exists.
                logger.debug(
                    "run_ingest: deduped source %s (new_only short-circuit)", source_id
                )
                return {
                    "deduped": True,
                    "source_id": source_id,
                    "wiki_path": existing_wiki_path,
                    "n_claims": 0,
                    "n_concepts": 0,
                    "embed": {"embedded": 0, "skipped": 0, "failed": 0},
                }
            # B-05-02: agent_runs are present but wiki_path IS NULL — the original
            # ingest run crashed after agent execution but before vault write (e.g.
            # the 05-03 FK bug). Fall through and re-attempt synthesis. The existing
            # agent_runs "ok" rows mean LLMClient will return cached results
            # (RuntimeError "cache hit") rather than making new API calls, so this
            # re-attempt is effectively free.
            logger.debug(
                "run_ingest: source %s has agent_runs but no wiki_path — re-attempting synthesis",
                source_id,
            )

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
    # Steps 4-8: All DB writes + log append are atomic within a single transaction.
    # On any exception, conn.rollback() fires and the exception re-raises.
    # -------------------------------------------------------------------------
    try:
        conn.execute("BEGIN")

        # Step 4 (DB): insert chunks (commit=False — inside explicit transaction)
        insert_chunks(conn, source_id, chunk_records, commit=False)

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

        # Real chunk ids inserted above; used to validate/map LLM provenance
        # labels (positional "para_N" or "null") to a chunks.id that satisfies
        # the claims.chunk_id FK. See _resolve_claim_chunk_id (05-03 fix).
        valid_chunk_ids = set(ordinal_to_chunk_id.values())

        for claim in claims_list:
            resolved_chunk_id = _resolve_claim_chunk_id(
                claim.chunk_id, valid_chunk_ids, ordinal_to_chunk_id
            )
            claim_row = {
                "source_id": source_id,
                "chunk_id": resolved_chunk_id,
                "statement": claim.statement,
                "subject": claim.subject,
                "predicate": claim.predicate,
                "object": claim.object,
                "claim_type": claim.claim_type,
                "confidence": claim.confidence,
                "status": "candidate",  # status_mapping_contract: initial claims.status is 'candidate'
                "created_at": now_str,
            }
            claim_id_str = insert_claim(conn, claim_row, commit=False)
            persisted_claims.append({
                "id": claim_id_str,
                "statement": claim.statement,
                "chunk_id": resolved_chunk_id,
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
                    }, commit=False)
                    concept_id_map[name] = cid
                else:
                    concept_id_map[name] = existing_cid

                # Link the referenced claims to this concept
                for idx in cm.claim_indices:
                    if idx < len(persisted_claims):
                        link_claim_concept(conn, persisted_claims[idx]["id"], concept_id_map[name], commit=False)

        # -------------------------------------------------------------------------
        # Step 7: Write vault pages
        # -------------------------------------------------------------------------
        # Guard: write_source_page requires a non-None summary (for summary.thesis).
        # Post B-05-02 durable-summary fix, a cache hit normally RESTORES the real
        # SummarizerOutput from agent_runs.output_json, so summarizer_output is the
        # real object here. This stub is the last-resort fallback only for a LEGACY
        # ok-row written before the 004 migration (no output_json to restore) whose
        # SummarizerAgent.run() therefore still raised RuntimeError above.
        if summarizer_output is None:
            from pkm.schemas.agent_io import SummarizerOutput as _SO
            summarizer_output = _SO(
                thesis="(summary unavailable — cached run)", key_claims=[], caveats=[], summary_confidence=0.0
            )

        source_slug = slugify(title)

        # Extract entities for frontmatter from KGAgent output
        entities_for_fm: dict = {"companies": [], "people": [], "concepts": []}
        if kg_output is not None:
            for node in kg_output.nodes:
                label = node.label.lower()
                if label in ("company", "organization", "org"):
                    entities_for_fm["companies"].append(node.name)
                elif label in ("person", "author", "ceo", "founder"):
                    entities_for_fm["people"].append(node.name)
                else:
                    entities_for_fm["concepts"].append(node.name)

        wiki_path = write_source_page(
            conn, vault_root, source_record, summarizer_output, persisted_claims, concept_names,
            commit=False,
            entities=entities_for_fm,
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

        # All DB writes succeeded — commit the transaction
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    # -------------------------------------------------------------------------
    # Step 6.5: Embed claims into Cloudflare Vectorize (best-effort, after commit).
    # Runs outside the main transaction so a CF outage never rolls back wiki pages.
    # No-op when cf_account_id / cf_api_token are empty (local dev, tests).
    # -------------------------------------------------------------------------
    embed_result: dict = {"embedded": 0, "skipped": 0, "failed": 0}
    if cf_account_id and cf_api_token and persisted_claims:
        try:
            from pkm.retrieval.embed import embed_claims
            embed_result = embed_claims(
                conn=conn,
                claims=persisted_claims,
                source_id=source_id,
                raw_path=raw_path,
                cf_account_id=cf_account_id,
                cf_api_token=cf_api_token,
            )
        except Exception as exc:
            logger.warning(
                "run_ingest: embed step failed for source %s: %s", source_id, exc
            )
            embed_result = {"embedded": 0, "skipped": 0, "failed": len(persisted_claims)}

    # -------------------------------------------------------------------------
    # Step 7.5: Concept synthesis — runs after main transaction (claims committed first).
    # Best-effort: if synthesis fails, the source page is still written. No rollback.
    # No-op when llm_client is None (some test modes) or no concepts were extracted.
    # -------------------------------------------------------------------------
    if llm_client is not None and concept_names:
        try:
            _run_concept_synthesis(
                conn, llm_client, vault_root,
                concept_names, concept_id_map, source_slug, now_str,
            )
        except Exception as exc:
            logger.warning(
                "run_ingest: concept synthesis step failed for source %s: %s", source_id, exc
            )

    # -------------------------------------------------------------------------
    # Step 9: Return result
    # -------------------------------------------------------------------------
    return {
        "deduped": False,
        "source_id": source_id,
        "wiki_path": wiki_path,
        "n_claims": n_claims,
        "n_concepts": n_concepts,
        "embed": embed_result,
    }
