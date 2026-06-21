# Plan 07-03 Summary — CLI wiring + backfill_embeds (GUARD-01, GUARD-02)

**Status:** COMPLETE ✓
**Wave:** 2 (depends on 01, 02)
**Requirements:** GUARD-01, GUARD-02

## What was built

- `pkm/retrieval/embed.py` — `backfill_embeds(conn, cf_account_id, cf_api_token,
  index_name="pkm-claims", batch_size=100) -> dict`: the reusable, idempotent
  replacement for the throwaway Phase-6 Wave 3 backfill script. Embeds every claim
  lacking an `embeddings_meta` row. Empty-creds no-op guard; delegates embedding to
  the existing `embed_claims` (no duplicate HTTP path). One pass per run — a claim
  whose embed call fails stays missing and retries on the next nightly run
  (prevents an infinite retry loop within a single run). `skipped` reports claims
  already in `embeddings_meta`.
- `pkm/cli.py` — three new subcommands wired into `_build_parser` + dispatch:
  - `pkm lint --vault <path> [--no-log]` → `lint_vault`; exits 1 on a dirty vault.
  - `pkm dashboard --vault <path> [--actions-minutes N]` → `write_dashboard`.
  - `pkm backfill-embeds [--vault <path>] [--batch-size N]` → `backfill_embeds`;
    exits 1 if `failed > 0`.
  - New handlers print only result dicts (counts/paths) — never Settings or api_key
    (T-03-09). `backfill-embeds` does not require a vault root (it reads the DB).
- `tests/test_backfill_embeds.py` — 5 tests: no-creds no-op, no-missing no-op,
  embeds missing claims (one Vectorize upsert for one source), per-claim failure
  (failed claim not embedded this run), raw_path + source_id in vector metadata.

## Verification

- `pytest tests/test_backfill_embeds.py -x` → 5 passed
- `pytest` (full suite) → 134 passed
- `pkm --help` lists `lint`, `dashboard`, `backfill-embeds`; per-subcommand
  `--help` exits 0 and shows `vault` / `actions-minutes` / `batch-size` respectively.
- Functional smoke (temp vault + DB): `pkm dashboard` writes dashboard.md; `pkm lint`
  on a clean vault writes `lint ok` to log.md and exits 0; on a dirty vault writes a
  `lint FAIL` block and exits 1; `pkm backfill-embeds` with no CF creds is a no-op
  (zeros) and exits 0.

## Decisions / deviations

- `backfill_embeds` makes one pass over missing claims per run (no re-query retry
  loop). The plan's "loop in batches until no more missing" would infinite-loop on a
  persistently-failing claim; one-pass + retry-next-night is idempotent and matches
  the per-claim-failure test contract. `batch_size` still chunks each source group.
- `skipped` is computed as the count of claims already in `embeddings_meta` (plus
  any per-call skips), so the no-missing case reports `skipped=N` as the behavior
  test requires.
- `backfill-embeds` accepts `--vault` for surface consistency but does not require
  it (the function operates on the DB only).