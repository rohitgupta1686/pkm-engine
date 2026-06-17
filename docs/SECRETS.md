# PKM Engine — Repository Secrets Setup

This document lists the secrets required by the `ingest.yml` GitHub Actions workflow
and how to set them up with least privilege.

## Required Repository Secrets

Add these secrets to the **pkm-engine** repository:
`github.com/rohitgupta1686/pkm-engine` → Settings → Secrets and variables → Actions

| Secret | Source | Purpose |
|--------|--------|---------|
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) → API keys | Claude API calls during ingest |
| `TURSO_URL` | [Turso dashboard](https://turso.tech/) → database → URL (e.g., `libsql://your-db.turso.io`) | Turso libSQL connection URL |
| `TURSO_TOKEN` | [Turso dashboard](https://turso.tech/) → database → create token | Turso auth token |
| `VAULT_PAT` | GitHub → Settings → Developer settings → Fine-grained tokens (see below) | Cross-repo checkout + commit-back to pkm-vault |

## VAULT_PAT — Scope and Permissions

The `VAULT_PAT` is a **fine-grained personal access token** with the following configuration:

- **Token type:** Fine-grained (not classic PAT)
- **Repository access:** Only `pkm-vault` (select "Only select repositories" and pick `rohitgupta1686/pkm-vault`)
- **Permissions:** Contents: **Read and write** — nothing else
- **Expiration:** Set a reasonable expiry (e.g., 90 days) and rotate before it lapses

**Why VAULT_PAT exists:** The default `GITHUB_TOKEN` in a workflow run is scoped to the repository where the workflow runs (`pkm-engine`). It **cannot** push commits to a different repository (`pkm-vault`). The fine-grained PAT bridges this gap with minimal scope.

**Least privilege:** The PAT is scoped to a single private repo with only `contents:read+write`. No admin, no issues, no packages, no other repositories.

## GitHub Actions Spending Limit

Set the GitHub Actions spending limit to **$0** (fail-closed):

1. Go to `github.com/rohitgupta1686/pkm-engine` → Settings → Billing and plans → Spending limits
2. Set the Actions spending limit to `$0`

This ensures that if free-tier minutes are exhausted, runs fail rather than incurring charges.

Also set a **monthly spend cap on the Anthropic API key** in the [Anthropic Console](https://console.anthropic.com/) → Settings → Billing → Monthly spend limit. This prevents runaway API costs.

## Manual Test

After configuring secrets, trigger a workflow run manually:

**Option A — GitHub UI:**
1. Go to `github.com/rohitgupta1686/pkm-engine` → Actions → ingest
2. Click "Run workflow"

**Option B — GitHub CLI:**
```bash
gh api repos/rohitgupta1686/pkm-engine/dispatches -f event_type=ingest
```

After the run completes, check `pkm-vault` for a commit from `pkm-bot` with message
`synthesize: <timestamp>`. If the vault had no new raw files, the commit step is
a clean no-op (empty diff → no commit pushed) — this confirms ORCH-07 idempotency.