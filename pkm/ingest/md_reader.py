"""Read personal source-notes from a Markdown folder and classify what changed.

The source-notes path (books / podcasts / lectures) reads one ``.md`` per source
from a capture folder synced via iCloud — typically an Obsidian vault opened on
the phone and the Mac. Each file is fragmentary personal notes, not the source's
full text. This module:

  - reads a capture file (optional YAML front matter + body),
  - derives a stable note ``title``/``slug`` and the source ``type``,
  - normalizes + hashes the body so unchanged files can be skipped without a call,
  - persists per-source state (SHA + paragraph count) in a JSON sidecar.

Delta policy (v1): UNCHANGED (same SHA) → skip; otherwise full re-synthesis. The
incremental paragraph-append optimization from the original design is deferred —
re-synthesizing the whole note keeps it coherent and stays "one call per source".
See DECISIONS.md (2026-06-30 source-notes entry).

iCloud safety: callers skip files that fail to read or were modified in the last
``min_age_seconds`` (a partial sync mid-write), so we never hash a half-written file.

Security: ``slug`` flows through ``slugify`` ([a-z0-9-] only), so a hostile title
or filename cannot escape the notes directory — same guarantee as the article path.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pkm.ingest.hashing import sha256_content, slugify

# Leading YAML front-matter block: --- ... --- at the very top of the file.
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Pull `captured:` verbatim from the raw block — PyYAML would coerce an ISO
# timestamp to a datetime and lose the exact string the prompt must copy.
_CAPTURED_RE = re.compile(r"^captured:\s*(.+?)\s*$", re.MULTILINE)

# Source types the notes prompt understands. Anything else falls back to "book".
_KNOWN_TYPES = {"book", "podcast", "lecture", "talk", "course"}
_DEFAULT_TYPE = "book"

# State sidecar lives in the vault (committed), NOT in the iCloud capture folder.
STATE_FILENAME = ".notes-state.json"


@dataclass
class Capture:
    """One parsed capture file, ready to delta-check and synthesize."""

    path: Path
    title: str
    slug: str
    source_type: str
    body: str
    captured: str | None  # verbatim front-matter timestamp, if the user set one
    content_sha: str
    para_count: int

    def raw_for_synthesis(self) -> str:
        """Reconstruct the front-matter + body the synthesis prompt expects.

        The notes prompt reads ``title``/``type``/``captured`` from the input front
        matter (and copies ``captured`` verbatim into the output). The body is the
        user's notes unchanged — including any ``![[image]]`` refs, which v1 passes
        through untouched (OCR is deferred).
        """
        lines = ["---", _emit("title", self.title), f"type: {self.source_type}"]
        if self.captured:
            # Bare line: keep the timestamp verbatim (a YAML emitter would quote it).
            lines.append(f"captured: {self.captured}")
        lines.append("---")
        return "\n".join(lines) + "\n" + self.body


def _emit(key: str, value: str) -> str:
    """Emit ``key: value`` as one valid-YAML line (quoting only when needed)."""
    return yaml.safe_dump(
        {key: value}, default_flow_style=False, allow_unicode=True,
        sort_keys=False, width=10**9,
    ).strip()


def _humanize_filename(stem: str) -> str:
    """Turn a filename stem into a readable title fallback (no front-matter title)."""
    return re.sub(r"[-_]+", " ", stem).strip() or "untitled"


def _count_paragraphs(body: str) -> int:
    """Count non-empty paragraph blocks (blank-line separated) in the body."""
    return sum(1 for block in re.split(r"\n\s*\n", body) if block.strip())


def parse_capture(path: Path) -> Capture:
    """Parse a capture ``.md`` file into a Capture (does not touch state).

    Title precedence: front-matter ``title:`` → humanized filename. Type precedence:
    front-matter ``type:`` (if a known type) → "book". The content SHA is over the
    *body only* (normalized to ``\\n`` newlines, trailing whitespace stripped), so
    editing the body re-triggers synthesis but front-matter-only edits do not.
    """
    text = path.read_text(encoding="utf-8")
    fm_match = _FRONT_MATTER_RE.match(text)
    fm: dict = {}
    fm_block = ""
    if fm_match:
        fm_block = fm_match.group(1)
        try:
            loaded = yaml.safe_load(fm_block)
            if isinstance(loaded, dict):
                fm = loaded
        except yaml.YAMLError:
            fm = {}  # unreadable front matter → treat whole file as body
        body = text[fm_match.end():]
    else:
        body = text

    title = str(fm.get("title") or _humanize_filename(path.stem)).strip()
    raw_type = str(fm.get("type") or "").strip().lower()
    source_type = raw_type if raw_type in _KNOWN_TYPES else _DEFAULT_TYPE
    # Read `captured` from the raw block (verbatim), not the parsed scalar.
    cap_match = _CAPTURED_RE.search(fm_block)
    captured = cap_match.group(1).strip().strip("\"'") if cap_match else None

    normalized = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    return Capture(
        path=path,
        title=title,
        slug=slugify(title) or "untitled",
        source_type=source_type,
        body=body,
        captured=captured,
        content_sha=sha256_content(normalized),
        para_count=_count_paragraphs(normalized),
    )


def classify(state: dict, capture: Capture) -> str:
    """Return "new", "unchanged", or "changed" for a capture vs. prior state.

    Keyed by slug (v1). A renamed file gets a new slug → classified "new" and the
    old note is orphaned; the rename-proof ``pkm_id`` anchor is a future upgrade
    (see DECISIONS.md). State stores the last-synthesized content SHA per slug.
    """
    prior = state.get(capture.slug)
    if prior is None:
        return "new"
    return "unchanged" if prior.get("content_sha") == capture.content_sha else "changed"


def load_state(state_path: Path) -> dict:
    """Load the source-notes state sidecar; empty dict if absent or unreadable."""
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state_path: Path, state: dict) -> None:
    """Write the state sidecar (pretty, stable key order) for a clean git diff."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def record(state: dict, capture: Capture) -> None:
    """Update ``state`` in place after a successful synthesis of ``capture``."""
    entry = state.get(capture.slug, {})
    state[capture.slug] = {
        "content_sha": capture.content_sha,
        "para_count": capture.para_count,
        "source_path": capture.path.name,
        "source_type": capture.source_type,
        "first_seen": entry.get("first_seen", capture.captured),
    }
