# PKM Engine — Phase Progress Tracker

Tracks phase-by-phase progress toward the Phase 8 MVP gate.
Updated at the end of each phase. See DECISIONS.md for logged choices.

---

## Phase Progress

| Phase | Status | DoD met | Notes |
|-------|--------|---------|-------|
| Phase 1: Data Layer + Idempotency | Complete ✓ | Yes | 5/5 tests passing; immutability trigger, schema auto-migrate, LLM cache verified |
| Phase 2: Core Agents | Complete ✓ | Yes | 22/22 tests passing; ReaderAgent, SummarizerAgent, ConceptExtractor, KGAgent all complete |
| Phase 3: Pipeline + Vault Writer + CLI | In Progress | — | Wave 1 executing (03-01 vault scaffold) |
| Phase 4: GitHub Actions Orchestration | Not started | — | Requires Phase 3 complete; also needs VAULT_PAT + CF credentials (see Open Items in STATE.md) |
| Phase 5: Capture Worker | Not started | — | |
| Phase 6: Embeddings + Vector + Query Worker | Not started | — | |
| Phase 7: Scheduled Jobs + Guardrails | Not started | — | |
| Phase 8: Hardening + MVP Gate | Not started | — | Stop here; do NOT start V1 autonomously |

---

## Cost Actuals

> To be filled at the Phase 8 MVP gate per MVP-06.

| Item | Target | Actual |
|------|--------|--------|
| Infrastructure (recurring) | $0/mo | — |
| GitHub Actions minutes | $0 (public repo = unlimited) | — |
| Cloudflare Workers | $0 (free tier) | — |
| Turso | $0 (free tier) | — |
| Claude API (pipeline) | TBD $/mo (capped) | — |

---

## Phase 1 DoD Evidence (2026-06-15)

- `pytest tests/test_idempotency.py`: 5 passed, 0 failed, 0 warnings
- raw_path immutability trigger fires on UPDATE
- auto-migration on empty DB (all 11 tables + FTS5 + graph tables)
- content_hash dedup via UNIQUE constraint
- LLM cache: 1 API call, 1 agent_runs row after 2 identical call() invocations

## Phase 2 DoD Evidence (2026-06-15)

- `pytest tests/test_agents.py`: 22 passed, 0 failed, 0 warnings
- AGNT-01 through AGNT-06 requirements verified
- All 4 BaseAgent subclasses complete: ReaderAgent, SummarizerAgent, ConceptExtractor, KGAgent
