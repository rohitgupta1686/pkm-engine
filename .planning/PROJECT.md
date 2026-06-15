# AI-Assisted PKM System (Cloud MVP)

## What This Is

A cloud-native, $0-infrastructure personal knowledge management system that turns any web clip, article, or note into a synthesized, linked, provenance-cited Markdown wiki page — automatically, while your Mac sleeps. The vault is plain Markdown in a private GitHub repo (durable forever); all compute runs on GitHub Actions + Cloudflare Workers; the only cost is capped Claude API tokens.

## Core Value

Clipping a source anywhere produces a synthesized, linked, cited wiki page with zero local daemon and zero infrastructure cost — defeating the Collector's Fallacy by automating the processing step.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Content-addressed raw/ capture (append-only, immutable, idempotent re-ingest)
- [ ] Turso (libSQL) metadata registry + claim/edge graph
- [ ] LLM call hash-cache (re-ingest = 0 LLM calls)
- [ ] Core agents: Reader, Summarizer, Concept Extractor, KG Agent
- [ ] Pipeline: raw/ → summary → claims → wiki pages (source + concept)
- [ ] CLI: `pkm ingest --new-only`
- [ ] GitHub Actions orchestration: repository_dispatch + nightly cron, commit-back to vault via VAULT_PAT
- [ ] Cloudflare Worker: capture endpoint (clip → raw/ → dispatch)
- [ ] Cloudflare Workers AI embeddings + Vectorize vector index
- [ ] Cloudflare Worker: query endpoint (embed → vector → Turso → Claude synthesis)
- [ ] Nightly lint + dashboard regeneration
- [ ] $0 guardrails: Actions spending limit $0, Anthropic spend cap, 80% Actions-minutes alert, backup remote

### Out of Scope (MVP)

- Neo4j graph database — deferred to V2 (SQLite graph tables are the bridge)
- Chroma/Vectorize-full path — basic Vectorize stub in Phase 6 is sufficient for MVP
- Pattern Detection agent — V2
- Contrarian agent — V2
- Opportunity + Investment + Writing agents — V3
- n8n orchestration — replaced by GitHub Actions at $0
- FastAPI local server — replaced by Cloudflare Workers
- Local daemon of any kind — hard constraint, never allowed

## Context

**Repos (settled):**
- `pkm-engine` — public GitHub repo (Python pipeline, Workers, Actions workflows; no secrets)
- `pkm-vault` — private GitHub repo (Markdown source of truth: raw/, wiki/, SCHEMA.md, index.md, log.md)

**Stack:**
- Storage: GitHub Markdown (vault), Turso libSQL (metadata/edges/cache), Cloudflare R2 (large blobs)
- Compute: GitHub Actions (Python 3.11 ingest pipeline), Cloudflare Workers (clip + query endpoints)
- Embeddings: Cloudflare Workers AI bge-base-en-v1.5 (768-dim, free)
- Vectors: Cloudflare Vectorize (5M vectors free)
- LLM: Claude API only (Haiku for cleanup, Sonnet for synthesis, Opus for contrarian/writing)
- DB client: `libsql-experimental` (works against Turso cloud and local SQLite identically)

**Key design principles:**
- Vault = source of truth; Turso/Vectorize are derived indexes (rebuildable from raw/)
- raw/ is append-only and content-addressed (AD-2)
- Hash-cache all LLM calls (AD-3) — re-ingest costs $0
- Zero local daemon (AD-4 variant) — nothing runs continuously on Mac
- Large text never stored in Turso (row-read trap avoidance)

## Constraints

- **Infrastructure**: $0 — all services must stay on free tiers; no paid plan
- **Architecture**: Zero local daemon — nothing continuously running on Mac
- **Data**: Never commit secrets; vault repo is private; engine repo is public
- **Idempotency**: Re-ingesting same content = 0 new rows, 0 LLM calls (hash cache enforced)
- **Scope**: Stop at MVP gate (Phase 8); do not start V1 autonomously

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| pkm-engine public, pkm-vault private | Unlimited free Actions minutes; engine has no secrets | — Pending validation |
| Turso (libSQL) over PlanetScale/Supabase | libSQL = SQLite API; zero schema change from local spec; $0 free tier | — Pending |
| Cloudflare Workers for clip/query endpoints | Always-on, $0, sub-second; replaces FastAPI + n8n | — Pending |
| GitHub Actions for ingest pipeline | Free (public repo = unlimited minutes); reuses Python unchanged; version-controlled | — Pending |
| Vectorize over Turso native vectors | Better for edge query Worker; 5M vectors free; co-located with other CF services | Tier-1: log in DECISIONS.md, revisit at MVP gate |
| repository_dispatch (not push trigger) | raw/ lives in vault repo; engine workflow can't watch cross-repo push events | — Settled AD |
| VAULT_PAT (not GITHUB_TOKEN) | Default token can't write to a different repo | — Settled AD |
| No Neo4j at MVP | Premature infrastructure; SQLite graph tables are the bridge to V2 | — Settled AD-3 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone (MVP gate):**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-15 after initialization*
