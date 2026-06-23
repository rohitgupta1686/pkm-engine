"""Note vault I/O for the single-call pipeline.

The redesign writes ONE Markdown note per source into ``<vault>/notes/<slug>.md``
and drops the legacy ``wiki/sources`` + ``wiki/concepts`` split. This module is
deliberately dependency-light (stdlib + ``slugify``) so the synthesis path can be
unit-tested without Turso, pydantic, or the OpenAI SDK.

Security: slug derives from the article title through ``slugify`` ([a-z0-9-] only),
so a hostile title cannot escape the notes directory (T-03-04).
"""
from __future__ import annotations

import re
from pathlib import Path

from pkm.ingest.hashing import slugify

# Match a leading YAML front-matter block: --- ... --- at the very top of the file.
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TITLE_RE = re.compile(r'^title:\s*"?(.*?)"?\s*$', re.MULTILINE)

# A wildcard callout header is the only callout whose title leads with one of the
# six wildcard emojis (the others — Thesis/By the numbers/Worth keeping/Open
# threads — never do). Capture the emoji+label so we can feed it back as
# "frames recently used, avoid repeating" to keep the vault's wildcards varied.
_WILDCARD_RE = re.compile(
    r"^>\s*\[!\w+\]\s*([\U0001F0CF⚡\U0001F52D\U0001F608\U0001F914\U0001F4A1].*?)\s*$",
    re.MULTILINE,
)


def title_from_raw(raw_text: str) -> str:
    """Extract the ``title:`` value from a raw capture's front matter.

    Falls back to "untitled" if there is no front matter or no title key.
    """
    fm = _FRONT_MATTER_RE.match(raw_text)
    block = fm.group(1) if fm else raw_text
    m = _TITLE_RE.search(block)
    return m.group(1).strip() if m else "untitled"


def slug_for_raw(raw_text: str) -> str:
    """Deterministic note slug for a raw capture, derived from its title."""
    return slugify(title_from_raw(raw_text)) or "untitled"


def body_from_raw(raw_text: str) -> str:
    """Return the capture's body — everything after the YAML front matter.

    If there is no leading front-matter block, the whole text is the body. Used to
    detect body-less stub captures (e.g. paywall clips that carry only front
    matter) so they can be skipped before reaching the model.
    """
    fm = _FRONT_MATTER_RE.match(raw_text)
    return raw_text[fm.end():] if fm else raw_text


def notes_dir(vault_root: Path, notes_dirname: str = "notes") -> Path:
    """Return the notes directory under the vault root."""
    return Path(vault_root) / notes_dirname


def list_note_slugs(vault_root: Path, notes_dirname: str = "notes") -> list[str]:
    """Return the slugs (filenames without .md) of existing notes, sorted.

    Returns an empty list if the notes directory does not exist yet.
    """
    d = notes_dir(vault_root, notes_dirname)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.md"))


def wildcard_frame_of(markdown: str) -> str | None:
    """Return the wildcard frame label (e.g. "🔭 Zoom out") of a note, or None.

    A note has at most one wildcard callout; non-wildcard callouts (Thesis, By the
    numbers, Worth keeping, Open threads) carry no leading wildcard emoji and are
    ignored.
    """
    m = _WILDCARD_RE.search(markdown)
    return m.group(1).strip() if m else None


def recent_wildcard_frames(
    vault_root: Path,
    notes_dirname: str = "notes",
    limit: int = 5,
) -> list[str]:
    """Frames used by the most-recently-written notes, newest first.

    "Recent" = by file mtime (ingest order). Notes without a wildcard are skipped.
    Returns at most ``limit`` frames; the synthesis call is told to avoid repeating
    them so the corpus stays varied across independent, stateless calls.
    """
    d = notes_dir(vault_root, notes_dirname)
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    frames: list[str] = []
    for p in files:
        if len(frames) >= limit:
            break
        try:
            frame = wildcard_frame_of(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        if frame:
            frames.append(frame)
    return frames


def write_note(
    vault_root: Path,
    slug: str,
    markdown: str,
    notes_dirname: str = "notes",
) -> Path:
    """Write ``markdown`` to ``<vault>/<notes_dirname>/<slug>.md`` and return the path.

    Creates the notes directory if needed. Overwrites an existing note (re-ingest
    is idempotent at the source level; the synthesis cache prevents needless calls).
    """
    safe_slug = slugify(slug) or "untitled"
    d = notes_dir(vault_root, notes_dirname)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{safe_slug}.md"
    # Normalize to a single trailing newline for byte-stable re-writes.
    path.write_text(markdown.rstrip("\n") + "\n", encoding="utf-8")
    return path
