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
| Phase 7: Scheduled Jobs + Guardrails | Complete ✓ (2026-06-21) | All 5 ROADMAP success criteria verified PASS via workflow_dispatch run 27901063045 | lint.py + dashboard.py + migration 003 + backfill_embeds + CLI + ingest.yml guardrail steps + GUARDRAILS.md; 134 tests passing; Plan 05 operator checkpoint complete (GUARD-04/05/07 + CF creds); backup remote `pkm-vault-backup` mirroring vault; two backup-push bugs fixed (extraheader override, shallow fetch-depth) |
| Phase 8: Hardening + MVP Gate | Complete ✓ — **MVP-ready declared 2026-06-21** | All 6 MVP criteria PASS | counter backfill (sources=7/claims=160/concepts=40) + full suite green (pytest 137 / npm 13+19) + MVP-03 broken-wikilinks=0 + MVP-06 cost actuals ($0 infra + OpenAI $0.35/mo) + Tier-1 review + MVP-01/02/04 live evidence; held at MVP gate, V1 not started |

---

## Cost Actuals

Filled at the Phase 8 MVP gate per MVP-06 (2026-06-21). All figures are actuals,
not estimates.

| Item | Target | Actual |
|------|--------|--------|
| Infrastructure (recurring) | $0/mo | **$0/mo** — Turso free tier, Cloudflare Workers free tier, no recurring infra |
| GitHub Actions minutes | $0 (public repo = unlimited) | **$0** — public repo = unlimited free minutes; spending limit $0 fail-closed (GUARD-04, confirmed 2026-06-21) |
| Cloudflare Workers | $0 (free tier) | **$0** — free tier; Workers AI within 10K/day free limit at current scale (Phase 6) |
| Turso | $0 (free tier) | **$0** — free tier |
| OpenAI API (pipeline) | ≤ per-run cap, ≤ monthly hard limit | **$0.35/mo** (June 2026: $0.353260 across 40 agent_runs rows, 197,154 tokens) — cumulative-to-date $0.353260 |

