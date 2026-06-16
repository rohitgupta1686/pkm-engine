"""
Idempotent vault writer for the PKM pipeline.

Renders wiki/sources/<slug>.md and wiki/concepts/<slug>.md from structured
pipeline data. All renders are byte-stable given identical inputs — timestamps
are passed in (never generated internally) so re-runs produce no diff.

Security:
  T-03-04: slugify strips to [a-z0-9-] — no path traversal via titles/names.
  T-03-05: Only wiki_path is written; raw_path is never touched.
  T-03-06: provenance_anchor_contract enforced — every claim bullet ends
           with ^cite:<source_id>#<chunk_id> (literal "null" when absent).

Vault root: always passed in as a pathlib.Path argument — never hardcoded.
The pipeline/CLI reads it from Settings.vault_path or a CLI flag.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

from pkm.ingest.hashing import slugify
from pkm.store.registry import update_source_wiki_path

if TYPE_CHECKING:
    from pkm.schemas.agent_io import SummarizerOutput

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Front-matter renderer (deterministic — fixed key order for byte stability)
# ---------------------------------------------------------------------------

_FRONT_MATTER_KEYS_SOURCE = (
    "id", "type", "title", "created", "updated",
    "source_paths", "tags", "entities", "confidence", "status",
)

_FRONT_MATTER_KEYS_CONCEPT = (
    "id", "type", "title", "created", "updated",
    "source_paths", "tags", "entities", "confidence", "status",
)


def _render_front_matter(fields: dict) -> str:
    """Render YAML front matter in a fixed key order for byte stability.

    Only the keys in the declared order are emitted (extras are ignored).
    String values are quoted; lists render as YAML sequences; dicts as mappings.
    """
    lines = ["---"]
    for key in _FRONT_MATTER_KEYS_SOURCE:
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for k, v in value.items():
                if isinstance(v, list):
                    if not v:
                        lines.append(f"  {k}: []")
                    else:
                        lines.append(f"  {k}:")
                        for item in v:
                            lines.append(f"    - {item}")
                else:
                    lines.append(f"  {k}: {v}")
        elif isinstance(value, str):
            # Quote strings that contain : or leading spaces to be safe
            if ":" in value or value.startswith(" "):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Concept resolution (PIPE-04 three-tier, tier-3 stub)
# ---------------------------------------------------------------------------

def resolve_concept(conn, name: str) -> str | None:
    """Three-tier concept resolution (mirrors resolver.resolve for entities).

    Tier 1: Exact match on concepts.name
    Tier 2: Alias match via concept_aliases
    Tier 3: Embedding similarity — MVP stub, returns None

    Args:
        conn: libsql connection.
        name: Concept name or alias to resolve.

    Returns:
        Concept id string if resolved, None otherwise.
    """
    # Tier 1: exact match
    row = conn.execute(
        "SELECT id FROM concepts WHERE name = ?",
        (name,),
    ).fetchone()
    if row is not None:
        return row[0]

    # Tier 2: alias match
    row = conn.execute(
        "SELECT c.id FROM concepts c "
        "JOIN concept_aliases ca ON ca.concept_id = c.id "
        "WHERE ca.alias = ?",
        (name,),
    ).fetchone()
    if row is not None:
        return row[0]

    # Tier 3: embedding similarity — MVP stub
    logger.debug(
        "resolve_concept: embedding tier not implemented for MVP; returning None for '%s'",
        name,
    )
    return None


# ---------------------------------------------------------------------------
# Source page writer
# ---------------------------------------------------------------------------

def write_source_page(
    conn,
    vault_root: pathlib.Path,
    source_record: dict,
    summary: "SummarizerOutput",
    claims: list[dict],
    concept_names: list[str],
    commit: bool = True,
) -> str:
    """Render wiki/sources/<slug>.md for a source, idempotently.

    Uses only data passed in — never calls datetime.now() internally so
    re-runs with identical inputs produce byte-identical output.

    Provenance anchor contract (T-03-06): every claim bullet ends with
    ^cite:<source_id>#<chunk_id>; literal "null" when chunk_id is absent.

    Path traversal prevention (T-03-04): slug derived from source title via
    slugify(), which strips to [a-z0-9-].

    Args:
        conn:          libsql connection (used to update sources.wiki_path).
        vault_root:    pathlib.Path to vault root (e.g. /path/to/pkm-vault).
        source_record: Dict matching sources column contract.
        summary:       SummarizerOutput instance from SummarizerAgent.
        claims:        List of dicts with 'statement' and 'chunk_id' keys.
        concept_names: List of concept names extracted for this source.

    Returns:
        Vault-relative wiki path string (e.g. "wiki/sources/my-article.md").
    """
    source_id = source_record["id"]
    title = source_record.get("title") or source_id
    slug = slugify(title)
    wiki_path = f"wiki/sources/{slug}.md"
    out_path = vault_root / wiki_path

    # Front matter — deterministic field order, timestamps from record (not now())
    front_matter = _render_front_matter({
        "id": source_id,
        "type": "source",
        "title": title,
        "created": source_record.get("created_at", ""),
        "updated": source_record.get("updated_at", ""),
        "source_paths": [f"raw/{source_record.get('raw_path', '')}"],
        "tags": [],
        "entities": {"companies": [], "people": [], "concepts": []},
        "confidence": source_record.get("credibility", 0.7),
        "status": "active",
    })

    # Body — sections in article-note heading order
    lines: list[str] = []

    # Title heading
    lines.append(f"# {title}\n")

    # Source metadata block
    url = source_record.get("url") or ""
    author = source_record.get("author") or ""
    date_published = source_record.get("date_published") or ""
    lines.append(f"> **Source:** {url}")
    lines.append(f"> **Author:** {author}")
    lines.append(f"> **Published:** {date_published}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # TL;DR
    lines.append("## TL;DR")
    lines.append("")
    lines.append(summary.thesis)
    lines.append("")

    # Key Claims — each bullet ends with ^cite:<source_id>#<chunk_id>
    lines.append("## Key Claims")
    lines.append("")
    for claim in claims:
        statement = claim["statement"]
        chunk_id = claim.get("chunk_id") or "null"
        # Provenance anchor contract: always emit ^cite even for null chunk_id
        lines.append(f"- {statement} ^cite:{source_id}#{chunk_id}")
    lines.append("")

    # Evidence & Data (empty placeholder — agents fill later)
    lines.append("## Evidence & Data")
    lines.append("")

    # MyThinking (never overwritten by agents)
    lines.append("## MyThinking")
    lines.append("")

    # Contradicts / Confirms (empty)
    lines.append("## Contradicts / Confirms")
    lines.append("")

    # Extracted Concepts — [[wikilinks]]
    lines.append("## Extracted Concepts")
    lines.append("")
    for name in concept_names:
        cslug = slugify(name)
        lines.append(f"[[{cslug}]]")
    lines.append("")

    # Open Questions (empty)
    lines.append("## Open Questions")
    lines.append("")

    body = "\n".join(lines)
    content = front_matter + "\n" + body

    # Write (idempotent — same content → same bytes)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    # Update sources.wiki_path (mutable — not raw_path)
    update_source_wiki_path(conn, source_id, wiki_path, commit=commit)

    return wiki_path


# ---------------------------------------------------------------------------
# Concept page writer
# ---------------------------------------------------------------------------

def write_concept_page(
    conn,
    vault_root: pathlib.Path,
    concept_id: str,
    name: str,
    source_slug: str,
) -> str:
    """Render or update wiki/concepts/<slug>.md for a concept, idempotently.

    Reads the existing file (if present) and only appends the source link if
    it is not already there — prevents duplication on re-run.

    Path traversal prevention (T-03-04): slug derived from name via slugify().

    Args:
        conn:        libsql connection (reads concept metadata).
        vault_root:  pathlib.Path to vault root.
        concept_id:  Concept id (cpt_<slug>).
        name:        Human-readable concept name.
        source_slug: Slug of the source page that contributed this concept.

    Returns:
        Vault-relative wiki path (e.g. "wiki/concepts/operating-leverage.md").
    """
    slug = slugify(name)
    wiki_path = f"wiki/concepts/{slug}.md"
    out_path = vault_root / wiki_path

    # Fetch concept metadata from DB
    row = conn.execute(
        "SELECT definition, domain, created_at, updated_at FROM concepts WHERE id = ?",
        (concept_id,),
    ).fetchone()
    if row:
        definition, domain, created_at, updated_at = row
    else:
        definition = ""
        domain = ""
        created_at = ""
        updated_at = ""

    source_link = f"[[{source_slug}]]"

    if out_path.exists():
        # Read existing page and add source link only if not already present
        existing = out_path.read_text(encoding="utf-8")
        if source_link in existing:
            # Already linked — no change needed (idempotent)
            return wiki_path
        # Add source link to both ## Provenance and ## Instances/Evidence sections
        updated = _append_source_link(existing, source_link)
        out_path.write_text(updated, encoding="utf-8")
        return wiki_path

    # New page — render from scratch
    front_matter = _render_front_matter({
        "id": concept_id,
        "type": "concept",
        "title": name,
        "created": created_at,
        "updated": updated_at,
        "source_paths": [],
        "tags": [],
        "entities": {"companies": [], "people": [], "concepts": []},
        "confidence": 0.7,
        "status": "active",
    })

    lines: list[str] = []
    lines.append(f"# {name}\n")
    lines.append("---")
    lines.append("")

    lines.append("## One-sentence Definition")
    lines.append("")
    if definition:
        lines.append(definition)
    lines.append("")

    lines.append("## Explanation")
    lines.append("")

    lines.append("## Related Concepts")
    lines.append("")

    lines.append("## Instances/Evidence")
    lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(source_link)
    lines.append("")

    body = "\n".join(lines)
    content = front_matter + "\n" + body

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return wiki_path


def _append_source_link(existing: str, source_link: str) -> str:
    """Add source_link to ## Provenance section.

    Only ## Provenance is auto-maintained by the vault writer (per concept-note
    template contract). ## Instances/Evidence is for manual/agent additions.
    """
    return _insert_into_section(existing, "## Provenance", source_link)


def _insert_into_section(text: str, section_heading: str, line_to_insert: str) -> str:
    """Insert line_to_insert into a section identified by section_heading.

    If the section does not exist, return text unchanged.
    Inserts after any existing content in the section, before the next heading.
    Does not insert if line_to_insert is already present in the section.
    """
    if section_heading not in text:
        return text

    lines = text.split("\n")
    in_section = False
    insert_at = None

    for i, line in enumerate(lines):
        if line.strip() == section_heading.strip():
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and line.strip() != section_heading.strip():
                # Next section starts — insert before this line
                insert_at = i
                break
            if line.strip() == line_to_insert.strip():
                # Already present in section
                return text

    if in_section and insert_at is None:
        # Section is at end of file
        insert_at = len(lines)

    if insert_at is None:
        return text

    lines.insert(insert_at, line_to_insert)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Log appender (the only non-idempotent writer — called once per run)
# ---------------------------------------------------------------------------

def append_log(vault_root: pathlib.Path, line: str) -> None:
    """Append exactly one line to log.md.

    The pipeline passes the full formatted line (including the newline) so
    this function is a thin wrapper around append-mode open.

    Args:
        vault_root: pathlib.Path to vault root.
        line:       The line to append (should end with \\n).
    """
    log_path = vault_root / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
