"""
Batch ingest — process every new raw/*.md file in a vault checkout.

ORCH-07 idempotency: re-running over an unchanged vault produces zero new wiki
writes because run_ingest's per-file hash cache (new_only=True) short-circuits
each file that has already been fully processed. The batch itself only
aggregates per-file results; it does not duplicate or bypass the cache.

raw_path is stored vault-relative (file.relative_to(vault_root).as_posix())
so that DB rows are portable across different checkout locations.

Per-run cost guardrail (DECISIONS.md [T1-02] condition 2): when run_cost_cap_usd
and/or run_token_cap are provided, batch_ingest aborts the loop once the running
spend (agent_runs.cost_usd) or token total (agent_runs.tokens_in+tokens_out)
recorded since batch_start_iso exceeds the cap. Aborts are reported via the
`aborted`/`abort_reason` keys; remaining files are skipped. This is the one
deliberate exception to the per-file continue-on-error policy.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

from pkm.pipeline.ingest import run_ingest

logger = logging.getLogger(__name__)


def _running_totals(conn: Any, batch_start_iso: str) -> tuple[float, int]:
    """Sum cost_usd and tokens (in+out) across agent_runs rows written since batch_start_iso."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0), COALESCE(SUM(tokens_in + tokens_out), 0) "
        "FROM agent_runs WHERE started_at >= ?",
        (batch_start_iso,),
    ).fetchone()
    cost_total = float(row[0]) if row[0] is not None else 0.0
    token_total = int(row[1]) if row[1] is not None else 0
    return cost_total, token_total


def batch_ingest(
    conn: Any,
    llm_client: Any,
    vault_root: Path,
    new_only: bool = True,
    run_cost_cap_usd: float | None = None,
    run_token_cap: int | None = None,
    cf_account_id: str = "",
    cf_api_token: str = "",
) -> dict:
    """Scan raw/**/*.md in vault_root and call run_ingest for each file.

    Args:
        conn:             libsql connection (auto-migrated, from registry.connect).
        llm_client:       LLMClient instance with .call() method.
        vault_root:       pathlib.Path to the vault root directory.
        new_only:         If True, pass new_only=True to run_ingest for idempotent re-runs.
        run_cost_cap_usd: If set, abort the batch once cumulative agent_runs.cost_usd
                          for this run reaches this value (abort_reason="cost_cap").
        run_token_cap:    If set, abort once cumulative tokens_in+tokens_out for this
                          run reaches this value (abort_reason="token_cap").
        cf_account_id:    Cloudflare account ID for Phase 6 embedding (empty = skip).
        cf_api_token:     CF API token for Phase 6 embedding (empty = skip).

    Returns:
        dict with keys:
            processed       (int) — total files attempted
            wrote           (int) — files that produced new content (deduped=False)
            deduped         (int) — files already processed (deduped=True)
            failed          (int) — files that raised an exception
            failures        (list[dict]) — per-file error details: {raw_path, error}
            aborted         (bool) — whether the batch hit a cost/token cap
            abort_reason    (str|None) — "cost_cap" | "token_cap" | None
            cost_usd_total  (float) — cumulative agent_runs.cost_usd for this run
            tokens_total    (int) — cumulative agent_runs tokens for this run
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
            "aborted": False,
            "abort_reason": None,
            "cost_usd_total": 0.0,
            "tokens_total": 0,
        }

    # Deterministic order so test assertions are stable
    raw_files = sorted(raw_dir.rglob("*.md"))

    processed = 0
    wrote = 0
    deduped = 0
    failed = 0
    failures: list[dict] = []
    aborted = False
    abort_reason: str | None = None

    # Window start for the per-run cap query. Matches the started_at format written
    # by LLMClient (ISO 8601 with trailing Z) so string comparison is consistent.
    batch_start_iso = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

    for file in raw_files:
        rel_path = file.relative_to(vault_root).as_posix()

        # Per-run cap check (before processing the next file).
        cost_usd_total, tokens_total = _running_totals(conn, batch_start_iso)
        if run_cost_cap_usd is not None and cost_usd_total >= run_cost_cap_usd:
            aborted = True
            abort_reason = "cost_cap"
            break
        if run_token_cap is not None and tokens_total >= run_token_cap:
            aborted = True
            abort_reason = "token_cap"
            break

        try:
            raw_text = file.read_text(encoding="utf-8")
            result = run_ingest(
                conn=conn,
                llm_client=llm_client,
                vault_root=vault_root,
                raw_text=raw_text,
                raw_path=rel_path,
                new_only=new_only,
                cf_account_id=cf_account_id,
                cf_api_token=cf_api_token,
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

    # Final totals for the returned summary (0 if we never entered the loop).
    cost_usd_total, tokens_total = _running_totals(conn, batch_start_iso)

    return {
        "processed": processed,
        "wrote": wrote,
        "deduped": deduped,
        "failed": failed,
        "failures": failures,
        "aborted": aborted,
        "abort_reason": abort_reason,
        "cost_usd_total": cost_usd_total,
        "tokens_total": tokens_total,
    }