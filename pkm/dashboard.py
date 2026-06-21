"""
Dashboard regenerator (GUARD-02) backed by counter rows (GUARD-03).

Renders vault/dashboard.md from incrementally-maintained counter rows in
dashboard_counters (sources/claims/concepts/insights_accepted) plus orphan &
stale-claim counts from pkm.lint.lint_vault. No full-table COUNT(*) scans of
sources/claims/concepts — cloud doc §9 line 231.

Pure functions: conn + vault_root + optional actions_minutes/now are arguments.
No Settings, no network, no datetime.now() when now is supplied.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import datetime, timezone

from pkm.lint import lint_vault
from pkm.store.registry import read_all_counters

logger = logging.getLogger(__name__)


def _now_iso(now: datetime | None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _count_wiki_pages(vault_root: pathlib.Path) -> int:
    """Count wiki page files (sources + concepts) on the filesystem.

    Used for the wiki-pages count. The no-scan rule (GUARD-03) is about DB
    tables; a filesystem glob over O(hundreds) of small files is bounded and
    does not touch Turso. A wiki_pages_total counter is preferred when present
    (see generate_dashboard) — this is the fallback.
    """
    vault_root = pathlib.Path(vault_root)
    n = 0
    for sub in ("sources", "concepts"):
        d = vault_root / "wiki" / sub
        if d.is_dir():
            n += sum(1 for _ in d.glob("*.md"))
    return n


def generate_dashboard(
    conn,
    vault_root: pathlib.Path,
    actions_minutes: int | None = None,
    now: datetime | None = None,
) -> str:
    """Render the dashboard markdown string from counter rows + lint counts.

    Args:
        conn:            libsql connection (reads dashboard_counters + claims).
        vault_root:      pathlib.Path to the vault root.
        actions_minutes: Optional Actions-minutes-used value for the month (N/A if None).
        now:             Optional datetime for a deterministic generated-at timestamp.

    Returns:
        The full dashboard.md contents as a string.
    """
    counters = read_all_counters(conn)
    sources_total = counters.get("sources_total", 0)
    claims_total = counters.get("claims_total", 0)
    concepts_total = counters.get("concepts_total", 0)
    insights_accepted = counters.get("insights_accepted", 0)
    # Prefer a maintained wiki_pages_total counter; fall back to a filesystem count.
    wiki_pages = counters.get("wiki_pages_total")
    if wiki_pages is None:
        wiki_pages = _count_wiki_pages(vault_root)

    # Orphan / stale-provenance counts come from lint (no log.md write here —
    # the nightly workflow runs lint separately for the log write).
    report = lint_vault(conn, vault_root, write_log=False)
    orphan_count = len(report.orphans)
    stale_count = len(report.missing_provenance)

    actions_display = "N/A" if actions_minutes is None else str(actions_minutes)

    lines: list[str] = []
    lines.append("# PKM Dashboard")
    lines.append("")
    lines.append(f"_Generated: {_now_iso(now)}_")
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    lines.append(str(sources_total))
    lines.append("")
    lines.append("## Claims")
    lines.append("")
    lines.append(str(claims_total))
    lines.append("")
    lines.append("## Concepts")
    lines.append("")
    lines.append(str(concepts_total))
    lines.append("")
    lines.append("## Insights accepted")
    lines.append("")
    lines.append(str(insights_accepted))
    lines.append("")
    lines.append("## Actions minutes")
    lines.append("")
    lines.append(actions_display)
    lines.append("")
    lines.append("## Orphans / stale")
    lines.append("")
    lines.append(f"orphans: {orphan_count}; missing provenance: {stale_count}")
    lines.append("")
    return "\n".join(lines)


def write_dashboard(
    conn,
    vault_root: pathlib.Path,
    actions_minutes: int | None = None,
    now: datetime | None = None,
) -> str:
    """Render the dashboard and write it to vault_root/dashboard.md.

    Returns the vault-relative path string "dashboard.md".
    """
    vault_root = pathlib.Path(vault_root)
    md = generate_dashboard(conn, vault_root, actions_minutes=actions_minutes, now=now)
    out = vault_root / "dashboard.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return "dashboard.md"