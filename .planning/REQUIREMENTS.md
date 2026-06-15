# Requirements: AI-Assisted PKM System (Cloud MVP)

**Defined:** 2026-06-15
**Core Value:** Clipping a source anywhere produces a synthesized, linked, cited wiki page with zero local daemon and zero infrastructure cost.

## v1 Requirements

Requirements for the MVP release. All 8 phases of the build plan are in scope.

### Data Layer

- [x] **DATA-01**: System stores source metadata (id, content_hash, type, title, author, url, raw_path, status) in Turso (libSQL)
- [x] **DATA-02**: System partitions raw text into deterministic TextUnit chunks (1200 tok) stored in Turso
- [x] **DATA-03**: System deduplicates ingested sources by content_hash (re-ingest = 0 new rows)
- [ ] **DATA-04**: System caches every LLM call by sha256(agent+model+prompt_version+input) — re-ingest = 0 LLM calls
- [x] **DATA-05**: raw/ files are immutable after write (DB trigger fires on update attempt)
- [x] **DATA-06**: Schema auto-migrates on startup from empty DB
- [x] **DATA-07**: System stores atomic claims (SPO, claim_type, confidence, provenance chunk_id) in Turso
- [x] **DATA-08**: System stores concept pages with aliases and claim-concept join table in Turso
- [x] **DATA-09**: System stores graph nodes and edges in Turso (SQLite property graph, bridge to V2 Neo4j)

### Agents

- [x] **AGNT-01**: Reader agent (Haiku) normalizes raw bytes/URL → clean Markdown + front matter
- [x] **AGNT-02**: Summarizer agent (Sonnet) produces thesis + key_claims[] + caveats[] with source spans and pydantic validation
- [x] **AGNT-03**: Concept Extractor (Sonnet) produces atomic SPO claims + concept matches; reads concept index
- [x] **AGNT-04**: KG Agent (Sonnet) produces graph nodes[] + relationships[] with entity resolution and provenance
- [x] **AGNT-05**: All agents validate output against pydantic schema with one repair-retry on schema-invalid response
- [x] **AGNT-06**: All agents write cost (tokens_in, tokens_out, cost_usd) to agent_runs table per call

### Pipeline & Vault

