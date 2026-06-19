---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: milestone
status: executing
last_updated: "2026-06-19T11:09:12.971Z"
progress:
  total_phases: 8
  completed_phases: 2
  total_plans: 7
  completed_plans: 7
  percent: 25
---

# Project State: AI-Assisted PKM System

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-15)

**Core value:** Clipping a source anywhere produces a synthesized, linked, cited wiki page with zero local daemon and zero infrastructure cost.
**Current focus:** Phase 3 — Pipeline + Vault Writer + CLI

## Current Phase

**Phase 2: Core Agents — COMPLETE ✓**

Plans: 4 plans in 2 waves

- Wave 1: 02-01 BaseAgent ABC + prompts — COMPLETE ✓
- Wave 2: 02-02 ReaderAgent — COMPLETE ✓, 02-03 Summarizer+Extractor — COMPLETE ✓, 02-04 KGAgent+graph — COMPLETE ✓

**Phase 1: Data Layer + Idempotency — COMPLETE ✓**

DoD verified (2026-06-15):

- `pytest tests/test_idempotency.py`: 5 passed, 0 failed, 0 warnings
- raw_path immutability trigger fires on UPDATE ✓
- auto-migration on empty DB (all 11 tables + FTS5 + graph tables) ✓
- content_hash dedup via UNIQUE constraint ✓
- LLM cache: 1 API call, 1 agent_runs row after 2 identical call() invocations ✓

## Phase History

| Phase | Status | Completed |
|-------|--------|-----------|
| Phase 1: Data Layer + Idempotency | Complete ✓ | 2026-06-15 |
| Phase 2: Core Agents | Complete ✓ | 2026-06-15 |
| Phase 3: Pipeline + Vault Writer + CLI | Not started | — |
| Phase 4: GitHub Actions Orchestration | Not started | — |
| Phase 5: Capture Worker | Not started | — |
| Phase 6: Embeddings + Vector + Query Worker | Not started | — |
| Phase 7: Scheduled Jobs + Guardrails | Not started | — |
| Phase 8: Hardening + MVP Gate | Not started | — |

## Open Items

- Prerequisites checklist (see KICKOFF.md) must be confirmed before Phase 4 can complete:
  - [x] pkm-engine (public GitHub repo) created — https://github.com/rohitgupta1686/pkm-engine
  - [x] pkm-vault (private GitHub repo) created — https://github.com/rohitgupta1686/pkm-vault
  - [ ] ANTHROPIC_API_KEY + monthly spend cap set
  - [ ] Turso account + TURSO_URL + TURSO_TOKEN
  - [ ] VAULT_PAT (fine-grained PAT, contents:write on pkm-vault only)
  - [ ] GitHub Actions spending limit = $0
  - [ ] Cloudflare account + CF_ACCOUNT_ID + scoped API token

## Phase 1 Decisions (Wave 1)

- setuptools package discovery scoped to `pkm*` only (migrations/ dir caused flat-layout error)
- `libsql_experimental.execute()` only runs first SQL statement — all migration runners must use `executescript()`
- `anthropic_api_key` has empty string default in Settings for test-context compatibility

## Phase 1 Decisions (Wave 2)

- INSERT OR REPLACE (not INSERT OR IGNORE) in _write_run: ensures ok-row overwrites prior error-row for same (agent, input_hash)
- LLMClient uses tool-calling (tools=[]+tool_choice) when output_schema provided — JSON schema enforcement at API level
- LLMClient takes explicit conn + api_key — no Settings singleton inside client for testability
- Migrations dir resolved via Path(__file__) so it works regardless of cwd (tests use os.chdir)

## Phase 2 Decisions (Wave 2 — 02-04)

- Tier 3 embedding resolution stubbed (logs debug, returns None) per AD-5 MVP constraint — no Opus call, no API spend
- resolver.py SQL uses parameterized ? placeholders throughout (T-02-08 mitigation)
- noisy_or() is a pure function with no DB dependency — enables isolated unit testing
- All 4 BaseAgent subclasses now complete: ReaderAgent, SummarizerAgent, ConceptExtractor, KGAgent

## Phase 2 Decisions (Wave 2 — 02-03)

- chunk_id="null" string convention tested as data contract: confidence <= 0.5 enforced in test_summarizer_chunk_id_rule (not Python None; the string "null" is the sentinel value)
- repair-retry test patches pkm.llm.client.anthropic.Anthropic and re-creates LLMClient inside the patch context — cannot patch after __init__ because self.client is bound at construction time
- ConceptMatch.claim_indices is list[int] — pydantic rejects string indices at validation gate (mitigates T-02-05)

## Phase 2 Decisions (Wave 2 — 02-02)

- output_schema=None on ReaderAgent: Reader returns plain string, not pydantic; LLMClient returns result["result"] as str when output_schema is None
- build_mock_llm_client writes real agent_runs rows: mock simulates LLMClient.call() exactly including DB write so downstream SQL assertions work without real API calls
- Placeholder test classes for plans 03-04 added in test_agents.py now: those plans extend this module

## Phase 2 Decisions (Wave 1 — 02-01)

- BaseAgent uses __init_subclass__ (not @abstractmethod) for ClassVar enforcement — ClassVars cannot be abstract methods; __init_subclass__ fires at class-definition time giving immediate TypeError
- No LLMClient import in pkm.agents.base — client injected via run() arg to avoid coupling and enable MagicMock testing
- chunk_id uses positional IDs (para_1, para_2) when source lacks explicit markers; string "null" reserved for untraceable claims with confidence <= 0.5

## Tier-1 Decisions (batched for MVP gate review)

- Vectorize chosen over Turso native vectors (default per cloud doc §7.2) — log in DECISIONS.md

## Notes

- This project uses YOLO mode — execute autonomously, surface only Mode C triggers
- Mode C triggers: $0 goal breaks, Claude cost exceeds cap, spec infeasible, irreversible decision undocumented, trust/blast-radius issue, genuine scope expansion
- Stop at Phase 8 MVP gate; do NOT start V1 autonomously

---
*Initialized: 2026-06-15*
