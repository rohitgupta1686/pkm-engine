# Plan 07-04 Summary — ingest.yml nightly steps + GUARDRAILS.md (GUARD-06, GUARD-07)

**Status:** COMPLETE ✓
**Wave:** 3 (depends on 03)
**Requirements:** GUARD-06, GUARD-07

## What was built

- `.github/workflows/ingest.yml` — 7 new steps appended after the existing
  "Commit synthesized wiki" step (original triggers, concurrency, permissions,
  checkout, setup, batch-ingest, and first commit step all preserved unchanged):
  1. **Backfill embeddings** — `pkm backfill-embeds`; `if: always()`,
     `continue-on-error: true` (an embed outage must not abort the run).
  2. **Lint vault** — `pkm lint`; `continue-on-error: true` (a dirty vault writes
     to log.md and surfaces via exit code, but does not block dashboard/backup).
  3. **Compute Actions minutes this month** — `gh api` sum of `run_duration_ms`
     this month → `steps.actions_minutes.outputs.minutes` (ms→minutes).
  4. **Regenerate dashboard** — `pkm dashboard --actions-minutes …`.
  5. **80% Actions-minutes alert** — appends a `WARN actions-minutes N/cap` line
     to `log.md` when usage ≥ 80% of `PKM_ACTIONS_MINUTES_CAP` (default 2000).
  6. **Commit guardrail artifacts** — `git add dashboard.md log.md`, commit, push.
  7. **Backup push to second remote** — `git push secrets.BACKUP_REMOTE_URL
     HEAD:refs/heads/main`; `if: always()`, `continue-on-error: true`.
  - Job permissions stay `contents: read` — the backup push uses the credential
    embedded in `BACKUP_REMOTE_URL`, not `GITHUB_TOKEN`.
- `docs/GUARDRAILS.md` — operator runbook covering GUARD-04/05/06/07, the OpenAI
  reconciliation (Anthropic wording is stale), the deferred CF-credentials gap,
  per-run caps (`PKM_RUN_COST_CAP_USD` / `PKM_RUN_TOKEN_CAP`), and an env/secret
  reference table. Checkboxes for the operator to tick in Plan 05. No secret
  material.

## Verification

- `python yaml.safe_load` parses the workflow; 13 steps, all 6 new named steps
  present, `Backfill embeddings` / `Lint vault` / `Backup push` have
  `continue-on-error: true`, the two backup/backfill steps have `if: always()`,
  `actions_minutes` step has `id: actions_minutes`.
- Original `cron: "0 3 * * *"`, `repository_dispatch`, `workflow_dispatch`,
  `concurrency`, `timeout-minutes: 10`, `permissions: contents: read`, and the
  `pkm batch-ingest --new-only` step all preserved.
- Command fragments present: `pkm backfill-embeds`, `pkm lint`, `pkm dashboard`,
  `secrets.BACKUP_REMOTE_URL`, `vars.PKM_ACTIONS_MINUTES_CAP`.
- `docs/GUARDRAILS.md`: contains GUARD-04/05/06/07, mentions OpenAI + the stale
  Anthropic wording, references `BACKUP_REMOTE_URL`, `CF_API_TOKEN`,
  `PKM_RUN_COST_CAP_USD`, `PKM_RUN_TOKEN_CAP`; grep for `sk-` / `ghp_` /
  `github_pat_` / `x-access-token:<alnum>` returns nothing (no secrets).
- Full test suite still green (134 passed) — Plan 04 touches only the workflow
  and a doc, no code.

## Decisions / deviations

- `PKM_ACTIONS_MINUTES_CAP` read from the `vars` context with a `'2000'` default
  (`${{ vars.PKM_ACTIONS_MINUTES_CAP || '2000' }}`) so it is overridable via a
  repo variable without editing the workflow.
- The 80% alert is informational for the public repo (minutes are free/unbilled);
  documented as defense-in-depth for a future private-repo scenario.
- Backup `continue-on-error: true` means an outage is a yellow step, not a failed
  run — the operator monitors run history (T-07-04-05 accepted).