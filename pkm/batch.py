"""
Batch ingest — process every new raw/*.md file in a vault checkout.

ORCH-07 idempotency: re-running over an unchanged vault produces zero new wiki
writes because run_ingest's per-file hash cache (new_only=True) short-circuits
each file that has already been fully processed. The batch itself only
aggregates per-file results; it does not duplicate or bypass the cache.

raw_path is stored vault-relative (file.relative_to(vault_root).as_posix())
so that DB rows are portable across different checkout locations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pkm.pipeline.ingest import run_ingest

logger = logging.getLogger(__name__)


def batch_ingest(
    conn: Any,
    llm_client: Any,
    vault_root: Path,
    new_only: bool = True,
) -> dict:
    """Scan raw/**/*.md in vault_root and call run_ingest for each file.

    Args:
        conn:        libsql connection (auto-migrated, from registry.connect).
        llm_client:  LLMClient instance with .call() method.
        vault_root:  pathlib.Path to the vault root directory.
        new_only:    If True, pass new_only=True to run_ingest for idempotent re-runs.

    Returns:
        dict with keys:
            processed (int) — total files attempted
            wrote      (int) — files that produced new content (deduped=False)
            deduped    (int) — files already processed (deduped=True)
            failed     (int) — files that raised an exception
            failures   (list[dict]) — per-file error details: {raw_path, error}
    """

    raw_dir = vault_root / "raw"

    # If raw/ doesn't exist, return a zero summary (nightly cron may run on empty vault)
    if not raw_dir.exists():
        return {
            "processed": 0,
            "wrote": 0,
            "deduped": 0,
            "failed": 0,
            "failures": [],
        }

    # Deterministic order so test assertions are stable
    raw_files = sorted(raw_dir.rglob("*.md"))

    processed = 0
    wrote = 0
    deduped = 0
    failed = 0
    failures: list[dict] = []

    for file in raw_files:
        rel_path = file.relative_to(vault_root).as_posix()
        try:
            raw_text = file.read_text(encoding="utf-8")
            result = run_ingest(
                conn=conn,
                llm_client=llm_client,
                vault_root=vault_root,
                raw_text=raw_text,
                raw_path=rel_path,
                new_only=new_only,
            )
            processed += 1
            if result.get("deduped"):
                deduped += 1
            else:
                wrote += 1
        except Exception as exc:
            processed += 1
            failed += 1
            failures.append({"raw_path": rel_path, "error": str(exc)})
            logger.warning("batch_ingest: failed on %s: %s", rel_path, exc)

    return {
        "processed": processed,
        "wrote": wrote,
        "deduped": deduped,
        "failed": failed,
        "failures": failures,
    }