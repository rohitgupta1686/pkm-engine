# Plan 07-01 Summary — Lint module (GUARD-01)

**Status:** COMPLETE ✓
**Wave:** 1
**Requirements:** GUARD-01

## What was built

- `pkm/lint.py` — pure `lint_vault(conn, vault_root, write_log=True, now=None) -> LintReport`
  with three checks:
  - **broken [[wikilinks]]** — `[[token]]` whose target slug has no matching page stem
    under `wiki/sources/` or `wiki/concepts/`; handles `[[slug|alias]]` pipe form.
  - **orphans** — a wiki page not referenced by any *other* page and not present in
    `index.md`.
  - **missing provenance** — `SELECT id, statement, source_id FROM claims WHERE chunk_id IS NULL`
    (parameterized; no value interpolation).
  - Log writer: `lint ok` line on a clean vault, `lint FAIL broken=N orphan=N missing_provenance=N`
    header + up to 50 detail lines on a dirty vault, via `pkm.store.vault.append_log`.
- `tests/test_lint.py` — 13 tests covering all three checks, clean/dirty paths, the
  log.md write contract, and report shape.

## Verification

- `pytest tests/test_lint.py -x` → 13 passed
- `pytest` (full suite) → 113 passed (additive; no existing files modified)
- `grep -c "COUNT" pkm/lint.py` → 0 (filtered WHERE, no aggregate scan)

## Decisions / deviations

- Orphan check uses substring match of the page slug in `index.md` (matches the plan's
  "appears in index.md" wording); a `[[slug]]` link or bare slug both satisfy it.
- Self-references do not clear an orphan — a page must be referenced by a *different*
  page or listed in `index.md`.
- Pipe-alias wikilinks (`[[slug|display]]`) resolve to the left side as the target.