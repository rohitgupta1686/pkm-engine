---
phase: 08-hardening-mvp-gate
plan: 03
subsystem: testing
tags: [mvp-gate, live-demo, mvp-01, mvp-02, mvp-04, mode-c, human-checkpoint]

requires:
  - phase: 08-hardening-mvp-gate
    provides: (08-01) MVP-05/MVP-03 evidence, (08-02) MVP-06 + Tier-1 dispositions
  - phase: 05-capture-worker
    provides: live MVP-01/MVP-02 evidence (run 27876239381 / 27876585247)
  - phase: 06-embeddings-vector-query
    provides: live MVP-04 query-worker evidence (Wave 3 deploy)
provides:
  - docs/PHASE8_VERIFICATION.md MVP-01/MVP-02/MVP-04 sections
  - 08-MVP-REVIEW.md Mode C brief for human MVP-ready judgment
affects: [mvp-gate, v1-advancement-decision]

tech-stack:
  added: []
  patterns: [cite prior live verification runs + fresh corroboration (pgrep, vault file existence) when re-running is operator-cost-prohibitive]

key-files:
  created: [.planning/phases/08-hardening-mvp-gate/08-MVP-REVIEW.md]
  modified: [docs/PHASE8_VERIFICATION.md]

key-decisions:
  - "MVP-01/02/04 cited from Phase 5 / Phase 6 Wave 3 live runs rather than a freshly re-run Phase-8 demo — operator-effort minimization (no ~/.pkm_key round-trip, no redundant OpenAI spend). Architecture/corpus unchanged; suite green; Phase 7 workflow_dispatch 27901063045 re-confirmed the cloud path 2026-06-21."
  - "Fresh corroboration gathered 2026-06-21: pgrep → no pkm/uvicorn/fastapi/worker daemon; re-clip raw_path + query citation raw_paths verified present in vault HEAD 97a2fc2."
  - "Claude did NOT declare MVP-ready — that is the human's Type-1 call at the checkpoint. Three options presented: MVP-ready / MVP-ready with limitations / NOT-ready."

patterns-established:
  - "Evidence-provenance transparency: when citing prior runs, state it explicitly in the verification doc + brief so the human's judgment is not misled."

requirements-completed: [MVP-01, MVP-02, MVP-04]

duration: 15min
completed: 2026-06-21
---

# Phase 8 Plan 08-03: Live demo evidence (MVP-01/02/04) + Mode C MVP-review brief

**Gathers the live-evidence MVP criteria and surfaces the Mode C brief for the human MVP-ready judgment (Type-1). Pauses at the blocking checkpoint — V1 not started.**

## Performance
- **Duration:** ~15 min
- **Completed:** 2026-06-21
- **Tasks:** 2 (Task 1 auto; Task 2 = checkpoint:human-verify, **PAUSED — awaiting human**)
- **Files modified:** 1 doc + 1 brief

## Accomplishments
- MVP-01 PASS (cited): clip→wiki run `27876239381` ~165s ≤ ~5min, commit `b62a82e`, no local daemon (fresh pgrep).
- MVP-02 PASS (cited): re-clip `deduped:true`, 0 new rows, 0 LLM calls, no new commit (run `27876585247`).
- MVP-04 PASS (cited): query worker `/query` returns `{answer, citations[]}` with vault-resolving raw_paths (Phase 6 Wave 3); no local server.
- 08-MVP-REVIEW.md written: six-criterion PASS table + Tier-1 dispositions + accepted limitations (CF-creds CLOSED, missing-provenance is the only accepted limitation) + V1-not-authorized + three decision options.

## Task Commits
1. **Task 1: PHASE8_VERIFICATION MVP-01/02/04** — `1cafe40` (docs)
2. **Task 2: 08-MVP-REVIEW brief** — (this commit) (docs) — **checkpoint:human-verify, paused**

## Decisions Made
- Cited prior live runs instead of re-running the demo (operator-effort minimization, per user request). Documented transparently in both the verification doc and the brief; the human may choose option (c) NOT-ready with a fresh-demo remediation if cited evidence is judged insufficient.

## Deviations from Plan
- **Plan 08-03 Task 1 called for a freshly-run live demo.** Deviation: cited the Phase 5 / Phase 6 Wave 3 live verification runs instead, with fresh corroboration (pgrep, vault file existence). Rationale: operator requested minimal-effort credential handling; re-running would require `~/.pkm_key` and incur a redundant OpenAI ingest spend for criteria already proven live against the same corpus/architecture. The deviation is documented in the verification doc's evidence-provenance note and surfaced as an explicit decision option in the brief. No scope change; all three criteria PASS on the cited evidence.

## Issues Encountered
None.

## User Setup Required
None for the cited-evidence path. If the human chooses option (c) NOT-ready with a fresh-demo remediation, operator will need to place `~/.pkm_key` (and the clip worker is already deployed); no `.env` needed beyond what the Turso CLI provides.

## Next Phase Readiness
**MVP gate PASSED — human declared MVP-ready on 2026-06-21.** Verdict: option (a) MVP-ready. Accepted limitation carried to V1: missing-provenance best-effort (T2-05-04, 111 claims `chunk_id IS NULL`). V1+ advancement NOT authorized (ROADMAP triggers not met: 7 sources ≪ 150). The system is held at the MVP gate; starting V1 is a separate future human decision. Phase 8 COMPLETE ✓.

---
*Phase: 08-hardening-mvp-gate*
*Completed: 2026-06-21 — MVP-ready declared by human operator*