"""Unit tests for the source-notes path (books / podcasts / lectures).

Dependency-light: a FakeLLMClient stands in for OpenAI, so these run without the
SDK. Runnable under pytest or directly:  python3 tests/test_ingest_notes.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

# Allow `python3 tests/test_ingest_notes.py` from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pkm.ingest.md_reader import (  # noqa: E402
    STATE_FILENAME,
    classify,
    load_state,
    parse_capture,
    record,
    save_state,
)
from pkm.pipeline.ingest_source_notes import run_source_notes_ingest  # noqa: E402
from pkm.pipeline.synthesize import (  # noqa: E402
    NOTES_AGENT_NAME,
    NOTES_PROMPT_VERSION,
)

NOTE_MD = "---\ntitle: x\ntype: book\nreviewed: false\n---\n\n# x\n\nbody\n"

CAPTURE_BOOK = (
    "---\n"
    'title: "Atomic Habits"\n'
    "type: book\n"
    "captured: 2026-06-28T10:00:00.000Z\n"
    "---\n"
    "Systems over goals. You do not rise to the level of your goals, you fall to "
    "the level of your systems.\n\n"
    "==1% better every day compounds.==\n"
)

# No front matter at all — title must fall back to the (humanized) filename, type
# to the default "book".
CAPTURE_BARE_BODY = "Just a few rough notes I jotted while listening. No front matter.\n"


class FakeLLMClient:
    """Records every call() and returns a canned note with a cost."""

    def __init__(self, *, result=NOTE_MD, cost=0.01):
        self.calls = []
        self._result = result
        self._cost = cost

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "cached": False, "input_hash": "deadbeef", "result": self._result,
            "tokens_in": 1000, "tokens_out": 500, "cost_usd": self._cost,
        }


def _write(dirpath: Path, name: str, text: str, *, age_seconds: int = 3600) -> Path:
    """Write a capture file and back-date its mtime so it isn't 'too fresh'."""
    import os

    p = dirpath / name
    p.write_text(text, encoding="utf-8")
    past = time.time() - age_seconds
    os.utime(p, (past, past))
    return p


# --- md_reader: parsing ----------------------------------------------------

def test_parse_capture_reads_frontmatter_title_type_captured():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "whatever.md", CAPTURE_BOOK)
        cap = parse_capture(p)
        assert cap.title == "Atomic Habits"
        assert cap.slug == "atomic-habits"
        assert cap.source_type == "book"
        assert cap.captured == "2026-06-28T10:00:00.000Z"
        assert cap.para_count == 2
        assert cap.content_sha  # non-empty


def test_parse_capture_falls_back_to_filename_and_default_type():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "deep_work-notes.md", CAPTURE_BARE_BODY)
        cap = parse_capture(p)
        assert cap.title == "deep work notes"  # humanized stem
        assert cap.slug == "deep-work-notes"
        assert cap.source_type == "book"  # default
        assert cap.captured is None


def test_unknown_type_falls_back_to_book():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "x.md", "---\ntitle: X\ntype: novella\n---\nbody\n")
        assert parse_capture(p).source_type == "book"


def test_podcast_type_preserved():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "x.md", "---\ntitle: Ep 12\ntype: podcast\n---\nbody\n")
        assert parse_capture(p).source_type == "podcast"


def test_content_sha_ignores_frontmatter_only_edits():
    # Changing front matter (not body) must NOT change the content SHA, so a tag
    # tweak doesn't trigger a needless re-synthesis.
    with tempfile.TemporaryDirectory() as tmp:
        a = _write(Path(tmp), "a.md", "---\ntitle: T\ntype: book\n---\nSame body.\n")
        b = _write(Path(tmp), "b.md", "---\ntitle: DIFFERENT\ntype: podcast\n---\nSame body.\n")
        assert parse_capture(a).content_sha == parse_capture(b).content_sha


def test_raw_for_synthesis_roundtrips_title_type_and_body():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "x.md", CAPTURE_BOOK)
        raw = parse_capture(p).raw_for_synthesis()
        assert raw.startswith("---")
        assert "title: Atomic Habits" in raw
        assert "type: book" in raw
        assert "captured: 2026-06-28T10:00:00.000Z" in raw
        assert "Systems over goals" in raw


# --- md_reader: classify + state -------------------------------------------

def test_classify_new_unchanged_changed():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "x.md", CAPTURE_BOOK)
        cap = parse_capture(p)
        state: dict = {}
        assert classify(state, cap) == "new"
        record(state, cap)
        assert classify(state, cap) == "unchanged"
        # Edit the body → SHA changes → "changed".
        p.write_text(CAPTURE_BOOK + "\nA new highlight added later.\n", encoding="utf-8")
        cap2 = parse_capture(p)
        assert classify(state, cap2) == "changed"


