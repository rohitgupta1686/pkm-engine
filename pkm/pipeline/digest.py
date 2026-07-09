"""Weekly digest — cross-note synthesis over recent clips.

Where the per-source engine (``pkm/pipeline/synthesize.py``) summarizes one
article in isolation, this reads the notes saved in a window (default 7 days)
and asks GPT-5.4 for ONE briefing: the week's throughline, the themes, the
connections between pieces, and what's worth a real read. It's the many-to-one
counterpart of synthesize.py — same ``BaseLLMClient.call`` seam, system prompt
+ user context framing (no ``_TASK_BRIDGE`` — that was a Claude-OAuth-proxy
workaround specific to the sibling local engine; OpenAI takes the digest
prompt as a normal system message).

The digest is written as a normal note (``type: digest``) into <vault>/notes/,
so it shows up on the Home dashboard like everything else (and is marked
reviewed so it doesn't land in the review queue). Prior digests are excluded
from the input so it never folds itself back in.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from pkm.ingest.hashing import slugify
from pkm.store.notes import notes_dir, write_note

# Cache-key identity for this call (agent_runs is unused DB-free, but the name
# still identifies the call path for anyone reading a result dict).
DIGEST_AGENT_NAME = "digest_synthesizer"
DIGEST_PROMPT_TEMPLATE = "digest.v1.md"
DIGEST_PROMPT_VERSION = "v1"

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PROMPT_PATH = _PROMPTS_DIR / DIGEST_PROMPT_TEMPLATE

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Thesis = the first quoted line of the `> [!abstract] Thesis` callout.
_THESIS = re.compile(r"^>\s*\[!abstract\][^\n]*\n>\s*(.+?)\s*$", re.M)

# Strip a stray ``` / ```markdown fence if the model wraps the whole note in
# one. The remote synthesis path (synthesize.py) does not need this — its
# prompt already forbids fences and no drift has been observed there — but
# OpenAI has been seen to wrap the digest body in one, so the digest owns its
# own copy of the helper rather than reaching into synthesize.py for it.
_FENCE_OPEN_RE = re.compile(r"^\s*```[a-zA-Z]*\n")
_FENCE_CLOSE_RE = re.compile(r"\n```\s*$")


def _strip_code_fence(text: str) -> str:
    """Remove an enclosing markdown code fence, if present. No-op otherwise."""
    if _FENCE_OPEN_RE.match(text):
        text = _FENCE_OPEN_RE.sub("", text, count=1)
        text = _FENCE_CLOSE_RE.sub("", text, count=1)
    return text


def load_digest_prompt() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Digest prompt not found: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _field(block: str, key: str) -> str:
    m = re.search(rf'^{key}:\s*(.*?)\s*$', block, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def _parse_saved(value: str) -> datetime.datetime | None:
    """Parse a `saved` value (date-only or full ISO) to a naive-UTC datetime."""
    v = value.strip().strip('"').strip("'")
    if not v:
        return None
    try:
        dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.datetime.strptime(v[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.UTC).replace(tzinfo=None)
    return dt


def collect_recent_notes(
    vault_root: Path,
    since: datetime.datetime,
    notes_dirname: str = "notes",
    exclude_types: tuple[str, ...] = ("digest",),
) -> list[dict]:
    """Notes whose `saved` is on/after ``since``, newest first, with metadata."""
    d = notes_dir(vault_root, notes_dirname)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for p in d.glob("*.md"):
        text = p.read_text(encoding="utf-8")
        m = _FM.match(text)
        if not m:
            continue
        block = m.group(1)
        if _field(block, "type").lower() in exclude_types:
            continue
        saved = _parse_saved(_field(block, "saved"))
        if saved is None or saved < since:
            continue
        thesis_m = _THESIS.search(text)
        out.append({
            "slug": p.stem,
            "title": _field(block, "title") or p.stem,
            "source": _field(block, "source"),
            "tags": _field(block, "tags"),
            "saved": saved,
            "thesis": thesis_m.group(1).strip() if thesis_m else "",
        })
    out.sort(key=lambda n: n["saved"], reverse=True)
    return out


def _notes_block(notes: list[dict]) -> str:
    lines = []
    for n in notes:
        lines.append(
            f"- slug: {n['slug']}\n"
            f"  title: {n['title']}\n"
            f"  source: {n['source']}\n"
            f"  tags: {n['tags']}\n"
            f"  thesis: {n['thesis']}"
        )
    return "\n".join(lines)


def build_digest(llm_client, notes: list[dict], period_label: str, model: str) -> dict:
    """One LLM call → ``{"text", "tokens_in", "tokens_out", "cost_usd"}``.

    Delivers the digest prompt as the system message and the period + notes
    block as the user message — the same split synthesize.py uses for article
    notes (no ``_TASK_BRIDGE``; that fold-into-one-user-turn workaround is only
    needed on the sibling local-Claude engine's OAuth transport).
    """
    context = (
        f"PERIOD: {period_label}\n"
        f"NOTES SAVED THIS PERIOD ({len(notes)}), newest first:\n\n"
        f"{_notes_block(notes)}\n"
    )
    messages = [
        {"role": "system", "content": load_digest_prompt()},
        {"role": "user", "content": context},
    ]
    res = llm_client.call(
        agent_name=DIGEST_AGENT_NAME,
        model=model,
        prompt_version=DIGEST_PROMPT_VERSION,
        messages=messages,
        input_text=context,
        output_schema=None,  # freeform Markdown, not a validated schema
    )
    return {
        "text": _strip_code_fence(res["result"]),  # OpenAI may still wrap in a ``` fence
        "tokens_in": res.get("tokens_in", 0),
        "tokens_out": res.get("tokens_out", 0),
        "cost_usd": res.get("cost_usd", 0.0),
    }


def _period_label(since: datetime.datetime, now: datetime.datetime) -> str:
    if since.year == now.year:
        return f"{since:%b %-d} – {now:%b %-d, %Y}"
    return f"{since:%b %-d, %Y} – {now:%b %-d, %Y}"


def run_digest(
    llm_client,
    vault_root: Path,
    model: str,
    days: int = 7,
    notes_dirname: str = "notes",
) -> dict:
    """Build and write a weekly digest note. Returns a result dict."""
    vault_root = Path(vault_root)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    since = now - datetime.timedelta(days=days)
    notes = collect_recent_notes(vault_root, since, notes_dirname)

    if not notes:
        return {"status": "empty", "days": days, "note_count": 0, "note_path": None}

    period = _period_label(since, now)
    gen = build_digest(llm_client, notes, period, model)
    body = gen["text"]
    if not body.strip():
        raise RuntimeError("run_digest: digest synthesis returned no text.")

    now_iso = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    slug = slugify(f"weekly-digest-{now:%Y-%m-%d}")
    markdown = (
        "---\n"
        f'title: "Weekly digest — {period}"\n'
        'source: "Weekly digest"\n'
        f"saved: {now_iso}\n"
        "type: digest\n"
        "tags: [digest, weekly]\n"
        'reading_time: "~2 min"\n'
        "reviewed: true\n"
        "---\n\n"
        f"{body.strip()}\n"
    )
    written = write_note(vault_root, slug, markdown, notes_dirname)
    return {
        "status": "ok",
        "days": days,
        "period": period,
        "note_count": len(notes),
        "note_path": str(written),
        "tokens_in": gen["tokens_in"],
        "tokens_out": gen["tokens_out"],
        "cost_usd": gen["cost_usd"],
    }
