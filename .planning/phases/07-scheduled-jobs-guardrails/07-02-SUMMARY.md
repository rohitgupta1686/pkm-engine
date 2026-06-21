# Plan 07-02 Summary — Dashboard + counter rows (GUARD-02, GUARD-03)

**Status:** COMPLETE ✓
**Wave:** 1
**Requirements:** GUARD-02, GUARD-03

## What was built

- `migrations/sqlite/003_dashboard_counters.sql` — `dashboard_counters(key, value, updated_at)`;
  rows lazy-created by `bump_counter` (no seed insert).
- `pkm/store/registry.py`:
  - `_run_migrations` now runs `003_dashboard_counters.sql` too.
  - `bump_counter(conn, key, delta=1, commit=True) -> int` — UPSERT via
    `INSERT ... ON CONFLICT DO UPDATE`, returns new value.
  - `read_counter`, `read_all_counters` helpers.
  - Bumps wired additively into the insert paths (commit=False so they share the
    caller's transaction): `upsert_source`/`upsert_concept` bump
    `sources_total`/`concepts_total` only when `created=True`; `insert_claim`
    bumps `claims_total` on every insert (claims are always new rows).
- `pkm/dashboard.py` — `generate_dashboard(...)` renders all six required sections
  (`## Sources`, `## Claims`, `## Concepts`, `## Insights accepted`,
  `## Actions minutes`, `## Orphans / stale`) from `read_all_counters` +
  `lint_vault(..., write_log=False)`; `write_dashboard(...)` writes
  `vault_root/dashboard.md` and returns `"dashboard.md"`. `actions_minutes=None`
  renders `N/A`.
- `tests/test_dashboard.py` — 16 tests: counters table, helpers, bump wiring,
  idempotent-reingest stability, dashboard rendering, no-scan spy, orphan/from-lint,
  insights-accepted default 0, optional actions-minutes, file write.

## Verification

- `pytest tests/test_dashboard.py -x` → 16 passed
- `pytest tests/test_idempotency.py tests/test_ingest_e2e.py tests/test_batch_ingest.py` → 24 passed
- `pytest` (full suite) → 129 passed (counter bumps did not regress existing assertions)
- `grep -c "COUNT(\*) FROM sources\|COUNT(\*) FROM claims\|COUNT(\*) FROM concepts" pkm/dashboard.py pkm/store/registry.py` → 0 / 0

## Decisions / deviations

- `insights_accepted` counter is wired as a key but not bumped anywhere yet (no
  approval path exists in MVP); a future approval step will call
  `bump_counter(conn, "insights_accepted", 1)`.
- `wiki_pages` count prefers a `wiki_pages_total` counter when present, else
  falls back to a filesystem glob over `wiki/sources/*.md` + `wiki/concepts/*.md`.
  The GUARD-03 no-scan rule is about DB tables; the filesystem glob is bounded
  and does not touch Turso.
- `dashboard.md` is committed back to the vault by the existing ingest workflow
  step (`git add dashboard.md 2>/dev/null || true`); Plan 04 adds an explicit
  guardrail commit step.