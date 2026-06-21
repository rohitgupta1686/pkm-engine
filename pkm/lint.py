"""
Nightly vault lint (GUARD-01).

Surfaces three classes of drift so the operator can fix them, writing the
result to vault/log.md (the human-readable audit surface):

  1. broken [[wikilinks]] — a [[token]] pointing at a wiki page that does not exist
  2. orphan notes          — a wiki page not linked from any other page and not in index.md
  3. missing provenance    — a claims row whose chunk_id is NULL (lost its source span)

Pure function: ``conn`` and ``vault_root`` are arguments. No Settings, no
network, no global state. Safe to run from the CLI, the nightly workflow, or
tests.

Security (T-07-01-02): the missing-provenance query uses parameterized ?
placeholders — no f-string value interpolation of values (matches T-03-03).
"""

from __future__ import annotations

import logging
import pathlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pkm.store.vault import append_log

logger = logging.getLogger(__name__)

# [[some-slug]] / [[some-slug|Display]] — capture the inner text up to ]].
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")

# Default cap on detail lines written to log.md so a very dirty vault does not
# blow up the audit log (counts in the header are always exact).
_MAX_DETAIL_LINES = 50


@dataclass
class LintReport:
    """Result of a single lint_vault run."""

    broken_wikilinks: list[dict] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    missing_provenance: list[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True when every category is empty."""
        return not (self.broken_wikilinks or self.orphans or self.missing_provenance)


def _wikilink_tokens(text: str) -> list[str]:
    """Extract wikilink target slugs from markdown text.

    Handles the simple ``[[slug]]`` form emitted by vault.py and the
    ``[[slug|alias]]`` pipe-alias form (target is the left side).
    """
    tokens: list[str] = []
    for inner in _WIKILINK_RE.findall(text):
        target = inner.split("|", 1)[0].strip()
        if target:
            tokens.append(target)
    return tokens


def _wiki_page_files(vault_root: pathlib.Path) -> list[pathlib.Path]:
    """Return all wiki/sources/*.md and wiki/concepts/*.md files."""
    files: list[pathlib.Path] = []
    for sub in ("sources", "concepts"):
        d = vault_root / "wiki" / sub
        if d.is_dir():
            files.extend(sorted(d.glob("*.md")))
    return files


def _now_iso(now: datetime | None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def lint_vault(
    conn,
    vault_root: pathlib.Path,
    write_log: bool = True,
    now: datetime | None = None,
) -> LintReport:
    """Lint the vault and optionally append the result to vault/log.md.

    Args:
        conn:       libsql connection (used only for the missing-provenance query).
        vault_root: pathlib.Path to the vault root.
        write_log:  When True, append a summary line to vault/log.md (a "lint ok"
                    line on a clean vault, a "lint FAIL ..." block on a dirty one).
        now:        Optional datetime for deterministic log timestamps in tests.

    Returns:
        LintReport with broken_wikilinks, orphans, missing_provenance.
    """
    vault_root = pathlib.Path(vault_root)
    report = LintReport()

    pages = _wiki_page_files(vault_root)

    # Stem (slug) -> vault-relative path, and per-page extracted wikilink tokens.
    stem_to_rel: dict[str, str] = {}
    page_tokens: dict[pathlib.Path, list[str]] = {}
    existing_stems: set[str] = set()
    for page in pages:
        stem = page.stem
        existing_stems.add(stem)
        stem_to_rel[stem] = page.relative_to(vault_root).as_posix()
        try:
            text = page.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("lint_vault: could not read %s: %s", page, exc)
            page_tokens[page] = []
            continue
        page_tokens[page] = _wikilink_tokens(text)

    # --- Broken wikilinks: a token with no matching page stem. ---
    for page in pages:
        rel = page.relative_to(vault_root).as_posix()
        for token in page_tokens[page]:
            if token not in existing_stems:
                report.broken_wikilinks.append({"page": rel, "link": token})

    # --- Orphans: a page not referenced by any OTHER page and not in index.md. ---
    index_text = ""
    index_path = vault_root / "index.md"
    if index_path.is_file():
        try:
            index_text = index_path.read_text(encoding="utf-8")
        except OSError:
            index_text = ""

    for page in pages:
        stem = page.stem
        referenced_by_other = any(
            stem in toks for other, toks in page_tokens.items() if other != page
        )
        if referenced_by_other:
            continue
        if stem in index_text:
            continue
        report.orphans.append(stem_to_rel.get(stem, page.relative_to(vault_root).as_posix()))

    # --- Missing provenance: claims with chunk_id IS NULL. ---
    rows = conn.execute(
        "SELECT id, statement, source_id FROM claims WHERE chunk_id IS NULL"
    ).fetchall()
    for r in rows:
        report.missing_provenance.append(
            {"claim_id": r[0], "statement": r[1], "source_id": r[2]}
        )

    if write_log:
        _write_log(vault_root, report, now)

    return report


def _write_log(vault_root: pathlib.Path, report: LintReport, now: datetime | None) -> None:
    """Append the lint summary to vault/log.md."""
    ts = _now_iso(now)
    if report.is_clean:
        append_log(vault_root, f"{ts} lint ok\n")
        return

    header = (
        f"{ts} lint FAIL broken={len(report.broken_wikilinks)} "
        f"orphan={len(report.orphans)} missing_provenance={len(report.missing_provenance)}\n"
    )
    detail: list[str] = []
    for item in report.broken_wikilinks:
        detail.append(f"- broken: {item['page']} -> [[{item['link']}]]\n")
    for path in report.orphans:
        detail.append(f"- orphan: {path}\n")
    for item in report.missing_provenance:
        detail.append(f"- missing-provenance: {item['claim_id']}\n")

    block = header + "".join(detail[:_MAX_DETAIL_LINES])
    append_log(vault_root, block)