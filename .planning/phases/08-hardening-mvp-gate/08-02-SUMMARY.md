---
phase: 08-hardening-mvp-gate
plan: 02
subsystem: infra
tags: [cost-actuals, mvp-06, tier-1-review, decisions, state-reconcile, turso]

requires:
  - phase: 08-hardening-mvp-gate
    provides: (08-01) test-suite + lint evidence baseline
  - phase: 07-scheduled-jobs-guardrails
    provides: GUARDRAILS.md authoritative CF-creds record (lines 151-152, 195-196)
provides:
  - PROGRESS.md Cost Actuals table filled (MVP-06)
  - DECISIONS.md "Phase 8 MVP-gate review" section (T1-01/T1-02 dispositions + T2-05-04 carried)
  - STATE.md CF-creds status reconciled to CLOSED
affects: [08-03, mvp-gate]

tech-stack:
  added: []
  patterns: [derive cost actuals from real agent_runs.cost_usd SUM, not estimates]

key-files:
  created: []
  modified: [PROGRESS.md, DECISIONS.md, .planning/STATE.md]

key-decisions:
  - "MVP-06 OpenAI $/mo derived from live `SELECT SUM(cost_usd) FROM agent_runs` ($0.353260 / 197,154 tokens / 40 rows, June 2026) — not an estimate."
  - "T1-02 condition 2 verified load-bearing: client.py:352 compute_cost + pricing.py:40 KeyError-on-unknown (never 0.0) — the costs are real and non-zero."
  - "STATE.md CF-creds gap reconciled to CLOSED per GUARDRAILS.md (was stale 'deferred to Phase 7' / 'still lacks CF creds' in 3 places)."
  - "No new Type-1 decision locked; T2-05-04 drop-FK deferral listed as 'carried to MVP review' (human decides at checkpoint)."

patterns-established:
  - "Tier-1 gate review records dispositions + condition verification with file:line evidence; never 'locked' language."

requirements-completed: [MVP-06]

duration: 20min
completed: 2026-06-21
---

# Phase 8 Plan 08-02: Cost actuals (MVP-06) + Tier-1 batch review + STATE.md CF-creds reconcile

**Records real cost actuals, finalizes the Tier-1 batch review, and makes gate evidence self-consistent across STATE.md and GUARDRAILS.md.**

## Performance
- **Duration:** ~20 min
- **Completed:** 2026-06-21
- **Tasks:** 3
- **Files modified:** 3 docs

## Accomplishments
- MVP-06 PASS: PROGRESS.md Cost Actuals filled — 4 infra rows $0 + OpenAI $0.35/mo (June 2026: $0.353260 / 197,154 tokens / 40 agent_runs rows from live `SUM(cost_usd)`); per-run cap $0.50 + monthly hard limit referenced. No TBD/— cells remain.
- DECISIONS.md "Phase 8 MVP-gate review": T1-01 reaffirm (Vectorize live, load-bearing); T1-02 all 3 conditions PASS with file:line evidence (ingest.yml:20, client.py:352, client.py:168-174); T2-05-04 carried to MVP review (not locked).
- STATE.md CF-creds reconciled to CLOSED (2026-06-21, GUARDRAILS cited); stale "deferred to Phase 7" / "still lacks CF creds" wording removed (both now 0).

## Task Commits
1. **Task 2 + 3: DECISIONS Tier-1 review + STATE CF-creds reconcile** — `a664ef8` (docs)
2. **Task 1: PROGRESS.md Cost Actuals (MVP-06)** — `561f77d` (docs)

(Task 1 was performed after Tasks 2-3 because the cost query needed a runtime-minted Turso token; both committed atomically per task.)

## Decisions Made
- T1-02's three locked conditions verified at the current file:line (the lock text cited stale `client.py:220`/`client.py:27-29` lines; current code is client.py:352 / 168-174).
- Cost query used a `turso db tokens create pkm`-minted token at runtime (Turso CLI authed) — no `.env` needed.

## Deviations from Plan
None — plan executed as written. Task ordering within the plan was Tasks 2-3 then Task 1 (token-minting sequencing); all three tasks complete.

## Issues Encountered
None. (Pre-existing PROGRESS.md references secret *names* like `PKM_KEY`/`OPENAI_API_KEY` in the Phase 6 "secrets set" documentation — these are names, not values; no secret values committed. The Cost Actuals section itself is clean.)

## Next Phase Readiness
MVP-06 evidence + Tier-1 dispositions + reconciled STATE.md ready for the 08-MVP-REVIEW brief. Ready for 08-03.