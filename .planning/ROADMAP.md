# Roadmap: AI-Assisted PKM System (Cloud MVP)

**Phases:** 8 | **Requirements:** 44 | **Target:** MVP gate at Phase 8

---

## Overview

| # | Phase | Goal | Requirements | Est. Effort |
|---|-------|------|--------------|-------------|
| 1 | Data Layer + Idempotency | Turso schema + LLM cache + pydantic models | DATA-01–09 | 0.5 day |
| 2 | Core Agents | 4/4 | Complete ✓ | 2026-06-15 |
| 3 | Pipeline + Vault Writer + CLI | End-to-end ingest: raw → wiki pages | PIPE-01–06 | 1.5 days |
| 4 | GitHub Actions Orchestration | Automated ingest workflow in pkm-engine | ORCH-01–07 | 0.5 day |
| 5 | Capture Worker | Cloudflare Worker: clip → raw → dispatch | CLIP-01–06 | 0.5 day |
| 6 | Embeddings + Vector + Query Worker | Semantic search and edge query endpoint | QURY-01–04 | 1 day |
| 7 | Scheduled Jobs + Guardrails | Nightly lint, dashboard, spend caps, backup | GUARD-01–07 | 0.5 day |
| 8 | Hardening + MVP Gate | Full test suite + cost actuals + MVP review | MVP-01–06 | 0.5 day |

---

### Phase 1: Data Layer + Idempotency

**Goal:** Turso schema running, pydantic models defined, LLM hash-cache implemented, raw-immutability enforced, idempotency test green.
**Mode:** standard

**Files to create:**
- `pyproject.toml`, `.env.example`, `README.md`
- `pkm/config.py` — pydantic-settings
- `pkm/store/registry.py` — libSQL connection + CRUD + recursive-CTE traversal
- `migrations/sqlite/001_init.sql` — full schema (sources, chunks, summaries, claims, concepts, concept_aliases, claim_concepts, entities, entity_aliases, agent_runs, embeddings_meta, claims_fts FTS5)
- `migrations/sqlite/002_graph_tables.sql` — graph_nodes, graph_edges
- `pkm/schemas/` — source.py, claim.py, concept.py, entity.py, graph.py, agent_io.py
- `pkm/llm/models.py` — HAIKU, SONNET, OPUS model string constants
- `pkm/llm/client.py` — Claude API wrapper: structured output, retries, agent_runs write, hash cache
- `tests/test_idempotency.py`
- `tests/fixtures/` — sample raw file

**Success Criteria:**
1. `test_idempotency.py` green: re-ingesting same content = 0 LLM calls, 0 new rows
2. Raw-immutability trigger fires on any UPDATE to sources.raw_path
3. Running `pkm` against empty DB auto-migrates schema on startup
4. libSQL connection works against both Turso cloud URL and local SQLite file

---

### Phase 2: Core Agents

**Goal:** All four MVP agents (Reader, Summarizer, Concept Extractor, KG Agent) pass golden-fixture tests with pydantic-validated structured output.
**Mode:** standard

**Plans:** 4/4 plans executed

Plans:
- [x] 02-01-PLAN.md — BaseAgent ABC + 3 prompt files (wave 1)
- [x] 02-02-PLAN.md — ReaderAgent + golden-fixture test infrastructure (wave 2)
- [x] 02-03-PLAN.md — SummarizerAgent + ConceptExtractor + repair-retry test (wave 2)
- [x] 02-04-PLAN.md — KGAgent + graph/resolver.py + graph/confidence.py + resolver tests (wave 2)

