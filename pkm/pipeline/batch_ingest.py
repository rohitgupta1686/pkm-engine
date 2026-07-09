"""Batch-API ingest orchestration (the article path).

Instead of N synchronous ``chat.completions`` calls (one per source), this submits
all synthesis requests as ONE OpenAI Batch job — billed at a 50% discount. The
Batch API is asynchronous (submit → poll → collect within a 24h window), so this
runs inside a single GitHub Actions job that blocks-polls the batch to completion,
then writes the notes. No database; the vault git repo is still the only state.

It reuses the exact same pre-synthesis decisions as the synchronous
``run_note_ingest`` (slug, skip body-less stubs, skip existing when --new-only,
linkable slugs + recent wildcard frames) and the same ``write_note`` output path
(front-matter/mermaid sanitizers included).

Behavior note vs the sync loop: requests are built from a SINGLE up-front snapshot
of the notes dir, so notes produced within one batch can't cross-link to or vary
against each other. That only matters for a multi-note backstop run; the primary
mode is per-clip (batch size ≈ 1). See DECISIONS.md (2026-07-09).
"""
from __future__ import annotations

import logging
from pathlib import Path

from pkm.llm.pricing import compute_cost
from pkm.pipeline.ingest_note import MIN_BODY_CHARS, RECENT_FRAMES_WINDOW
from pkm.pipeline.synthesize import _build_user_message, load_synthesis_prompt
from pkm.store.notes import (
    body_from_raw,
    list_note_slugs,
    recent_wildcard_frames,
    slug_for_raw,
    write_note,
)

logger = logging.getLogger(__name__)

# Rough token estimate for the pre-submit cost cap: ~4 chars/token for the prompt,
# plus a fixed allowance for the note the model will write. Only used to decide how
# many sources fit under the cap — real spend is computed from actual batch usage.
_CHARS_PER_TOKEN = 4
_EST_OUTPUT_TOKENS = 2_000


def prepare_requests(
    client,
    vault_root: Path,
    raw_files: list[Path],
    model: str,
    new_only: bool,
    cost_cap: float,
    notes_dirname: str = "notes",
    min_body_chars: int = MIN_BODY_CHARS,
) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """Build the batch request lines and the pre-decided (no-LLM) result rows.

    Returns ``(requests, meta, prelim_results)``:
      - ``requests``: JSONL lines to submit (``custom_id`` is the string index).
      - ``meta``: custom_id → {slug, raw_path} for mapping results back on collect.
      - ``prelim_results``: rows already decided without a model call
        (skipped_empty / skipped / deferred), in the summary's result shape.
    """
    vault_root = Path(vault_root)
    prompt = load_synthesis_prompt()  # article synthesis prompt; same for every request
    existing = list_note_slugs(vault_root, notes_dirname)
    recent_frames = recent_wildcard_frames(vault_root, notes_dirname, limit=RECENT_FRAMES_WINDOW)
    prompt_tokens_base = len(prompt) // _CHARS_PER_TOKEN

    requests: list[dict] = []
    meta: dict[str, dict] = {}
    prelim: list[dict] = []
    projected = 0.0
    capped = False

    for raw_file in raw_files:
        raw_text = raw_file.read_text(encoding="utf-8")
        raw_path = str(raw_file)
        slug = slug_for_raw(raw_text)
        note_path = vault_root / notes_dirname / f"{slug}.md"

        if len(body_from_raw(raw_text).strip()) < min_body_chars:
            prelim.append({
                "slug": slug, "note_path": None, "raw_path": raw_path,
                "status": "skipped_empty", "cached": False,
            })
            continue

        if new_only and note_path.exists():
            prelim.append({
                "slug": slug, "note_path": str(note_path), "raw_path": raw_path,
                "status": "skipped", "cached": True,
            })
            continue

        # Once the cap is hit, defer this and every remaining source — they're
        # picked up by the next dispatch/nightly run (idempotent via --new-only).
        if capped:
            prelim.append({
                "slug": slug, "note_path": None, "raw_path": raw_path,
                "status": "deferred", "cached": False,
            })
            continue

        linkable = [s for s in existing if s != slug]
        user_message = _build_user_message(raw_text, linkable, recent_frames)
        est_tokens = prompt_tokens_base + len(user_message) // _CHARS_PER_TOKEN
        est_cost = compute_cost(model, est_tokens, 0, _EST_OUTPUT_TOKENS, batch=True)
        if requests and projected + est_cost > cost_cap:
            capped = True
            prelim.append({
                "slug": slug, "note_path": None, "raw_path": raw_path,
                "status": "deferred", "cached": False,
            })
            continue
        projected += est_cost

        custom_id = str(len(requests))
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]
        requests.append(client.build_batch_request(custom_id, model, messages))
        meta[custom_id] = {"slug": slug, "raw_path": raw_path}

    if capped:
        logger.warning(
            "prepare_requests: cost cap $%.2f reached; %d source(s) deferred to next run.",
            cost_cap, sum(1 for r in prelim if r["status"] == "deferred"),
        )
    return requests, meta, prelim


