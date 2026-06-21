# PKM Engine — Phase Progress Tracker

Tracks phase-by-phase progress toward the Phase 8 MVP gate.
Updated at the end of each phase. See DECISIONS.md for logged choices.

---

## Phase Progress

| Phase | Status | DoD met | Notes |
|-------|--------|---------|-------|
| Phase 1: Data Layer + Idempotency | Complete ✓ | Yes | 5/5 tests passing; immutability trigger, schema auto-migrate, LLM cache verified |
| Phase 2: Core Agents | Complete ✓ | Yes | 22/22 tests passing; ReaderAgent, SummarizerAgent, ConceptExtractor, KGAgent all complete |
| Phase 3: Pipeline + Vault Writer + CLI | Complete ✓ | Yes | run_ingest end-to-end; GitVaultWriter; CLI ingest/batch; see PHASE3 verification |
| Phase 4: GitHub Actions Orchestration | Complete ✓ | Yes | ingest.yml dispatch workflow; VAULT_PAT + CF secrets; see PHASE4_VERIFICATION.md |
| Phase 5: Capture Worker | Complete ✓ | Yes | worker-clip.js; X-PKM-Key auth; 13 vitest tests passing; see PHASE5_VERIFICATION.md |
| Phase 6: Embeddings + Vector + Query Worker | Complete ✓ | Wave 1–3 | embed.py + worker-query.js + 132 tests passing; Wave 3 live CF deploy verified (160 claims embedded, end-to-end query returns cited synthesis) |
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

## Phase 3 DoD Evidence (2026-06-16)

- `pytest`: full suite green
- run_ingest(): reader→summarizer→concept→kg→vault pipeline complete
- GitVaultWriter commits synthesized wiki pages to pkm-vault
- CLI: `pkm ingest` + `pkm batch-ingest` working

## Phase 4 DoD Evidence (2026-06-16)

- `.github/workflows/ingest.yml`: repository_dispatch trigger with `repository_dispatch_token`
- VAULT_PAT secret + gh repo push confirmed in docs/PHASE4_VERIFICATION.md
- Batch ingest with per-run cost+token cap enforced

## Phase 5 DoD Evidence (2026-06-17)

- `npm test`: 13 vitest tests passing (worker-clip.spec.ts)
- worker-clip.js deployed to Cloudflare Workers
- X-PKM-Key timingSafeEqual auth gate verified
- GitHub repository_dispatch fires on successful clip
- See docs/PHASE5_VERIFICATION.md

## Phase 6 Code Complete (2026-06-21)

- `pytest`: 100 passed (includes test_embed.py — 14 new tests)
- `npm test`: 13 clip worker tests passing
- `npm run test:query`: 19 query worker tests passing
- B-05-02 stuck-source bug fixed in run_ingest (wiki_path IS NOT NULL guard)
- pkm/retrieval/embed.py: Workers AI REST + Vectorize NDJSON upsert, idempotent
- worker-query.js: embed→search→Turso→OpenAI synthesis, X-PKM-Key auth
- Wave 3 (live CF deploy) requires operator steps — see below

### Wave 3 operator checklist (manual steps before verification run):

```
# 1. Create Vectorize index (one-time)
npx wrangler vectorize create pkm-claims --dimensions=768 --metric=cosine

# 2. Add GH Actions secrets (CF_ACCOUNT_ID, CF_API_TOKEN) via GitHub repo settings
#    Required scopes: Workers AI:Read + Vectorize:Edit

# 3. Deploy query worker
npx wrangler deploy -c wrangler-query.toml

# 4. Set query worker secrets
wrangler secret put PKM_KEY -c wrangler-query.toml
wrangler secret put TURSO_URL -c wrangler-query.toml
wrangler secret put TURSO_TOKEN -c wrangler-query.toml
wrangler secret put OPENAI_API_KEY -c wrangler-query.toml

# 5. Fire ingest to populate Vectorize (dispatch or send a clip)
#    After ingest, check: SELECT COUNT(*) FROM embeddings_meta;

# 6. Verify end-to-end
curl "$QUERY_WORKER_URL/query?q=what+is+operating+leverage" \
  -H "X-PKM-Key: $(cat ~/.pkm_key)"
```

### Wave 3 COMPLETE ✓ (2026-06-21)

Live deploy executed and end-to-end query verified against real data.

**Done:**
- Vectorize index `pkm-claims` created (768-dim, cosine) via `wrangler vectorize create`.
- Query worker `pkm-query` deployed → `https://pkm-query.rohitgupta-iitr.workers.dev` (AI + VECTORIZE bindings).
- 4 worker secrets set: `PKM_KEY`, `OPENAI_API_KEY`, `TURSO_URL`, `TURSO_TOKEN`.
- Vectorize populated with all 160 existing claims (embeddings_meta = 160) via a one-off local backfill (`embed_claims` called per-source). 0 failed.
- End-to-end `/query?q=what+is+operating+leverage` returns a synthesized, cited answer with a `citations[]` array (claim id, statement, source_title, raw_path, url). Full chain verified live: X-PKM-Key auth → Workers AI embed → Vectorize search → Turso HTTPS pipeline fetch → OpenAI gpt-5.4-mini synthesis.
- `npm run test:query`: 19/19 passing after fix.

**Fixes made during Wave 3 (code):**
- `worker-query.js`: `max_tokens` → `max_completion_tokens` (gpt-5.4-mini rejects `max_tokens`; unit tests mock OpenAI so this only surfaced against the live API). Redeployed.
- Query worker `TURSO_URL` secret must be the **HTTPS** form (`https://<db>.turso.io`), not `libsql://` — the worker does a raw `fetch(${TURSO_URL}/v2/pipeline)`, and `libsql://` is not a fetchable scheme. (The Python pipeline still uses `libsql://` via the libsql driver; the two clients use different schemes — both correct for their client.)

**Deviations from checklist & deferred gaps:**
- Step 2 (GH Actions secrets `CF_ACCOUNT_ID` + `CF_API_TOKEN`) was **skipped**. Vectorize was populated via a local backfill using the wrangler OAuth token (valid for Workers AI + Vectorize REST), not via a CI ingest run. **Consequence:** the CI ingest workflow still has no CF creds, so future CI ingests will skip the embed step (Step 6.5 no-op) and new sources will NOT be auto-embedded. To wire CI embedding, add `CF_ACCOUNT_ID` + a scoped `CF_API_TOKEN` (Workers AI:Read + Vectorize:Edit) as GitHub Actions secrets — this is a remaining operator step, deferred to Phase 7 (Scheduled Jobs + Guardrails) or a follow-up. A reusable `pkm backfill-embeds` command is a candidate Phase 7 addition.
- Step 5 used backfill of existing claims rather than firing a fresh ingest; functionally equivalent for query-worker verification.
