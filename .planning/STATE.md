---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: milestone
status: executing
last_updated: "2026-06-21T10:12:50.000Z"
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 13
  completed_plans: 12
  percent: 38
---

# Project State: AI-Assisted PKM System

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-15)

**Core value:** Clipping a source anywhere produces a synthesized, linked, cited wiki page with zero local daemon and zero infrastructure cost.
**Current focus:** Phase 8 — Hardening + MVP Gate (**STOP here; do NOT start V1 autonomously**)

> **Note (2026-06-21):** This file had fallen behind reality. Phases 3–6 were completed on the remote but STATE.md was not updated at the time. Reconciled against `PROGRESS.md` (the fresher record) and the live `pkm-vault` output. Phase-by-phase evidence lives in `PROGRESS.md` and `docs/PHASE{N}_VERIFICATION.md`; `DECISIONS.md` holds the logged choices. This STATE.md is the GSD status summary only.

## Current Phase

**Phase 7: Scheduled Jobs + Guardrails — COMPLETE ✓ (2026-06-21)**

Plans 01–04 executed autonomously (YOLO) on 2026-06-21. `pytest` → 134 passed (+34 new):

- 07-01: `pkm/lint.py` (broken wikilinks, orphans, missing provenance) + 13 tests — GUARD-01
- 07-02: migration 003 + counter helpers wired into insert paths + `pkm/dashboard.py` + 16 tests — GUARD-02/03
- 07-03: `backfill_embeds` + `pkm lint`/`pkm dashboard`/`pkm backfill-embeds` CLI + 5 tests — GUARD-01/02
- 07-04: `ingest.yml` +7 nightly steps (backfill, lint, actions-minutes, dashboard, 80% alert, guardrail commit, backup push) + `docs/GUARDRAILS.md` — GUARD-06/07

**Plan 07-05 (autonomous:false) — COMPLETE ✓ (2026-06-21):** operator performed the
external console configurations (GUARD-04 GH spending limit $0; GUARD-05 OpenAI
monthly hard limit; GUARD-07 second remote `rohitgupta1686/pkm-vault-backup` +
scoped PAT + `BACKUP_REMOTE_URL` secret; deferred `CF_ACCOUNT_ID`/`CF_API_TOKEN`
GH secrets). Claude verified end-to-end via `workflow_dispatch` run
[27901063045](https://github.com/rohitgupta1686/pkm-engine/actions/runs/27901063045)
— all 5 ROADMAP Phase 7 success criteria PASS. Two backup-push bugs found and
fixed during verification (checkout `extraheader` override → 403; shallow
`fetch-depth:1` → index-pack fail). See `docs/GUARDRAILS.md` Verification
section and `.planning/phases/07-scheduled-jobs-guardrails/07-05-SUMMARY.md`.

**Known follow-up (carry into Phase 8):** dashboard `Sources/Claims/Concepts`
counters read 0 — `dashboard_counters` rows only bump on new inserts, so
pre-Phase-7 data (~160 claims) was never counted. One-time counter backfill
needed. Lint orphan/missing-provenance counts are correct (query live tables).

### Prior: Phase 6 — Embeddings + Vector + Query Worker — COMPLETE ✓ (Wave 1–3)

- `pkm/retrieval/embed.py`: Workers AI REST + Vectorize NDJSON upsert, idempotent
- `worker-query.js`: embed → search → Turso → OpenAI synthesis, X-PKM-Key auth
- `pytest`: 100 passed (incl. 14 new embed tests); `npm run test:query`: 19 query-worker tests
- B-05-02 stuck-source bug fixed in run_ingest (wiki_path IS NOT NULL guard)
- **Wave 3 (live CF deploy) COMPLETE ✓ (2026-06-21)**: Vectorize index `pkm-claims` created + 160 claims embedded; query worker deployed to `https://pkm-query.rohitgupta-iitr.workers.dev` with 4 secrets; end-to-end `/query` returns cited synthesis. Fixes: `max_tokens`→`max_completion_tokens`; worker `TURSO_URL` must be HTTPS form. **Deferred:** CI ingest still lacks CF creds (`CF_ACCOUNT_ID`/`CF_API_TOKEN` GH secrets) so future CI ingests skip embed — carry into Phase 7. See `PROGRESS.md` Phase 6 section.

**Prior phases — all COMPLETE ✓** (see Phase History below and `PROGRESS.md` for DoD evidence).

## Phase History

| Phase | Status | Completed |
|-------|--------|-----------|
| Phase 1: Data Layer + Idempotency | Complete ✓ | 2026-06-15 |
| Phase 2: Core Agents | Complete ✓ | 2026-06-15 |
| Phase 3: Pipeline + Vault Writer + CLI | Complete ✓ | 2026-06-16 |
| Phase 4: GitHub Actions Orchestration | Complete ✓ | 2026-06-16 |
| Phase 5: Capture Worker | Complete ✓ | 2026-06-17 |
| Phase 6: Embeddings + Vector + Query Worker | Code complete ✓ (Wave 1–2; Wave 3 = live CF deploy pending operator) | 2026-06-21 |
| Phase 7: Scheduled Jobs + Guardrails | Complete ✓ | 2026-06-21 |
| Phase 8: Hardening + MVP Gate | Not started — **next; stop here; do NOT start V1 autonomously** | — |

## Open Items

- Prerequisites checklist (see KICKOFF.md) — confirmed via live Phase 4/5 runs and code inspection (2026-06-21):
  - [x] pkm-engine (public GitHub repo) created — https://github.com/rohitgupta1686/pkm-engine
  - [x] pkm-vault (private GitHub repo) created — https://github.com/rohitgupta1686/pkm-vault
  - [x] LLM API key + per-run spend cap set — **note: backend swapped Anthropic → OpenAI** (04-04); key is now `OPENAI_API_KEY`, cap enforced via `PKM_RUN_COST_CAP_USD` / `PKM_RUN_TOKEN_CAP`. The old `ANTHROPIC_API_KEY` checklist item is stale.
  - [x] Turso account + TURSO_URL + TURSO_TOKEN (used by pipeline + query worker)
  - [x] VAULT_PAT (fine-grained PAT, contents:write on pkm-vault only) — confirmed in Phase 4 verification
  - [x] GitHub Actions spending limit = $0 (public repo = unlimited free minutes)
  - [x] Cloudflare account + CF_ACCOUNT_ID + scoped API token — worker-clip.js deployed & verified in Phase 5
- ~~Phase 6 Wave 3 outstanding~~ → **COMPLETE (2026-06-21)**. Live deploy + end-to-end query verified. Remaining: add `CF_ACCOUNT_ID` + scoped `CF_API_TOKEN` as GitHub Actions secrets so CI ingest auto-embeds new sources (deferred to Phase 7); see `PROGRESS.md` Phase 6 section.

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
