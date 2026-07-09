"""Unit tests for the weekly digest path.

Dependency-light: a FakeLLMClient stands in for the OpenAI-backed LLMClient
(same ``call(**kwargs) -> dict`` shape as tests/test_synthesize.py), so these
run without the SDK. Focuses on the parts that are easy to get wrong: the date
window, thesis/tag extraction, digest exclusion (a digest never folds itself
back in), the `empty` path, and the frontmatter of the written digest note.
"""
from __future__ import annotations

import datetime
import tempfile
from pathlib import Path

from pkm.pipeline.digest import (
    DIGEST_AGENT_NAME,
    DIGEST_PROMPT_VERSION,
    _parse_saved,
    build_digest,
    collect_recent_notes,
    run_digest,
)

DIGEST_BODY = "# Weekly digest — test\n\n> [!abstract] The week in one line\n> AI everywhere.\n"


class FakeLLMClient:
    """Records every call() and returns a canned digest body with a cost."""

    def __init__(self, *, result=DIGEST_BODY, cost=0.02):
        self.calls = []
        self._result = result
        self._cost = cost

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "cached": False, "input_hash": "deadbeef", "result": self._result,
            "tokens_in": 200, "tokens_out": 80, "cost_usd": self._cost,
        }


def _note(saved, title, thesis="A thesis.", tags="[ai]", ntype="article"):
    return (
        f"---\ntitle: {title}\nsource: The Economist\nsaved: {saved}\n"
        f"type: {ntype}\ntags: {tags}\nreading_time: \"~4 min\"\nreviewed: false\n---\n\n"
        f"# {title}\n\n> [!abstract] Thesis\n> {thesis}\n\n## TL;DR\n- x\n"
    )


def _seed(vault: Path, files: dict[str, str]):
    (vault / "notes").mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (vault / "notes" / name).write_text(body, encoding="utf-8")


def test_parse_saved_handles_date_and_iso():
    assert _parse_saved("2026-06-25").year == 2026
    assert _parse_saved("2026-06-25T15:17:40.861Z").hour == 15
    assert _parse_saved("") is None
    assert _parse_saved("garbage") is None


def test_collect_windows_by_saved():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        recent = (now - datetime.timedelta(days=2)).isoformat() + "Z"
        old = (now - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
        _seed(vault, {
            "recent.md": _note(recent, "Recent One", thesis="Fresh take."),
            "old.md": _note(old, "Old One"),
        })
        since = now - datetime.timedelta(days=7)
        got = collect_recent_notes(vault, since)
        assert [n["slug"] for n in got] == ["recent"]
        assert got[0]["thesis"] == "Fresh take."
        assert got[0]["tags"] == "[ai]"


def test_collect_excludes_prior_digests():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        recent = (now - datetime.timedelta(days=1)).isoformat() + "Z"
        _seed(vault, {
            "a.md": _note(recent, "Article"),
            "d.md": _note(recent, "Last week digest", ntype="digest"),
        })
        got = collect_recent_notes(vault, now - datetime.timedelta(days=7))
        assert [n["slug"] for n in got] == ["a"]


def test_build_digest_uses_system_prompt_and_user_context():
    client = FakeLLMClient()
    notes = [{"slug": "a", "title": "A", "source": "S", "tags": "[x]", "thesis": "T",
              "saved": datetime.datetime.now()}]
    out = build_digest(client, notes, "Jun 1 – Jun 7, 2026", "gpt-5.4")
    assert out["text"] == DIGEST_BODY
    assert out["tokens_in"] == 200
    assert out["tokens_out"] == 80
    assert out["cost_usd"] == 0.02

    kw = client.calls[0]
    assert kw["agent_name"] == DIGEST_AGENT_NAME
    assert kw["model"] == "gpt-5.4"
    assert kw["prompt_version"] == DIGEST_PROMPT_VERSION
    assert kw["output_schema"] is None  # freeform markdown, not a schema

    msgs = kw["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "chief of staff" in msgs[0]["content"]   # digest prompt present, in the system slot
    assert "slug: a" in msgs[1]["content"]           # note metadata present, in the user turn


def test_run_digest_writes_note_with_digest_frontmatter():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        recent = (now - datetime.timedelta(days=1)).isoformat() + "Z"
        _seed(vault, {"a.md": _note(recent, "Article One")})

        r = run_digest(FakeLLMClient(), vault, model="gpt-5.4", days=7)

        assert r["status"] == "ok" and r["note_count"] == 1
        assert r["cost_usd"] == 0.02
        text = Path(r["note_path"]).read_text()
        assert "type: digest" in text
        assert "reviewed: true" in text          # digests stay out of the review queue
        assert text.startswith("---")
        assert "# Weekly digest" in text


def test_run_digest_empty_when_no_recent_notes():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        _seed(vault, {"old.md": _note((now - datetime.timedelta(days=99)).strftime("%Y-%m-%d"), "Old")})

        client = FakeLLMClient()
        r = run_digest(client, vault, model="gpt-5.4", days=7)

        assert r["status"] == "empty" and r["note_path"] is None
        assert client.calls == []  # never reached the model


def test_run_digest_excludes_prior_digest_from_its_own_input():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        recent = (now - datetime.timedelta(days=1)).isoformat() + "Z"
        _seed(vault, {
            "a.md": _note(recent, "Article"),
            "prior-digest.md": _note(recent, "Last week digest", ntype="digest"),
        })

        client = FakeLLMClient()
        r = run_digest(client, vault, model="gpt-5.4", days=7)

        assert r["status"] == "ok" and r["note_count"] == 1  # digest not folded into its own input
        user_msg = client.calls[0]["messages"][1]["content"]
        assert "slug: a" in user_msg
        assert "prior-digest" not in user_msg
