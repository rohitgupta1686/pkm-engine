"""Single-call ingest orchestration (the redesigned pipeline).

raw capture --> one LLM call --> one Markdown note in <vault>/notes/.

No Turso writes, no chunking, no claim/concept/graph extraction, no embeddings,
no database. The only state it reads is the set of existing note slugs (for
cross-linking) plus recent wildcard frames (for variety); the only state it
writes is the note file. The knowledge artifact is the Markdown vault itself.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pkm.pipeline.synthesize import (
    SYNTH_AGENT_NAME,
    SYNTH_PROMPT_TEMPLATE,
    SYNTH_PROMPT_VERSION,
    synthesize_note,
)
from pkm.store.notes import (
    body_from_raw,
    list_note_slugs,
    recent_wildcard_frames,
    slug_for_raw,
    write_note,
)

logger = logging.getLogger(__name__)

# How many recent notes' wildcard frames to feed back as "avoid repeating".
RECENT_FRAMES_WINDOW = 5

# Minimum non-whitespace body length (chars, after front matter) for a capture to
# be worth synthesizing. Body-less stubs — paywall clips that carry only front
# matter — fall below this and are skipped before the model call, so they can't
# produce hallucinated notes (and don't burn spend).
MIN_BODY_CHARS = 200


def run_note_ingest(
    llm_client,
    vault_root: Path,
    raw_text: str,
    raw_path: str,
    model: str,
    notes_dirname: str = "notes",
    new_only: bool = False,
    min_body_chars: int = MIN_BODY_CHARS,
    prompt_template: str = SYNTH_PROMPT_TEMPLATE,
    prompt_version: str = SYNTH_PROMPT_VERSION,
    agent_name: str = SYNTH_AGENT_NAME,
    feed_recent_frames: bool = True,
) -> dict:
    """Synthesize one note from one raw capture.

    Args:
        llm_client: a BaseLLMClient (OpenAI-compatible client; Z.AI GLM-5.2 on the production path).
        vault_root: vault checkout root; notes are written under <root>/<notes_dirname>.
        raw_text:   the raw captured Markdown.
        raw_path:   the source path (for the result/log; never modified).
        model:      synthesis model id (settings.synthesis_model).
        notes_dirname: vault subdir for notes (default "notes").
        new_only:   if True, skip when the target note already exists.
        min_body_chars: captures whose body (after front matter) has fewer than
                    this many non-whitespace chars are skipped without an LLM call.
        prompt_template/prompt_version/agent_name: select the synthesis "engine".
                    Defaults are the article prompt; the source-notes path
                    (ingest_source_notes) overrides them with the notes prompt.
        feed_recent_frames: when True, pass recent wildcard frames to steer variety.
                    The notes prompt has no wildcard section, so that path sets
                    this False to avoid feeding an irrelevant block.

    Returns:
        A JSON-serializable result dict: slug, note_path, raw_path, status,
        cached, and token counts when a live call was made.
    """
    vault_root = Path(vault_root)
    slug = slug_for_raw(raw_text)
    note_path = vault_root / notes_dirname / f"{slug}.md"

    # Skip body-less stub captures (paywall clips with only front matter) before
    # the model ever sees them — otherwise they yield junk/hallucinated notes.
    body_len = len(body_from_raw(raw_text).strip())
    if body_len < min_body_chars:
        logger.info(
            "run_note_ingest: skip (empty body: %d < %d chars) — %s",
            body_len, min_body_chars, raw_path,
        )
        return {
            "slug": slug,
            "note_path": None,
            "raw_path": raw_path,
            "status": "skipped_empty",
            "cached": False,
        }

    existing = list_note_slugs(vault_root, notes_dirname)

    if new_only and note_path.exists():
        logger.info("run_note_ingest: skip (new_only) — note exists: %s", note_path)
        return {
            "slug": slug,
            "note_path": str(note_path),
            "raw_path": raw_path,
            "status": "skipped",
            "cached": True,
        }

    # Linkable slugs exclude this note's own slug so it can't self-link.
    linkable = [s for s in existing if s != slug]

    # Recent wildcard frames → steer this stateless call away from repeating them.
    recent_frames = (
        recent_wildcard_frames(vault_root, notes_dirname, limit=RECENT_FRAMES_WINDOW)
        if feed_recent_frames
        else []
    )

    call_result = synthesize_note(
        llm_client,
        raw_text=raw_text,
        existing_titles=linkable,
        source_id=slug,
        model=model,
        recent_frames=recent_frames,
        prompt_template=prompt_template,
        prompt_version=prompt_version,
        agent_name=agent_name,
    )

    note_md = call_result.get("result")
    if not isinstance(note_md, str) or not note_md.strip():
        raise RuntimeError(
            f"run_note_ingest: synthesis returned no note text for {raw_path!r} "
            f"(cached={call_result.get('cached')})."
        )

    written = write_note(vault_root, slug, note_md, notes_dirname)

    result = {
        "slug": slug,
        "note_path": str(written),
        "raw_path": raw_path,
        "status": "ok",
        "cached": bool(call_result.get("cached")),
    }
    if "tokens_in" in call_result:
        result["tokens_in"] = call_result["tokens_in"]
        result["tokens_out"] = call_result["tokens_out"]
        result["cost_usd"] = call_result.get("cost_usd", 0.0)
    logger.info("run_note_ingest: wrote %s (cached=%s)", written, result["cached"])
    return result