- [ ] **PIPE-01**: `pkm ingest --new-only` CLI command runs Reader → Summarizer → Extractor → KG Agent → vault writer sequentially
- [ ] **PIPE-02**: Vault writer idempotently upserts wiki/sources/*.md and wiki/concepts/*.md with [[wikilinks]] and ^cite: anchors
- [ ] **PIPE-03**: Vault writer appends to log.md after each successful ingest
- [ ] **PIPE-04**: Three-tier entity resolution: exact match → alias match → (embedding tier stubbed for MVP)
- [ ] **PIPE-05**: pkm-vault repo contains: SCHEMA.md, index.md, log.md, wiki/ subfolders, 3 MVP templates (Article Note, Concept Note, Decision Log)
- [ ] **PIPE-06**: PROGRESS.md and DECISIONS.md initialized in pkm-engine

### Orchestration (GitHub Actions)

- [ ] **ORCH-01**: ingest.yml workflow in pkm-engine triggers on repository_dispatch (type: ingest) — primary trigger
- [ ] **ORCH-02**: ingest.yml also triggers on nightly schedule cron (03:00 UTC) as catch-up
- [ ] **ORCH-03**: ingest.yml checks out pkm-vault using VAULT_PAT (fine-grained PAT, contents:write on vault only)
- [ ] **ORCH-04**: ingest.yml commits wiki/ + index.md + log.md + dashboard.md back to pkm-vault after ingest
- [ ] **ORCH-05**: ingest.yml uses concurrency serialization (cancel-in-progress: false) — runs queue, never cancel
- [ ] **ORCH-06**: ingest.yml has timeout-minutes: 10 to guard Actions budget
- [ ] **ORCH-07**: Re-pushing the same file to raw/ produces no new output (idempotency via hash cache)

### Capture Worker

- [ ] **CLIP-01**: Cloudflare Worker accepts POST {url, type, text, title} at /clip endpoint
- [ ] **CLIP-02**: Worker validates X-PKM-Key shared-secret header; rejects unauthorized requests
- [ ] **CLIP-03**: Worker offloads text > 200K chars to Cloudflare R2; stores r2key in raw/ front matter
- [ ] **CLIP-04**: Worker commits content-addressed raw/ file to pkm-vault via GitHub Contents API using VAULT_PAT
- [ ] **CLIP-05**: Worker fires repository_dispatch to pkm-engine (type: ingest) after commit
- [ ] **CLIP-06**: Bookmarklet / clipper config documented so clipping from browser requires only one click

### Embeddings & Query

- [ ] **QURY-01**: Ingest pipeline generates 768-dim bge-base-en-v1.5 embeddings via Cloudflare Workers AI
- [ ] **QURY-02**: Ingest pipeline upserts claim embeddings to Cloudflare Vectorize with metadata {source_id, concept_id}
- [ ] **QURY-03**: Cloudflare Worker at /query?q= embeds question, queries Vectorize top-12, fetches claims from Turso, calls Claude Sonnet for synthesis
- [ ] **QURY-04**: Query Worker returns {answer, citations: [raw_path...]} — no local server involved

### Scheduled Jobs & Guardrails

- [ ] **GUARD-01**: Nightly lint checks broken [[wikilinks]], orphan notes, claims missing chunk_id provenance; writes failures to log.md
- [ ] **GUARD-02**: Nightly dashboard regenerates dashboard.md with: sources ingested, wiki pages, claims, insights accepted, Actions-minutes used, orphan/stale counts
- [ ] **GUARD-03**: Dashboard uses incrementally-maintained counter rows in Turso (not full-table scans)
- [ ] **GUARD-04**: GitHub Actions spending limit confirmed $0 (fail-closed, no overage)
- [ ] **GUARD-05**: Anthropic monthly spend cap confirmed set in console
- [ ] **GUARD-06**: 80% Actions-minutes alert step in workflow writes warning to log.md
- [ ] **GUARD-07**: Second git remote configured; nightly backup push executes in workflow

### MVP Acceptance

- [ ] **MVP-01**: Clipping a source via bookmarklet → synthesized wiki page within ~5 minutes, Mac can be asleep
- [ ] **MVP-02**: Re-clipping the same source is a complete no-op (0 new rows, 0 LLM calls, no new commit)
- [ ] **MVP-03**: Every wiki claim resolves to a raw/ source span via ^cite: anchor
- [ ] **MVP-04**: curl "$WORKER_URL/query?q=..." returns a cited answer; no local server needed
- [ ] **MVP-05**: Full test suite green (idempotency, resolver, e2e, agent golden-files)
- [ ] **MVP-06**: Cost actuals recorded in PROGRESS.md (infra $0 target, Claude $/mo)

## v2 Requirements

Deferred — not in MVP roadmap. Advancement trigger: corpus ≥150 sources OR relational/multi-hop questions recur.

### Knowledge Graph (V2)

- **KG-01**: Neo4j graph database with ETL from SQLite graph_nodes/graph_edges tables
- **KG-02**: GraphRAG: Leiden community detection + bottom-up community summaries
- **KG-03**: Local and global GraphRAG query modes (entity-anchored + map-reduce)
- **KG-04**: Pattern Detection agent (Sonnet) — theme/trend/analogy clustering over graph
- **KG-05**: Contrarian agent (Opus) — NLI + LLM-judge contradiction detection queue

### Embeddings Full Path (V1 bridge)

- **EMB-01**: Chroma vector store as alternative to Vectorize for local-first development
- **EMB-02**: Hybrid BM25 + vector + graph fusion retrieval (Reciprocal-rank fusion)
- **EMB-03**: Turso embedded replica option for zero-latency reads in query Worker

## Out of Scope

| Feature | Reason |
|---------|--------|
| Opportunity agent | V3 — requires manufacturing/portfolio context profile |
| Investment Research agent | V3 — requires market data feeds |
| Writing agent | V3 — requires coordinator orchestration |
| n8n orchestration | Replaced by GitHub Actions at $0 |
| FastAPI local server | Replaced by Cloudflare Workers |
| Local daemon (any kind) | Hard architectural constraint — never allowed |
| Mobile app | Not part of PKM scope |
| Docker Compose stack | Cloud-native; no local containers in production path |
| Neo4j at MVP | Premature; SQLite graph tables bridge to V2 |
| Full 12 templates at MVP | Only 3 templates needed for MVP (Article, Concept, Decision Log) |
| Spaced repetition | V3+ |
| Contradiction queue UI | V2 — Contrarian agent handles this |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01–09 | Phase 1 | Pending |
| AGNT-01–06 | Phase 2 | Complete ✓ |
| PIPE-01–06 | Phase 3 | Pending |
| ORCH-01–07 | Phase 4 | Pending |
| CLIP-01–06 | Phase 5 | Pending |
| QURY-01–04 | Phase 6 | Pending |
| GUARD-01–07 | Phase 7 | Pending |
| MVP-01–06 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-15*
*Last updated: 2026-06-15 after initialization*