**MVP-06 cost evidence (2026-06-21):** OpenAI $/mo derived from the real
`agent_runs.cost_usd` totals, not an estimate — the live Turso query
`SELECT SUM(cost_usd) FROM agent_runs` returns $0.353260 across 40 rows
(197,154 tokens), all in calendar month 2026-06. `cost_usd` is computed per call
by `pkm/llm/pricing.py::compute_cost` (`pkm/llm/client.py:352`), which raises
`KeyError` on unknown models and never returns a hardcoded 0.0 — T1-02
condition 2, load-bearing for this evidence (verified in `DECISIONS.md` "Phase
8 MVP-gate review").

**Cost controls confirmed:**
- Per-run cap `PKM_RUN_COST_CAP_USD` (default $0.50) — `pkm/batch.py` aborts a
  run if cumulative `cost_usd` ≥ cap. The single largest run is well under this.
- Per-run token cap `PKM_RUN_TOKEN_CAP` (default 200,000) — `pkm/batch.py` aborts
  if cumulative tokens ≥ cap.
- OpenAI monthly hard limit (GUARD-05, set 2026-06-21) — bounds month-total
  spend at the account level.

The "Claude API (pipeline)" target row is satisfied by the OpenAI actual: the
cloud pipeline LLM backend is OpenAI `gpt-5.4-mini` (T1-02, locked 2026-06-19),
not Anthropic. Total cumulative OpenAI spend to date: $0.353260. No secret
values recorded — only dollar figures and token counts.

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

---

## Phase 7 Code Complete — Plans 01–04 (2026-06-21)

Plans 01–04 executed autonomously (YOLO). Plan 05 is the `autonomous:false`
operator checkpoint — surfaced back, not executed.

**Suite:** `pytest` → 134 passed (was 100 at Phase 7 start; +34 new tests).

### Plan 07-01 — Lint module (GUARD-01) ✓
- `pkm/lint.py`: `lint_vault(conn, vault_root, write_log=True, now=None) -> LintReport`
  — broken `[[wikilinks]]` (handles `[[slug|alias]]`), orphans (not referenced by
  another page AND not in index.md), missing provenance (`claims WHERE chunk_id IS
  NULL`, parameterized). `lint ok` / `lint FAIL broken=N orphan=N
  missing_provenance=N` block to log.md via `append_log`.
- `tests/test_lint.py`: 13 tests. `grep -c COUNT pkm/lint.py` = 0.

### Plan 07-02 — Dashboard + counter rows (GUARD-02, GUARD-03) ✓
- `migrations/sqlite/003_dashboard_counters.sql` (key, value, updated_at).
- `pkm/store/registry.py`: `bump_counter` / `read_counter` / `read_all_counters`;
  migration 003 added to `_run_migrations`; bumps wired into `upsert_source` /
  `upsert_concept` (created-guarded) / `insert_claim` (always). Idempotent re-ingest
  leaves counters stable (verified).
- `pkm/dashboard.py`: `generate_dashboard` / `write_dashboard` — six sections from
  counter rows + `lint_vault(..., write_log=False)`. No `COUNT(*) FROM
  sources|claims|concepts` (grep = 0; spy-verified).
- `tests/test_dashboard.py`: 16 tests.

### Plan 07-03 — CLI + backfill_embeds (GUARD-01, GUARD-02) ✓
- `pkm/retrieval/embed.py`: `backfill_embeds` — reusable idempotent backfill for
  claims lacking `embeddings_meta` (one pass per run; empty-creds no-op; delegates
  to `embed_claims`). Closes the deferred Phase-6 CI-embed gap.
- `pkm/cli.py`: `pkm lint` (exit 1 on dirty vault), `pkm dashboard`, `pkm
  backfill-embeds` (exit 1 on failures). Handlers print only result dicts — never
  Settings/api_key.
- `tests/test_backfill_embeds.py`: 5 tests. Functional smoke verified (clean/dirty
  lint exit codes, dashboard.md write, no-creds backfill no-op).

### Plan 07-04 — ingest.yml nightly steps + GUARDRAILS.md (GUARD-06, GUARD-07) ✓
- `.github/workflows/ingest.yml`: +7 steps after batch-ingest — backfill-embeds,
  lint, compute actions-minutes, regenerate dashboard, 80% alert (log.md WARN),
  commit guardrail artifacts, backup push to `secrets.BACKUP_REMOTE_URL`.
  `continue-on-error` on backfill/lint/backup; `if: always()` on backfill/backup;
  `permissions: contents: read` preserved (backup uses BACKUP_REMOTE_URL credential).
- `docs/GUARDRAILS.md`: operator runbook for GUARD-04/05/06/07 + OpenAI
  reconciliation + deferred CF-creds gap. No secret material (grep clean).

### Plan 07-05 — Operator checkpoint (autonomous:false) — COMPLETE ✓ (2026-06-21)
Operator performed the external console configurations; Claude verified the
end-to-end nightly run from the CLI.
1. GUARD-04 — GH Actions spending limit $0 confirmed (public repo = free;
   private vault = $0 fail-closed).
2. GUARD-05 — OpenAI monthly hard spend limit set in OpenAI console (reconciled
   from stale Anthropic wording); per-run caps `PKM_RUN_COST_CAP_USD` /
   `PKM_RUN_TOKEN_CAP` confirmed in `pkm/batch.py`.
3. GUARD-07 — second remote `rohitgupta1686/pkm-vault-backup` created; scoped
   fine-grained PAT (contents:read+write on backup repo only); `BACKUP_REMOTE_URL`
   secret added to pkm-engine.
4. Deferred CF creds — `CF_ACCOUNT_ID` + `CF_API_TOKEN` (Workers AI:Read +
   Vectorize:Edit) added as GH Actions secrets; CI embedding now functional.
5. `workflow_dispatch` run
   [27901063045](https://github.com/rohitgupta1686/pkm-engine/actions/runs/27901063045)
   — all 5 ROADMAP Phase 7 success criteria PASS. Results in
   `docs/GUARDRAILS.md` Verification section.

**Two backup-push bugs found + fixed during verification:**
- 403 "Write access not granted" — `actions/checkout` `persist-credentials:
  true` injects `VAULT_PAT` as `http.https://github.com/.extraheader`, which
  overrides the backup token embedded in `BACKUP_REMOTE_URL`. Fix: clear the
  extraheader for the backup push (commit `2e2f6ae`).
- "remote unpack failed: index-pack failed" — `actions/checkout` default
  `fetch-depth: 1` shallow clone lacks parent history to push to the empty
  backup remote. Fix: `fetch-depth: 0` on the vault checkout (commit `1b857d7`).

**Known follow-up (carry into Phase 8):** dashboard `Sources/Claims/Concepts`
counters read 0 — `dashboard_counters` rows only bump on new inserts, so
pre-Phase-7 data (~160 claims) was never counted. One-time counter backfill
needed. Lint orphan/missing-provenance counts are correct (query live tables).
