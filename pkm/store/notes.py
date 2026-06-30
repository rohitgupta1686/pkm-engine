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

import yaml

from pkm.ingest.hashing import slugify

# Match a leading YAML front-matter block: --- ... --- at the very top of the file.
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TITLE_RE = re.compile(r'^title:\s*"?(.*?)"?\s*$', re.MULTILINE)

# Free-text frontmatter fields the model fills with arbitrary article strings.
# These are the only fields that can carry a stray ``: `` (which YAML reads as a
# mapping separator), an unbalanced quote, etc. — so they're the only ones we
# re-serialize. Structured fields (saved/tags/url/type/reading_time) are left
# byte-for-byte so we don't disturb Dataview's date and list semantics.
_FREE_TEXT_FIELDS = ("title", "source")
_FIELD_LINE_RE = re.compile(
    rf"^({'|'.join(_FREE_TEXT_FIELDS)}):\s*(.*?)\s*$"
)

_MERMAID_BLOCK_RE = re.compile(r"(```mermaid[^\n]*\n)(.*?)(```)", re.DOTALL)

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


def _unquote(raw: str) -> str:
    """Best-effort recover the plain string a frontmatter value already encodes.

    If ``raw`` is a valid quoted YAML scalar (e.g. ``'A: title'`` or ``"x"``),
    return the string it denotes — this makes the sanitizer idempotent, so a value
    we quoted on a previous write isn't re-wrapped. If ``raw`` doesn't parse as
    YAML (the broken case: a bare value containing ``: ``) or parses to a
    non-string, treat it as the literal text and let it be re-serialized.
    """
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw
    return loaded if isinstance(loaded, str) else raw


def _emit_field(key: str, value: str) -> str:
    """Emit ``key: value`` as one line of valid YAML, quoting only when needed.

    Delegates escaping to PyYAML rather than hand-rolling quote logic: a colon,
    pipe, embedded quote or apostrophe is handled correctly and identically to how
    any YAML reader would. ``width`` is set huge so long titles never line-fold.
    """
    return yaml.safe_dump(
        {key: value},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=10**9,
    ).strip()


def sanitize_frontmatter(markdown: str) -> str:
    """Re-serialize the free-text frontmatter fields so the block is valid YAML.

    The model writes the note's frontmatter itself, emitting ``title``/``source``
    verbatim — so a title like ``Foo: Bar`` produces ``title: Foo: Bar``, which
    YAML rejects (``mapping values are not allowed here``). Obsidian then can't
    read the note's metadata and it vanishes from every Dataview dashboard.

    This rewrites only the ``title`` and ``source`` lines (via a real YAML
    emitter), leaving every other line and the body untouched. Idempotent: running
    it on already-sanitized text yields identical bytes. No-op when there's no
    leading front-matter block.
    """
    fm = _FRONT_MATTER_RE.match(markdown)
    if not fm:
        return markdown
    lines = []
    for line in fm.group(1).split("\n"):
        m = _FIELD_LINE_RE.match(line)
        lines.append(_emit_field(m.group(1), _unquote(m.group(2))) if m else line)
    # Guarantee reviewed field is present; model sometimes omits it.
    if not any(re.match(r"^reviewed:", ln) for ln in lines):
        lines.append("reviewed: false")
    return markdown[: fm.start(1)] + "\n".join(lines) + markdown[fm.end(1) :]


def sanitize_mermaid(markdown: str) -> str:
    """Replace literal ``\\n`` with ``<br>`` inside Mermaid node labels.

    The model occasionally emits ``A[foo\\nbar]``; Obsidian's Mermaid renders the
    literal characters ``\\n`` rather than a line break, garbling the diagram. The
    prompt forbids it but the model ignores it, so this is the write-time guarantee.
    Scope is limited to ```mermaid blocks so legitimate ``\\n`` in prose is untouched.
    Idempotent; no-op when there is no mermaid block.
    """
    def _fix(m):
        return m.group(1) + m.group(2).replace("\\n", "<br>") + m.group(3)
    return _MERMAID_BLOCK_RE.sub(_fix, markdown)


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
    # Guarantee parseable frontmatter regardless of what the model emitted, then
    # fix literal \n in mermaid node labels, then normalize to a single trailing
    # newline for byte-stable re-writes.
    markdown = sanitize_frontmatter(markdown)
    markdown = sanitize_mermaid(markdown)
    path.write_text(markdown.rstrip("\n") + "\n", encoding="utf-8")
    return path
