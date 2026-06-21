# PKM Guardrails Runbook (Phase 7)

This is the **operator-side companion** to the automated guardrails in
`.github/workflows/ingest.yml`. The workflow runs the machine-side checks nightly
(backfill-embeds, lint, dashboard regeneration, 80% alert, backup push). This
document covers the guardrails that require a human to confirm or configure in an
external console — and records when each was confirmed.

The detailed per-item setup steps live in the **Plan 05 checkpoint**
(`.planning/phases/07-scheduled-jobs-guardrails/07-05-PLAN.md`). Tick the boxes
below as you complete them.

> **No secrets are recorded here.** This is a runbook, not a credentials file
> (Hard Constraint: no secrets committed). Record only that a value is set, never
> the value itself.

---

## GUARD-04 — GitHub Actions spending limit = $0

- **pkm-engine is a PUBLIC repo** → GitHub grants unlimited free Actions minutes
  for public repositories. No spending limit is billable on this repo.
- For the **private pkm-vault repo** (and any future private mirror): go to
  GitHub account → Settings → Billing & plans → Spending limit → set the Actions
  spending limit to **$0** (fail-closed). A run that would exceed the free quota
  is then **halted by GitHub, not billed**.

**Test:** a run that exceeds the free quota on a private repo fails to start/runs
out of minutes instead of producing a charge.

- [ ] GUARD-04 confirmed (public repo: unlimited free; private repo: spending limit = $0) — date: ______

---

## GUARD-05 — LLM monthly spend cap (OpenAI, not Anthropic)

> **RECONCILIATION NOTE:** the original requirement and cloud doc say "Anthropic
> monthly spend cap", but the LLM backend was swapped to **OpenAI** in Phase 2
> (see `STATE.md` prerequisites; `.env.example` key is `OPENAI_API_KEY`, model is
> `gpt-5.4-mini`). GUARD-05 is therefore satisfied against **OpenAI**. The
> Anthropic wording in the cloud doc is stale.

- **Console cap:** log in to the OpenAI console → Settings → Billing → set a
  monthly budget / **hard spend limit** (fail-closed). Record the cap *value*
  (e.g. "$X/month") below — not the key.
- **Per-run code caps (already enforced, confirm only):**
  - `PKM_RUN_COST_CAP_USD` (default `0.50`) — `pkm/batch.py` aborts a run if the
    running spend exceeds this.
  - `PKM_RUN_TOKEN_CAP` (default `200000`) — `pkm/batch.py` aborts a run if the
    running token count exceeds this.

**Test:** a run that would exceed `PKM_RUN_COST_CAP_USD` / `PKM_RUN_TOKEN_CAP`
aborts before completion; a month that would exceed the OpenAI hard limit is
rejected by the API/console rather than billed.

- [ ] GUARD-05 confirmed (OpenAI monthly hard limit set) — cap value: $____/mo — date: ______
- [ ] Per-run caps `PKM_RUN_COST_CAP_USD` / `PKM_RUN_TOKEN_CAP` confirmed present in `pkm/batch.py` — date: ______

---

## GUARD-06 — 80% Actions-minutes alert

The nightly workflow computes approximate monthly Actions minutes from
`gh api repos/{repo}/actions/runs` (sum of `run_duration_ms` this month, ms→minutes),
compares to `PKM_ACTIONS_MINUTES_CAP` (repo variable, default **2000**), and at
**≥ 80%** appends a line to `vault/log.md`:

```
2026-06-21T03:00:00Z WARN actions-minutes 1600/2000 (>=80%)
```

The "Compute Actions minutes this month" and "80% Actions-minutes alert" steps in
`ingest.yml` implement this. For the public `pkm-engine` repo minutes are
free/unbilled, so this is **informational** — defense in depth for a future
private-repo scenario where minutes are metered.

**Test:** the 80% step runs each nightly cycle; with `PKM_ACTIONS_MINUTES_CAP`
deliberately set low (e.g. `1`), a `WARN actions-minutes` line appears in
`vault/log.md`.

- [ ] GUARD-06 step present in `ingest.yml` (no operator config needed for the public repo)

---

## GUARD-07 — Second git remote + nightly backup push

The vault is the **only irreplaceable asset** — Turso and Vectorize can both be
rebuilt from `raw/` (cloud doc §13 line 350). The nightly "Backup push to second
remote" step mirrors the vault HEAD to an off-site git host:

