"""Unit tests for the single-call note synthesis path.

Dependency-light by design: a FakeLLMClient stands in for the OpenAI client, so
these run without the SDK, Turso, or pydantic. Runnable either under pytest or
directly:  python3 tests/test_synthesize.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow `python3 tests/test_synthesize.py` from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pkm.pipeline.ingest_note import run_note_ingest  # noqa: E402
from pkm.pipeline.synthesize import (  # noqa: E402
    SYNTH_AGENT_NAME,
    SYNTH_PROMPT_VERSION,
    synthesize_note,
)
from pkm.store.notes import (  # noqa: E402
    body_from_raw,
    list_note_slugs,
    recent_wildcard_frames,
    sanitize_frontmatter,
    slug_for_raw,
    title_from_raw,
    wildcard_frame_of,
    write_note,
)

RAW = (
    "---\n"
    'title: "Anthropic\'s astonishing commercial success"\n'
    "type: Article\n"
    "url: \"https://www.economist.com/x\"\n"
    "date_saved: 2026-06-21T13:24:51.899Z\n"
    "---\n"
    "Anthropic's revenue is growing fast. The body of the article goes on to "
    "describe how the company's annualized run-rate has climbed sharply over the "
    "past year, driven by enterprise demand for Claude. It covers the model "
    "lineup, the API business, and the competitive landscape against OpenAI and "
    "Google, with plenty of substance for a synthesizer to work from.\n"
)

# A body-less stub: front matter only (a paywall clip). Its body is below the
# MIN_BODY_CHARS guard, so run_note_ingest must skip it without an LLM call.
RAW_STUB = (
    "---\n"
    'title: "Paywalled piece behind a login wall"\n'
    "type: Article\n"
    "url: \"https://example.com/paywalled\"\n"
    "date_saved: 2026-06-23T09:00:00.000Z\n"
    "---\n"
)

NOTE_MD = (
    "---\n"
    "title: x\n"
    "reviewed: false\n"
    "---\n\n# x\n\n> [!abstract] Thesis\n> A note.\n"
)

# A note carrying a "Zoom out" wildcard, plus decoy callouts that must NOT be
# mistaken for a wildcard (no leading wildcard emoji).
NOTE_WITH_ZOOM = (
    "---\ntitle: z\n---\n\n# z\n\n"
    "> [!abstract] Thesis\n> t\n\n"
    "> [!info] By the numbers\n> 5\n\n"
    "> [!example] 🔭 Zoom out\n> the bigger pattern.\n\n"
    "> [!question] Open threads\n> - q?\n"
)
NOTE_WITH_DEVIL = (
    "---\ntitle: d\n---\n\n# d\n\n"
    "> [!note] 😈 Devil's advocate\n> the case against.\n"
)
NOTE_NO_WILDCARD = (
    "---\ntitle: n\n---\n\n# n\n\n"
    "> [!abstract] Thesis\n> t\n\n"
    "> [!question] Open threads\n> - q?\n"
)


class FakeLLMClient:
    """Records the last call() and returns a canned note (no schema)."""

    def __init__(self, *, cached=False, result=NOTE_MD):
        self.calls = []
        self._cached = cached
        self._result = result

    def call(self, **kwargs):
        self.calls.append(kwargs)
        out = {"cached": self._cached, "input_hash": "deadbeef", "result": self._result}
        if not self._cached:
            out["tokens_in"] = 1234
            out["tokens_out"] = 567
        return out


def test_title_and_slug_from_raw():
    assert title_from_raw(RAW) == "Anthropic's astonishing commercial success"
    assert slug_for_raw(RAW) == "anthropic-s-astonishing-commercial-success"
    assert title_from_raw("no front matter here") == "untitled"


def test_synthesize_builds_system_and_user_messages():
    client = FakeLLMClient()
    synthesize_note(
        client, raw_text=RAW, existing_titles=["jio-ipo-finshots"], model="gpt-5.4"
    )
    assert len(client.calls) == 1
    kw = client.calls[0]
    assert kw["agent_name"] == SYNTH_AGENT_NAME
    assert kw["model"] == "gpt-5.4"
    assert kw["prompt_version"] == SYNTH_PROMPT_VERSION
    assert kw["output_schema"] is None  # freeform markdown, not a schema
    msgs = kw["messages"]
    assert msgs[0]["role"] == "system"
    assert "reading companion" in msgs[0]["content"]  # the prompt loaded
    assert msgs[1]["role"] == "user"
    assert "Anthropic's revenue is growing fast" in msgs[1]["content"]  # raw body
    assert "jio-ipo-finshots" in msgs[1]["content"]  # linkable slug list


def test_synthesize_requires_model():
    client = FakeLLMClient()
    try:
        synthesize_note(client, raw_text=RAW, model="")
    except ValueError:
        return
    raise AssertionError("expected ValueError when model is missing")


def test_run_note_ingest_writes_note_and_excludes_self_link():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        # Pre-existing notes: one is THIS note's own slug → must be excluded.
        (vault / "notes").mkdir()
        (vault / "notes" / "anthropic-s-astonishing-commercial-success.md").write_text("old\n")
        (vault / "notes" / "jio-ipo-finshots.md").write_text("x\n")

        result = run_note_ingest(
            client, vault_root=vault, raw_text=RAW, raw_path="raw/a.md", model="gpt-5.4"
        )

        assert result["status"] == "ok"
        assert result["slug"] == "anthropic-s-astonishing-commercial-success"
        assert result["tokens_in"] == 1234
        written = Path(result["note_path"])
        assert written.exists()
        assert written.read_text().startswith("---")

        # The own-slug must NOT be offered as a linkable title; the other one must.
        linkable = client.calls[0]["messages"][1]["content"]
        assert "jio-ipo-finshots" in linkable
        # own slug appears as the file but not in the linkable list line items
        assert "- anthropic-s-astonishing-commercial-success" not in linkable


def test_body_from_raw_strips_front_matter():
    assert body_from_raw(RAW).strip().startswith("Anthropic's revenue is growing fast")
    # A front-matter-only stub has an empty body.
    assert body_from_raw(RAW_STUB).strip() == ""
    # No front matter → the whole text is the body.
    assert body_from_raw("just a body, no fm") == "just a body, no fm"


def test_run_note_ingest_skips_body_less_stub_without_calling_llm():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)

        result = run_note_ingest(
            client, vault_root=vault, raw_text=RAW_STUB, raw_path="raw/stub.md",
            model="gpt-5.4",
        )

        assert result["status"] == "skipped_empty"
        assert result["note_path"] is None
        assert client.calls == []  # never reached the model
        # No note file written for a stub.
        assert list_note_slugs(vault) == []


def test_min_body_chars_threshold_is_configurable():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        # With the guard relaxed to 0, even the stub synthesizes.
        result = run_note_ingest(
            client, vault_root=vault, raw_text=RAW_STUB, raw_path="raw/stub.md",
            model="gpt-5.4", min_body_chars=0,
        )
        assert result["status"] == "ok"
        assert len(client.calls) == 1


def test_new_only_skips_existing_note_without_calling_llm():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "notes").mkdir()
        (vault / "notes" / "anthropic-s-astonishing-commercial-success.md").write_text("keep\n")

        result = run_note_ingest(
            client, vault_root=vault, raw_text=RAW, raw_path="raw/a.md",
            model="gpt-5.4", new_only=True,
        )

        assert result["status"] == "skipped"
        assert client.calls == []  # no LLM call
        # existing note untouched
        assert (vault / "notes" / "anthropic-s-astonishing-commercial-success.md").read_text() == "keep\n"


def test_list_note_slugs_empty_when_no_dir():
    with tempfile.TemporaryDirectory() as tmp:
        assert list_note_slugs(Path(tmp)) == []


def test_wildcard_frame_extraction():
    assert wildcard_frame_of(NOTE_WITH_ZOOM) == "🔭 Zoom out"
    assert wildcard_frame_of(NOTE_WITH_DEVIL) == "😈 Devil's advocate"
    # Decoy callouts (Thesis / By the numbers / Open threads) are not wildcards.
    assert wildcard_frame_of(NOTE_NO_WILDCARD) is None
    assert wildcard_frame_of(NOTE_MD) is None


def test_recent_wildcard_frames_newest_first_skips_none_respects_limit():
    import os
    import time

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        nd = vault / "notes"
        nd.mkdir()
        # Write three notes; stamp mtimes so order is deterministic (oldest→newest).
        (nd / "a.md").write_text(NOTE_WITH_DEVIL)       # oldest
        (nd / "b.md").write_text(NOTE_NO_WILDCARD)      # no wildcard → skipped
        (nd / "c.md").write_text(NOTE_WITH_ZOOM)        # newest
        base = time.time()
        os.utime(nd / "a.md", (base, base))
        os.utime(nd / "b.md", (base + 10, base + 10))
        os.utime(nd / "c.md", (base + 20, base + 20))

        frames = recent_wildcard_frames(vault, limit=5)
        assert frames == ["🔭 Zoom out", "😈 Devil's advocate"]  # newest first, no None
        assert recent_wildcard_frames(vault, limit=1) == ["🔭 Zoom out"]


def test_recent_frames_appear_in_user_message():
    client = FakeLLMClient()
    synthesize_note(
        client, raw_text=RAW, existing_titles=[], model="gpt-5.4",
        recent_frames=["🔭 Zoom out", "⚡ Plot twist"],
    )
    user_msg = client.calls[0]["messages"][1]["content"]
    assert "WILDCARD FRAMES USED BY RECENT NOTES" in user_msg
    assert "🔭 Zoom out" in user_msg
    assert "⚡ Plot twist" in user_msg


def test_run_note_ingest_feeds_recent_frames():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        nd = vault / "notes"
        nd.mkdir()
        (nd / "prior.md").write_text(NOTE_WITH_ZOOM)

        run_note_ingest(
            client, vault_root=vault, raw_text=RAW, raw_path="raw/a.md", model="gpt-5.4"
        )
        user_msg = client.calls[0]["messages"][1]["content"]
        assert "WILDCARD FRAMES USED BY RECENT NOTES" in user_msg
        assert "🔭 Zoom out" in user_msg


def _parse_frontmatter(markdown: str) -> dict:
    """yaml.safe_load the leading --- ... --- block of a note (raises if invalid)."""
    import yaml

    block = markdown.split("---", 2)[1]
    return yaml.safe_load(block)


def test_sanitize_frontmatter_fixes_colon_in_title():
    # The exact bug: a title with ": " is invalid YAML until quoted.
    md = (
        "---\n"
        "title: The Existence Project: Inside a tribal district's race\n"
        "source: Mint / Pankaj Mishra\n"
        "saved: 2026-06-24T14:41:33.784Z\n"
        "tags: [ai, india, language]\n"
        "---\n\n# body\n"
    )
    # Sanity: the input really is broken.
    try:
        import yaml

        yaml.safe_load(md.split("---", 2)[1])
        raise AssertionError("fixture should be invalid YAML")
    except Exception as e:  # noqa: BLE001
        assert "AssertionError" not in type(e).__name__

    out = sanitize_frontmatter(md)
    fm = _parse_frontmatter(out)  # must now parse
    assert fm["title"] == "The Existence Project: Inside a tribal district's race"
    assert fm["source"] == "Mint / Pankaj Mishra"


def test_sanitize_frontmatter_handles_pipe_quotes_apostrophes():
    # One title carrying every adversarial character at once.
    nasty = 'A: title with | pipes and "quotes" and \'apostrophes\''
    md = f"---\ntitle: {nasty}\nsource: Pub / Auth\n---\n\n# body\n"
    out = sanitize_frontmatter(md)
    fm = _parse_frontmatter(out)
    assert fm["title"] == nasty  # round-trips EXACTLY (verbatim, no | -> -)
    assert "|" in fm["title"] and "—" not in fm["title"]


def test_sanitize_frontmatter_is_idempotent():
    md = (
        "---\n"
        "title: From food crime: the evolution of India's fake milk | Mint\n"
        'source: "Mint / Dhirendra Kumar"\n'  # already quoted → must not double-wrap
        "tags: [india, dairy]\n"
        "---\n\n# body\n"
    )
    once = sanitize_frontmatter(md)
    twice = sanitize_frontmatter(once)
    assert once == twice  # byte-identical on re-run
    fm = _parse_frontmatter(once)
    assert fm["title"] == "From food crime: the evolution of India's fake milk | Mint"
    assert fm["source"] == "Mint / Dhirendra Kumar"


def test_sanitize_frontmatter_leaves_structured_fields_untouched():
    # saved must stay a bare ISO string and tags must stay a list — quoting them
    # would cost Dataview its date/list semantics.
    md = (
        "---\n"
        "title: Plain title\n"
        "saved: 2026-06-24T14:41:33.784Z\n"
        "tags: [ai, india, language]\n"
        "url: https://example.com/x\n"
        "type: article\n"
        "reading_time: ~11 min\n"
        "---\n\n# body\n"
    )
    out = sanitize_frontmatter(md)
    assert "saved: 2026-06-24T14:41:33.784Z\n" in out  # bare, unquoted
    assert "tags: [ai, india, language]\n" in out      # still a flow list
    assert "url: https://example.com/x\n" in out
    assert "reading_time: ~11 min\n" in out
    fm = _parse_frontmatter(out)
    assert fm["tags"] == ["ai", "india", "language"]


def test_sanitize_frontmatter_noop_without_block():
    body = "no front matter here\n\njust text\n"
    assert sanitize_frontmatter(body) == body


def test_write_note_sanitizes_broken_frontmatter():
    broken = (
        "---\n"
        "title: Foo: a broken title\n"
        "source: Pub / Auth\n"
        "---\n\n# body\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = write_note(Path(tmp), "foo", broken)
        fm = _parse_frontmatter(path.read_text())  # written file parses
        assert fm["title"] == "Foo: a broken title"


def test_synthesized_note_includes_reviewed_field():
    # New notes must include `reviewed: false` so they enter the vault review queue.
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        result = run_note_ingest(
            client, vault_root=vault, raw_text=RAW, raw_path="raw/a.md", model="gpt-5.4"
        )
        assert result["status"] == "ok"
        written = Path(result["note_path"])
        content = written.read_text()
        fm = _parse_frontmatter(content)
        assert "reviewed" in fm
        assert fm["reviewed"] is False


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
