---
phase: 07-scheduled-jobs-guardrails
plan: 05
type: execute
wave: 4
depends_on: [04]
autonomous: false
requirements: [GUARD-04, GUARD-05, GUARD-07]
status: complete
completed: 2026-06-21
---

# Plan 07-05 Summary — Operator guardrail confirmations + end-to-end nightly verification

## What was done

Plan 05 was the operator checkpoint (autonomous:false). The operator performed
the external console/account configurations that Claude cannot do autonomously
(widening secret scope + setting billing caps = Mode C surface), and Claude
verified the end-to-end nightly run.

### Task 1 — external guardrails + secrets (operator)

- **GUARD-04** — GitHub Actions spending limit = $0 confirmed. pkm-engine is
  public (unlimited free minutes); private pkm-vault spending limit set to $0
  (fail-closed).
- **GUARD-05** — OpenAI monthly hard spend limit set in the OpenAI console
  (reconciled from the stale "Anthropic" wording — backend swapped in Phase 2).
  Per-run caps `PKM_RUN_COST_CAP_USD` (0.50) / `PKM_RUN_TOKEN_CAP` (200000)
  confirmed present in `pkm/batch.py`. Numeric cap value held in OpenAI billing
  settings, not transcribed into the repo.
- **GUARD-07** — second remote `rohitgupta1686/pkm-vault-backup` created;
  fine-grained PAT (contents:read+write on `pkm-vault-backup` ONLY) issued;
  `BACKUP_REMOTE_URL` secret added to pkm-engine with the credential embedded.
- **Deferred CF creds** — `CF_ACCOUNT_ID` + `CF_API_TOKEN` (Workers AI:Read +
  Vectorize:Edit) added as GH Actions secrets, closing the Phase 6 Wave 3 gap.
  CI ingest now embeds new claims instead of no-oping.

All checkboxes in `docs/GUARDRAILS.md` ticked with date 2026-06-21; no secret
values committed (grep for `ghp_`/`github_pat_`/`x-access-token:`/`api.cloudflare`
returns nothing).

### Task 2 — end-to-end nightly verification (Claude, from CLI)

Triggered `workflow_dispatch` of `ingest.yml`. Verification run:
https://github.com/rohitgupta1686/pkm-engine/actions/runs/27901063045
(2026-06-21, conclusion: success). All 7 Phase 7 steps green; all 5 ROADMAP
success criteria PASS — see the Verification section in `docs/GUARDRAILS.md`.

## Two workflow bugs found and fixed during verification

The backup push (criterion 5) failed on the first verification runs. Root-caused
and fixed both (commits `2e2f6ae` and `1b857d7`):

1. **403 "Write access not granted"** — `actions/checkout` with
   `persist-credentials: true` injects `VAULT_PAT` as
   `http.https://github.com/.extraheader`, which overrides the backup token
   embedded in `BACKUP_REMOTE_URL` for any `github.com` push. VAULT_PAT is
   scoped to `pkm-vault` only → 403 on `pkm-vault-backup`. Fix: clear the
   extraheader for the backup push (`git -c http.https://github.com/.extraheader=
   push …`) so the URL-embedded backup credential is used.
2. **"remote unpack failed: index-pack failed / did not receive expected
   object"** — `actions/checkout` defaults to `fetch-depth: 1` (shallow), so the
   vault checkout lacks parent history; pushing to the empty backup remote needs
   complete ancestry the shallow clone can't supply. Fix: `fetch-depth: 0` on
   the vault checkout so the backup mirrors full history.

Both gotchas are documented in `docs/GUARDRAILS.md` GUARD-07 so they don't regress.

## Known follow-up (not a Phase 7 blocker)

Dashboard `Sources/Claims/Concepts` counters read 0 because
`dashboard_counters` (migration 003) rows only bump on NEW inserts going
forward — pre-Phase-7 data (~160 claims) was never counted. Lint's
orphan/missing-provenance counts ARE correct (they query live tables, not
counters). A one-time counter backfill seeded from existing rows would make the
dashboard reflect historical totals; carry into Phase 8.

## Threat model dispositions

- T-07-05-01 (backup PAT scope) — mitigated: fine-grained PAT, contents:write on
  `pkm-vault-backup` ONLY.
- T-07-05-02 (secrets committed) — mitigated: grep returns no secret material in
  `docs/GUARDRAILS.md`.
- T-07-05-03 (CF token scope) — mitigated: Workers AI:Read + Vectorize:Edit only.
- T-07-05-04 (repudiation) — mitigated: confirmation dates + run URL recorded in
  `docs/GUARDRAILS.md`.

## Result

Phase 7 (GUARD-01–07) COMPLETE. All 5 ROADMAP success criteria verified PASS via
a real `workflow_dispatch` run; backup remote mirrors pkm-vault; deferred CF-creds
gap closed. Next: Phase 8 (Hardening + MVP Gate) — **do NOT start V1
autonomously**.