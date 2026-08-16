# PKM Engine — Current State

One page, kept current. History lives in git, `DECISIONS.md`, and
`docs/legacy/` (including the retired 8-phase tracker,
`docs/legacy/PROGRESS-phases-2026-06.md` — historical only).

## What runs today (2026-08)

| Piece | Status | Where |
|---|---|---|
| Clip capture (bookmarklet → Worker → `raw/` commit + dispatch) | Live | `worker-clip.js`, Cloudflare |
| Per-clip + nightly ingest (one GLM-5.2 call → `notes/<slug>.md`) | Live | `.github/workflows/ingest.yml` |
| Weekly digest (Sundays 04:00 UTC) | Live | `.github/workflows/digest.yml` |
| Book/podcast source-notes (Mac-run, iCloud folder, optional `--ocr`) | Live, manual | `pkm ingest-notes` |
| Vault lint (broken `[[wikilinks]]` + review backlog, warn-only in CI) | Live | `pkm lint`, wired into ingest.yml |
| Tests in CI (offline suite, fake LLM clients) | Live | `.github/workflows/tests.yml` |
| Vault backup mirror (force-push after ingest) | Live | `pkm-vault-backup` |
| Advisor layer v2 (Profile + advice/ channels, Claude-subscription runs) | Scaffolded | `pkm-vault: .claude/skills/advisor/` |

## Costs

$0 infrastructure (Cloudflare + GitHub free tiers). LLM spend ≈ $1–2/month on
Z.AI GLM-5.2 at ~90 clips/month (measured 2026-08). Caps: `RUN_COST_CAP_USD`
(default $0.50/run) enforced in `pkm/batch.py`-descended paths.

## Retired (June 2026 redesign — do not resurrect)

Turso, Vectorize, the 4-agent chain, atomic claims/concepts, the query worker,
and the DB-backed lint/dashboard. Rationale: `DECISIONS.md` (2026-06-23);
teardown: `docs/legacy/LEGACY_RETIREMENT_PLAN.md`.

## Known follow-ups

- Notes-count dashboard against `notes/` (lint now covers links + backlog).
- `pkm_id` frontmatter anchor for `ingest-notes` rename-proofing.
- Prompt nit: callout bullets occasionally missing `> ` prefix inside
  `[!question]` blocks.
- Advisor v2: fill `Profile.md`, schedule weekly runs after first attended run.