def run_batch_ingest(
    client,
    vault_root: Path,
    model: str,
    new_only: bool = False,
    notes_dirname: str = "notes",
    cost_cap: float = 0.50,
    poll_interval: int = 20,
    timeout: int = 5400,
) -> dict:
    """Synthesize every new raw capture via one OpenAI Batch job.

    Reads ``<vault>/raw/**/*.md``, submits surviving sources as one batch, blocks
    until it completes, and writes ``<vault>/<notes_dirname>/<slug>.md`` per success.
    Returns a summary in the same shape as the old synchronous ``batch-ingest``.
    """
    vault_root = Path(vault_root)
    raw_files = sorted((vault_root / "raw").glob("**/*.md"))

    requests, meta, prelim = prepare_requests(
        client, vault_root, raw_files, model, new_only, cost_cap, notes_dirname,
    )

    results: list[dict] = list(prelim)
    failed = 0
    spent = 0.0

    if requests:
        batch_id = client.submit_batch(requests)
        batch = client.poll_batch(batch_id, poll_interval, timeout)

        if getattr(batch, "status", None) != "completed":
            # Whole batch failed/expired/timed-out — write nothing, retry next run.
            for cid, info in meta.items():
                failed += 1
                results.append({
                    "slug": info["slug"], "note_path": None, "raw_path": info["raw_path"],
                    "status": "error", "error": f"batch status={getattr(batch, 'status', None)}",
                })
        else:
            collected = client.collect_batch(batch)
            for cid, info in meta.items():
                slug, raw_path = info["slug"], info["raw_path"]
                out = collected.get(cid)
                if not out or "error" in out:
                    failed += 1
                    results.append({
                        "slug": slug, "note_path": None, "raw_path": raw_path,
                        "status": "error", "error": str((out or {}).get("error", "missing result")),
                    })
                    continue
                written = write_note(vault_root, slug, out["text"], notes_dirname)
                cost = compute_cost(
                    model, out["tokens_in"], out["cached_tokens"], out["tokens_out"], batch=True,
                )
                spent += cost
                results.append({
                    "slug": slug, "note_path": str(written), "raw_path": raw_path,
                    "status": "ok", "cached": False,
                    "tokens_in": out["tokens_in"], "tokens_out": out["tokens_out"],
                    "cost_usd": cost,
                })
                logger.info("run_batch_ingest: wrote %s", written)

    return {
        "total": len(raw_files),
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "skipped_empty": sum(1 for r in results if r.get("status") == "skipped_empty"),
        "deferred": sum(1 for r in results if r.get("status") == "deferred"),
        "failed": failed,
        "cost_usd": round(spent, 5),
        "cost_capped": any(r.get("status") == "deferred" for r in results),
        "results": results,
    }
