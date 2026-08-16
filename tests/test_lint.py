"""Tests for the markdown-native vault lint (pkm/lint.py). No LLM, no network."""
from __future__ import annotations

from pathlib import Path

from pkm.lint import lint_vault


def _mk_vault(tmp_path: Path) -> Path:
    (tmp_path / "notes").mkdir()
    (tmp_path / "advice" / "briefs").mkdir(parents=True)
    return tmp_path


def _note(vault: Path, slug: str, body: str, reviewed: str = "true") -> None:
    (vault / "notes" / f"{slug}.md").write_text(
        f"---\ntitle: \"{slug}\"\nreviewed: {reviewed}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_clean_vault_reports_zero_broken(tmp_path):
    vault = _mk_vault(tmp_path)
    _note(vault, "alpha", "links to [[beta]] and [[beta|an alias]] and [[beta#h1]]")
    _note(vault, "beta", "no links here")
    report = lint_vault(vault)
    assert report["broken_count"] == 0
    assert report["notes"] == 2


def test_broken_link_detected_with_page_and_target(tmp_path):
    vault = _mk_vault(tmp_path)
    _note(vault, "alpha", "links to [[does-not-exist]]")
    report = lint_vault(vault)
    assert report["broken_count"] == 1
    assert report["broken_links"] == [{"page": "alpha", "target": "does-not-exist"}]


def test_links_resolve_to_root_and_advice_pages(tmp_path):
    vault = _mk_vault(tmp_path)
    (vault / "Profile.md").write_text("# profile\n", encoding="utf-8")
    (vault / "advice" / "briefs" / "2026-08-15-brief.md").write_text(
        "cites [[alpha]] and [[Profile]]\n", encoding="utf-8"
    )
    _note(vault, "alpha", "links [[Profile]] and [[2026-08-15-brief]]")
    report = lint_vault(vault)
    assert report["broken_count"] == 0


def test_advice_files_are_scanned_for_broken_links(tmp_path):
    vault = _mk_vault(tmp_path)
    (vault / "advice" / "briefs" / "b.md").write_text("[[ghost-note]]\n", encoding="utf-8")
    report = lint_vault(vault)
    assert report["broken_count"] == 1
    assert report["broken_links"][0]["page"] == "b"


def test_unreviewed_count(tmp_path):
    vault = _mk_vault(tmp_path)
    _note(vault, "a", "x", reviewed="false")
    _note(vault, "b", "y", reviewed="true")
    _note(vault, "c", "z", reviewed="false")
    report = lint_vault(vault)
    assert report["unreviewed"] == 2
    assert report["notes"] == 3


def test_missing_dirs_do_not_crash(tmp_path):
    # vault with no notes/ or advice/ at all
    report = lint_vault(tmp_path)
    assert report == {
        "notes": 0,
        "unreviewed": 0,
        "broken_count": 0,
        "broken_links": [],
    }