**Files to create:**
- `pkm/agents/base.py` — BaseAgent ABC with schema validation + repair-retry
- `pkm/agents/reader_agent.py` — Haiku, raw → raw/*.md front matter
- `pkm/agents/summarizer_agent.py` — Sonnet, → SummarizerOutput
- `pkm/agents/concept_extractor.py` — Sonnet, → claims + concept_matches
- `pkm/agents/kg_agent.py` — Sonnet, → KGAgentOutput (nodes, relationships)
- `pkm/prompts/summarize.v1.md`, `extract_claims.v1.md`, `er_extraction.v1.md`, `reader.v1.md`
- `pkm/graph/resolver.py` — three-tier: exact → alias → (embedding tier stubbed)
- `pkm/graph/confidence.py` — noisy-OR: s' = 1 − (1−s_old)·(1−s_new)
- `tests/test_agents.py` — golden-fixture tests per agent
- `tests/test_resolver.py` — resolver unit tests

**Success Criteria:**
1. Each agent passes golden-fixture test independently
2. Every claim has chunk_id (provenance) or null + confidence ≤ 0.5
3. Schema-invalid LLM response triggers repair-retry; valid response passes
4. All agent calls write tokens_in, tokens_out, cost_usd to agent_runs

---

### Phase 3: Pipeline + Vault Writer + CLI

**Goal:** `pkm ingest --new-only` runs end-to-end: fixture article → source wiki page + ≥1 concept wiki page + claim rows; re-run is a no-op.
**Mode:** standard

**Files to create (pkm-engine):**
- `pkm/pipeline/ingest.py` — sequential coordinator
- `pkm/store/vault.py` — idempotent wiki page upsert with [[wikilinks]] + ^cite: anchors
- `pkm/cli.py` — `pkm ingest --new-only`
- `tests/test_ingest_e2e.py`

**Files to create (pkm-vault):**
- `SCHEMA.md` — ontology, page rules, tag vocab, edge types, status enums
- `index.md`, `log.md`
- `wiki/` subdirectory structure (all 13 types)
- `_templates/` — Article Note, Concept Note, Decision Log
- `PROGRESS.md`, `DECISIONS.md`

**Success Criteria:**
1. `test_ingest_e2e.py` green: fixture → source page + ≥1 concept page + claim rows (status=pending_review)
2. Re-running ingest on same fixture = no new files, no new DB rows, 0 LLM calls
3. Every wiki claim has ^cite:<source_id>#<chunk_id> anchor pointing to raw/ span
4. log.md gets one new line appended per ingest run

---

### Phase 4: GitHub Actions Orchestration

**Goal:** Pushing to pkm-vault/raw/ (via dispatch) triggers ingest workflow in pkm-engine; bot commits wiki pages back to vault; re-push is a no-op; concurrent triggers serialize.
**Mode:** standard

**Files to create (pkm-engine):**
- `.github/workflows/ingest.yml` — triggers: repository_dispatch + schedule cron; checkout vault with VAULT_PAT; run ingest; commit wiki/ + index.md + log.md back; concurrency serialization; timeout-minutes: 10

**Success Criteria:**
1. Firing repository_dispatch to pkm-engine triggers Actions run that writes wiki pages to pkm-vault
2. Bot commit appears in pkm-vault with synthesized pages
3. Re-dispatching same payload = no new commit (idempotency preserved end-to-end)
4. Two concurrent dispatch events queue (second waits for first, does not cancel)
5. Workflow completes in < 10 minutes

---

### Phase 5: Capture Worker

**Goal:** Clipping an article via bookmarklet/browser POST → immutable raw/ file in vault → Actions processing triggered end-to-end; Mac can be asleep.
**Mode:** standard

**Files to create (pkm-engine):**
- `worker-clip.js` — CF Worker: validate X-PKM-Key → optionally offload to R2 → commit raw/*.md to vault via GitHub API → fire repository_dispatch
- `wrangler.toml`
- Bookmarklet snippet + README clipper setup notes

**Success Criteria:**
1. POST to Worker with test article → raw/ file appears in pkm-vault within 5 seconds
2. Large text (>200K chars) offloads to R2; r2key appears in raw/ front matter
3. Request missing X-PKM-Key header returns 401
4. Chained Actions run completes: wiki pages committed to vault
5. Mac can be offline throughout (everything runs at edge/cloud)

---

### Phase 6: Embeddings + Vector + Query Worker

**Goal:** Ingest pipeline upserts claim embeddings to Vectorize; curl to /query?q= returns a cited answer; no local server involved.
**Mode:** standard

**Files to create (pkm-engine):**
- `pkm/retrieval/embed.py` — Workers AI bge-base-en-v1.5; batch embed; writes embeddings_meta to Turso
- Vectorize upsert integrated into `pkm/pipeline/ingest.py`
- `worker-query.js` — embed → Vectorize top-12 → Turso claims fetch → Claude Sonnet synthesis → {answer, citations}
- `wrangler.toml` updated for query Worker

**Success Criteria:**
1. After ingest, Vectorize index contains embeddings for ingested claims
2. `curl "$WORKER_URL/query?q=test+question"` returns JSON {answer, citations} within 5 seconds
3. Citations are valid raw/ paths that exist in pkm-vault
4. No local server process required for query to succeed
5. Daily embedding volume stays within Workers AI 10K/day free limit at current scale

---

### Phase 7: Scheduled Jobs + Guardrails

**Goal:** Nightly lint + dashboard run in Actions; $0 spend limits confirmed; backup push works; 80% Actions-minutes alert fires.
**Mode:** standard

**Files to create (pkm-engine):**
- `pkm/lint.py` — broken [[wikilinks]], orphans, missing ^cite: provenance; writes to log.md
- `pkm/dashboard.py` — generates dashboard.md with output counts, Actions-minutes, queue depths; uses counter rows (not COUNT(*) scans)
- `.github/workflows/ingest.yml` updated with lint + dashboard steps + 80% alert + backup push

**Success Criteria:**
1. Nightly cron run regenerates dashboard.md with current counts
2. Lint step writes any failures to log.md (empty = clean vault)
3. 80% Actions-minutes check runs and would write warning to log.md if triggered
4. GitHub Actions spending limit confirmed $0 (tested: would hard-stop not bill)
5. Backup push to second remote succeeds

---

### Phase 8: Hardening + MVP Gate

**Goal:** All acceptance criteria met; cost actuals recorded; MVP review surfaced.
**Mode:** standard

**Tasks:**
- Full test suite pass (DATA, AGNT, PIPE, ORCH, CLIP, QURY, GUARD)
- Record cost actuals in PROGRESS.md (infra $0, Claude $/mo via agent_runs)
- Confirm all hard constraints: zero local daemon, $0 infra, idempotent re-ingest, raw/ immutable, query at edge
- Document any Tier-1 batch items accumulated since Phase 1
- Surface MVP review (Mode C brief)

**Success Criteria:**
1. End-to-end demo: clip article via bookmarklet → wiki page with citations within ~5 min, Mac asleep
2. Re-clip same article → complete no-op (0 new rows, 0 LLM calls, no new commit)
3. Every wiki claim resolves to raw/ source span
4. Query Worker returns cited answer, no local server
5. Full test suite green
6. Cost actuals: infra $0, Claude cost ≤ cap

---

## Advancement Gates (Post-MVP)

| Trigger | Build |
|---------|-------|
| Corpus ≳150 sources OR long-context misses answers | **V1:** Chroma embeddings, 12 templates wired, hybrid BM25+vector retrieval, nightly lint hardening |
| Relational/multi-hop/"what's changing" questions recur | **V2:** Neo4j (ETL from graph_* tables), GraphRAG (Leiden + community summaries), Pattern + Contrarian agents |
| Want active opportunity/thesis generation | **V3:** Opportunity + Investment + Writing agents, coordinator orchestration, decision→outcome loop |

**Do not begin V1 autonomously — version progression is a human judgment call.**

---
*Roadmap created: 2026-06-15*
*Last updated: 2026-06-15 after Phase 2 planning*