def test_state_roundtrip_and_first_seen_preserved():
    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / STATE_FILENAME
        assert load_state(sp) == {}
        p = _write(Path(tmp), "x.md", CAPTURE_BOOK)
        cap = parse_capture(p)
        state: dict = {}
        record(state, cap)
        first = state[cap.slug]["first_seen"]
        save_state(sp, state)
        reloaded = load_state(sp)
        assert reloaded[cap.slug]["content_sha"] == cap.content_sha
        # Re-record after a body edit keeps the original first_seen.
        record(reloaded, cap)
        assert reloaded[cap.slug]["first_seen"] == first


# --- pipeline: run_source_notes_ingest -------------------------------------

def test_run_ingest_synthesizes_new_and_writes_state_and_note():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        _write(Path(src), "atomic-habits.md", CAPTURE_BOOK)
        summary = run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        assert summary["synthesized"] == 1
        assert summary["unchanged"] == 0
        assert summary["failed"] == 0
        # Note written, state persisted.
        assert (Path(vlt) / "notes" / "atomic-habits.md").exists()
        assert (Path(vlt) / "notes" / STATE_FILENAME).exists()
        # Used the NOTES engine, not the article engine.
        kw = client.calls[0]
        assert kw["agent_name"] == NOTES_AGENT_NAME
        assert kw["prompt_version"] == NOTES_PROMPT_VERSION
        assert "study companion" in kw["messages"][0]["content"]  # notes prompt loaded
        # No wildcard-frames block for the notes path.
        assert "WILDCARD FRAMES" not in kw["messages"][1]["content"]


def test_rerun_unchanged_makes_no_llm_call():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        _write(Path(src), "atomic-habits.md", CAPTURE_BOOK)
        run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        assert len(client.calls) == 1
        # Second run: nothing changed → no new call.
        summary = run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        assert len(client.calls) == 1  # unchanged
        assert summary["unchanged"] == 1
        assert summary["synthesized"] == 0


def test_edited_body_triggers_resynthesis():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        p = _write(Path(src), "atomic-habits.md", CAPTURE_BOOK)
        run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        # Edit the body and back-date mtime so it's not 'too fresh'.
        _write(Path(src), "atomic-habits.md", CAPTURE_BOOK + "\nNew chapter notes.\n")
        summary = run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        assert len(client.calls) == 2
        assert summary["synthesized"] == 1
        assert summary["results"][0]["change"] == "changed"


def test_fresh_file_is_skipped():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        # Modified just now → within MIN_AGE_SECONDS → skipped this run.
        _write(Path(src), "x.md", CAPTURE_BOOK, age_seconds=0)
        summary = run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        assert client.calls == []
        assert summary["skipped_fresh"] == 1
        assert summary["synthesized"] == 0


def test_cost_cap_aborts_before_exceeding():
    # Soft cap (same as batch-ingest): abort once accumulated spend has reached the
    # cap. One call at 0.60 crosses 0.50, so the second source is not synthesized.
    client = FakeLLMClient(cost=0.60)
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        _write(Path(src), "a.md", "---\ntitle: A\n---\nbody one is long enough.\n")
        _write(Path(src), "b.md", "---\ntitle: B\n---\nbody two is long enough.\n")
        summary = run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
            cost_cap_usd=0.50,
        )
        assert summary["synthesized"] == 1
        assert summary["cost_capped"] is True


def test_bare_body_below_article_guard_still_synthesizes():
    # A new source with very few chars must NOT be skipped (the article path's
    # 200-char empty-body guard is relaxed on this path).
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        _write(Path(src), "tiny.md", "One short highlight.\n")
        summary = run_source_notes_ingest(
            client, sources_dir=Path(src), vault_root=Path(vlt), model="gpt-5.4",
        )
        assert summary["synthesized"] == 1


def test_source_paths_limits_ingest_to_one_capture():
    client = FakeLLMClient()
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as vlt:
        source_dir = Path(src)
        wanted = _write(source_dir, "wanted.md", "---\ntitle: Wanted\n---\nbody\n")
        _write(source_dir, "other.md", "---\ntitle: Other\n---\nbody\n")
        summary = run_source_notes_ingest(
            client, source_dir, Path(vlt), "gpt-5.4", source_paths=[wanted],
        )
        assert summary["total"] == 1
        assert summary["synthesized"] == 1
        assert len(client.calls) == 1


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
