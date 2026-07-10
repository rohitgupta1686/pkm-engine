"""Source-notes ingest — books / podcasts / lectures from an iCloud Markdown folder.

Sibling of the article path. Where ``batch-ingest`` scans an immutable ``raw/``
folder of clipped articles, this scans a *live* capture folder (one ``.md`` per
source, synced via iCloud / Obsidian) where the user keeps editing as they read or
listen. A JSON state sidecar in the vault lets unchanged files skip the model.

Flow per file:
  read → skip if too fresh / unreadable (iCloud mid-sync) → classify vs state →
  skip if unchanged → one LLM call with the notes prompt → write note → update state.

Delta policy is full re-synthesis on any body change (v1) — see md_reader and
DECISIONS.md. Cost is bounded the same way as batch-ingest: the run aborts before
in-memory spend exceeds the cap.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from pkm.ingest.md_reader import (
    STATE_FILENAME,
    classify,
    load_state,
    parse_capture,
    record,
    save_state,
)
from pkm.pipeline.ingest_note import run_note_ingest
from pkm.pipeline.synthesize import (
    NOTES_AGENT_NAME,
    NOTES_PROMPT_TEMPLATE,
    NOTES_PROMPT_VERSION,
)

logger = logging.getLogger(__name__)

# A capture modified within this window may be mid-sync from another device; skip
# it this run and pick it up once it settles (Opus risk: iCloud partial syncs).
MIN_AGE_SECONDS = 60

# Source notes legitimately start tiny (a single highlight on day one), so the
# article path's 200-char empty-body guard would wrongly skip a new book. Allow
# anything with real content through.
NOTES_MIN_BODY_CHARS = 1


def run_source_notes_ingest(
    llm_client,
    sources_dir: Path,
    vault_root: Path,
    model: str,
    notes_dirname: str = "notes",
    cost_cap_usd: float = 0.50,
    min_age_seconds: int = MIN_AGE_SECONDS,
    now: float | None = None,
) -> dict:
    """Synthesize/refresh notes for every changed source in ``sources_dir``.

    Args:
        llm_client: a BaseLLMClient (OpenAI-compatible client; Z.AI GLM-5.2 on the production path).
        sources_dir: the iCloud capture folder (top-level ``*.md`` only in v1).
        vault_root: vault checkout; notes + the state sidecar live here.
        model:      synthesis model id (settings.synthesis_model).
        notes_dirname: vault subdir for notes.
        cost_cap_usd: abort before in-memory spend would exceed this.
        min_age_seconds: skip files modified more recently than this (iCloud safety).
        now:        injectable clock (epoch seconds) for tests; defaults to time.time().

    Returns:
        A JSON-serializable summary dict (counts, spend, per-file results).
    """
    sources_dir = Path(sources_dir)
    vault_root = Path(vault_root)
    now = time.time() if now is None else now

    state_path = vault_root / notes_dirname / STATE_FILENAME
    state = load_state(state_path)

    results: list[dict] = []
    spent = 0.0
    aborted = False
    changed_any = False

    for md_path in sorted(sources_dir.glob("*.md")):
        # iCloud safety: skip a file that's still settling from another device.
        try:
            mtime = md_path.stat().st_mtime
        except OSError as exc:
            results.append({"source_path": md_path.name, "status": "error", "error": str(exc)})
            continue
        if now - mtime < min_age_seconds:
            results.append({"source_path": md_path.name, "status": "skipped_fresh"})
            continue

        try:
            capture = parse_capture(md_path)
        except (OSError, UnicodeDecodeError) as exc:
            results.append({"source_path": md_path.name, "status": "error", "error": str(exc)})
            continue

        verdict = classify(state, capture)
        if verdict == "unchanged":
            results.append(
                {"source_path": md_path.name, "slug": capture.slug, "status": "unchanged"}
            )
            continue

        if spent >= cost_cap_usd:
            aborted = True
            break

        try:
            r = run_note_ingest(
                llm_client,
                vault_root=vault_root,
                raw_text=capture.raw_for_synthesis(),
                raw_path=str(md_path),
                model=model,
                notes_dirname=notes_dirname,
                new_only=False,
                min_body_chars=NOTES_MIN_BODY_CHARS,
                prompt_template=NOTES_PROMPT_TEMPLATE,
                prompt_version=NOTES_PROMPT_VERSION,
                agent_name=NOTES_AGENT_NAME,
                feed_recent_frames=False,
            )
        except Exception as exc:  # noqa: BLE001 — isolate per-file failures
            results.append(
                {"source_path": md_path.name, "slug": capture.slug,
                 "status": "error", "error": str(exc)}
            )
            continue

        if r.get("status") == "ok":
            record(state, capture)
            changed_any = True
            spent += r.get("cost_usd", 0.0)
        r["source_path"] = md_path.name
        r["change"] = verdict
        results.append(r)

    if changed_any:
        save_state(state_path, state)

    return {
        "total": sum(1 for _ in sources_dir.glob("*.md")),
        "synthesized": sum(1 for r in results if r.get("status") == "ok"),
        "unchanged": sum(1 for r in results if r.get("status") == "unchanged"),
        "skipped_fresh": sum(1 for r in results if r.get("status") == "skipped_fresh"),
        "failed": sum(1 for r in results if r.get("status") == "error"),
        "cost_usd": round(spent, 5),
        "cost_capped": aborted,
        "results": results,
    }