```
git push "${{ secrets.BACKUP_REMOTE_URL }}" HEAD:refs/heads/main
```

`BACKUP_REMOTE_URL` is a **repository secret** in `pkm-engine` holding the full
https push URL for a second private GitHub repo (e.g. `pkm-vault-backup`) or
another git host, with a credential embedded:

```
https://x-access-token:<TOKEN>@github.com/<owner>/pkm-vault-backup.git
```

The credential (fine-grained PAT or deploy token) must be scoped to
**contents:write on the backup repo ONLY** — not the production vault. GitHub
masks `${{ secrets.BACKUP_REMOTE_URL }}` in logs. The step is `continue-on-error:
true` so a backup-remote outage surfaces as a yellow step without aborting the
ingest run. Job permissions stay `contents: read` — the push uses
`BACKUP_REMOTE_URL`'s embedded credential, not `GITHUB_TOKEN`.

Setup steps (create the backup repo, create the scoped token, construct the URL,
add the `BACKUP_REMOTE_URL` secret) are in the Plan 05 checkpoint.

**Test:** after a nightly run, the backup remote's `main` branch HEAD matches
`pkm-vault`'s `main` HEAD.

- [ ] Backup remote created (repo / host): ______
- [ ] `BACKUP_REMOTE_URL` secret added to pkm-engine (scoped to backup repo only) — date: ______

---

## Phase 6 deferred gap — CF credentials for CI embedding

`CF_ACCOUNT_ID` + `CF_API_TOKEN` must be added as **GitHub Actions secrets** in
`pkm-engine` so the nightly `pkm batch-ingest` + `pkm backfill-embeds` steps embed
newly ingested claims into Cloudflare Vectorize. Without them, the embed steps
are no-ops and the query worker goes stale for sources ingested in CI.

- **Scopes:** `Workers AI:Read` + `Vectorize:Edit` (+ `Account:Read` for account-id
  lookup). Matches the Phase 5 `worker-clip` token discipline — no account-wide token.
- The `pkm backfill-embeds` CLI (Phase 7 Plan 03) is the reusable backfill that
  replaces the throwaway Phase-6 Wave 3 script; once the creds are present it
  catches up all claims that were ingested while creds were absent.

Setup is a Plan 05 checkpoint.

**Test:** after creds are added, a nightly run's "Backfill embeddings" step
reports `embedded > 0` (or `skipped = N` if all claims were already embedded);
`SELECT COUNT(*) FROM embeddings_meta` equals `SELECT COUNT(*) FROM claims` in Turso.

- [ ] `CF_ACCOUNT_ID` secret added to pkm-engine — date: ______
- [ ] `CF_API_TOKEN` secret added to pkm-engine (scoped Workers AI:Read + Vectorize:Edit) — date: ______

---

## Env / secret reference

Phase 7 workflow inputs (see `SECRETS.md` for the pre-existing ones):

| Name | Kind | Purpose | Status |
|------|------|---------|--------|
| `OPENAI_API_KEY` | secret | LLM calls during ingest | pre-existing |
| `TURSO_URL` | secret | libSQL connection | pre-existing |
| `TURSO_TOKEN` | secret | Turso auth | pre-existing |
| `VAULT_PAT` | secret | checkout + commit-back to pkm-vault | pre-existing |
| `CF_ACCOUNT_ID` | secret | Workers AI + Vectorize (embed/backfill) | **Plan 05 checkpoint** |
| `CF_API_TOKEN` | secret | Workers AI:Read + Vectorize:Edit | **Plan 05 checkpoint** |
| `BACKUP_REMOTE_URL` | secret | off-site vault backup push (GUARD-07) | **Plan 05 checkpoint** |
| `PKM_ACTIONS_MINUTES_CAP` | repo variable | 80% alert cap (default 2000) | optional |
| `PKM_RUN_COST_CAP_USD` | env (workflow) | per-run spend cap (default 0.50) | enforced in `pkm/batch.py` |
| `PKM_RUN_TOKEN_CAP` | env (workflow) | per-run token cap (default 200000) | enforced in `pkm/batch.py` |

---

## Verification (completed in Plan 05 Task 2)

_A manual `workflow_dispatch` run of the ingest workflow must produce all Phase 7
artifacts end-to-end. Record the run URL and PASS/FAIL for each of the 5 ROADMAP
Phase 7 success criteria here once verified._

<!-- Verification section appended by the operator during Plan 05 Task 2. -->