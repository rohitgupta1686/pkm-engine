"""Markdown-native vault lint — the DB-free successor to the retired SQL lint.

Scans the vault's Markdown directly (no database): every ``[[wikilink]]`` in
``notes/`` and ``advice/`` must resolve to an existing page anywhere in the
vault (``notes/``, ``advice/**``, ``wiki/``, or a root-level page like
``Home.md``). Also reports the review-queue backlog (``reviewed: false``).

Unresolved links are a *warning*, not an error, by default: in Obsidian an
unresolved link is a legal "note you might want to write" — but a spike in
them usually means a slug-generation regression (e.g. the Gmail-suffix
pollution fixed in 2026-08), which is exactly what this lint exists to catch.

Deliberately not detected: orphan notes. The vault's dashboards (Home.md) are
Dataview queries over frontmatter, so unreferenced notes are still reachable
and orphanhood carries no signal here.

Limitation: wikilinks inside fenced code blocks are counted like any other —
acceptable noise at current scale.
"""
from __future__ import annotations

import re
from pathlib import Path

# [[target]], [[target|alias]], [[target#heading]] — capture up to |, # or ]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|#\n]+)")
_REVIEWED_FALSE_RE = re.compile(r"^reviewed:\s*false\s*$", re.MULTILINE)


def _page_stems(vault_root: Path) -> set[str]:
    """Every linkable page stem in the vault."""
    stems: set[str] = set()
    for pattern in ("*.md", "notes/*.md", "wiki/*.md", "advice/**/*.md"):
        stems.update(p.stem for p in vault_root.glob(pattern))
    return stems


def lint_vault(vault_root: Path, notes_dirname: str = "notes") -> dict:
    """Lint the vault; returns a JSON-serializable report.

    Report shape::

        {
          "notes": <int>, "unreviewed": <int>,
          "broken_count": <int>,
          "broken_links": [{"page": <slug>, "target": <slug>}, ...],
        }
    """
    vault = Path(vault_root)
    pages = _page_stems(vault)

    scan_files: list[Path] = sorted(vault.glob(f"{notes_dirname}/*.md"))
    scan_files += sorted(vault.glob("advice/**/*.md"))

    broken: list[dict] = []
    notes_count = 0
    unreviewed = 0
    for f in scan_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        in_notes = f.parent.name == notes_dirname
        if in_notes:
            notes_count += 1
            if _REVIEWED_FALSE_RE.search(text):
                unreviewed += 1
        for m in _WIKILINK_RE.finditer(text):
            target = m.group(1).strip()
            if target and target not in pages:
                broken.append({"page": f.stem, "target": target})

    return {
        "notes": notes_count,
        "unreviewed": unreviewed,
        "broken_count": len(broken),
        "broken_links": broken,
    }
