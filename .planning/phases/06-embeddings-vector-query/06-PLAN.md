# Phase 6: Embeddings + Vector + Query Worker

**Goal:** After ingest, every claim has an embedding in Cloudflare Vectorize.
`curl "$QUERY_WORKER_URL/query?q=..."` returns a cited answer within 5 seconds.
No local server involved.

**Roadmap requirements:** QURY-01–04
**Depends on:** Phase 5 complete ✓ (worker-clip deployed, ingest.yml running, vault live)

---

## Architecture

```
[GH Actions ingest.yml]
  pkm/pipeline/ingest.py
    └── Step 6.5 (new): embed_claims()
          │
          ├─► Workers AI REST  (@cf/baai/bge-base-en-v1.5, 768-dim)
          │     → batch of claim texts → [[float, ...], ...]
          │
          ├─► Vectorize REST   (upsert NDJSON to index "pkm-claims")
          │     → stores {id: claim_id, values: [...], metadata: {source_id, raw_path}}
          │
          └─► Turso            (INSERT OR REPLACE embeddings_meta row)

[Cloudflare Worker: worker-query.js]
  GET /query?q=<text>  (or POST JSON)
    │
    ├─ Workers AI binding: embed the query (same model)
    ├─ Vectorize binding:  query top-12 by cosine similarity
    ├─ Turso HTTP:         fetch claim text + source metadata for each hit
    └─ OpenAI API:         synthesize answer with citations
         → {answer, citations: [{statement, source_title, raw_path, url}]}
```

---

## Decisions to confirm before executing

| # | Decision | Recommendation | Alternative |
|---|----------|----------------|-------------|
| D-06-01 | **Synthesis model in worker-query.js** | `gpt-5.4-mini` (same as pipeline; one OPENAI_API_KEY secret covers both) | Claude claude-sonnet-4-6 (roadmap original intent; would need ANTHROPIC_API_KEY as a 2nd CF secret) |
| D-06-02 | **Query worker auth** | Add same `X-PKM-Key` gate as worker-clip (defence in depth; prevents your vault content from being read by anyone with the URL) | No auth (read-only; PKM is personal) |
| D-06-03 | **Query worker entry point** | Separate `wrangler-query.toml` pointing at `worker-query.js` (avoids binding collision with clip worker's R2 + no wrangler multi-worker syntax needed) | Second entry in same `wrangler.toml` using `[[workers]]` (newer syntax, less proven) |
| D-06-04 | **Embed what** | Claims only (`object_kind = 'claim'`) — currently ~150 claims across live sources; fits comfortably in 10K/day Workers AI free limit | Also embed chunks (3–5× volume; hits limit faster; no QURY requirement) |
| D-06-05 | **B-05-02 stuck source** | Fix in this phase (re-embed on wiki_path IS NULL + agent_runs ok) OR defer to Phase 7 | Must decide before writing embed.py idempotency logic |

---

## Waves

### Wave 1 — 06-01: Python embed module + ingest integration (GH Actions side)

**New secrets required (add before testing):**
- `CF_ACCOUNT_ID` — in GH Actions + as env var in ingest.yml
- `CF_API_TOKEN` — scoped to "Workers AI:Read" + "Vectorize:Edit" (create in CF dashboard)

**New Vectorize index (one-time setup):**
```bash
npx wrangler vectorize create pkm-claims --dimensions=768 --metric=cosine
```

**Files:**

| File | Action | What it does |
|------|--------|--------------|
| `pkm/retrieval/__init__.py` | Create | Package init |
| `pkm/retrieval/embed.py` | Create | `embed_claims(conn, claims, cf_account_id, cf_api_token)` → Workers AI REST batch embed → Vectorize REST upsert → `embeddings_meta` row per claim |
| `pkm/config.py` | Edit | Add `cf_account_id: str = ""` and `cf_api_token: str = ""` to Settings |
| `pkm/pipeline/ingest.py` | Edit | Add Step 6.5 after claim persist: call `embed_claims()` when `cf_account_id` is set; skip silently if not configured (keeps local dev working without CF creds) |
| `.github/workflows/ingest.yml` | Edit | Add `CF_ACCOUNT_ID` + `CF_API_TOKEN` to env block (read from GH secrets) |
| `tests/test_embed.py` | Create | Unit tests: mocked `requests.post` for Workers AI + Vectorize; verify `embeddings_meta` row written; verify idempotent upsert (same claim_id → no duplicate) |

**embed.py key behaviours:**
- Single REST call per claim to Workers AI (`POST /accounts/{id}/ai/run/@cf/baai/bge-base-en-v1.5`)
  — the model accepts `{"text": "..."}` and returns `{"result": {"data": [[float, ...]]}}`
- Vectorize upsert: `POST /accounts/{id}/vectorize/v2/indexes/pkm-claims/upsert` with
  NDJSON body: `{"id": "<claim_id>", "values": [...], "metadata": {"source_id": "...", "raw_path": "..."}}\n`
- `embeddings_meta` row: `INSERT OR REPLACE` so re-ingest updates the row rather than crashing
- Guard: if `cf_account_id` or `cf_api_token` is empty string, log a debug line and return — ingest proceeds without embedding (required for tests that don't set CF creds)
- `object_kind = 'claim'`, `collection = 'pkm-claims'`, `model = '@cf/baai/bge-base-en-v1.5'`, `dim = 768`

**DoD:**
- `pytest tests/test_embed.py` → all passing
- After a real ingest run: `SELECT COUNT(*) FROM embeddings_meta WHERE object_kind='claim'` in Turso = number of claims
- `npx wrangler vectorize get pkm-claims --vector-id <claim_id>` returns the vector

---

### Wave 2 — 06-02: Query Worker (Cloudflare side)

**New secrets required (set via `wrangler secret put -c wrangler-query.toml`):**
- `PKM_KEY` — same shared secret as clip worker (or separate; see D-06-02)
- `TURSO_URL` — libsql HTTP URL
- `TURSO_TOKEN` — Turso auth token
- `OPENAI_API_KEY` — for synthesis (or `ANTHROPIC_API_KEY` if D-06-01 resolves to Claude)

**Files:**

| File | Action | What it does |
|------|--------|--------------|
| `wrangler-query.toml` | Create | `name = "pkm-query"`, `main = "worker-query.js"`, Vectorize binding + AI binding |
| `worker-query.js` | Create | Full query worker (see flow below) |
| `test/worker-query.spec.ts` | Create | Vitest unit tests: mock AI/Vectorize/fetch; verify 401 on bad key; verify answer + citations shape |
| `vitest.config.ts` | — | Already exists; no change needed |

**worker-query.js flow:**
1. Auth gate (same `timingSafeEqual` as clip worker; return 401 on missing/wrong key)
2. Parse `?q=` from URL or `body.q` from JSON POST
3. `const {data} = await env.AI.run('@cf/baai/bge-base-en-v1.5', {text: q})` → 768-dim float[]
4. `const {matches} = await env.VECTORIZE.query(data[0], {topK: 12, returnMetadata: 'all'})`
5. Extract `claim_id`s from `matches[].id`; fetch from Turso:
   ```sql
   SELECT c.id, c.statement, s.title, s.raw_path, s.url
   FROM claims c JOIN sources s ON c.source_id = s.id
   WHERE c.id IN (?, ?, ...)
   ```
6. Build context block from fetched claims; call OpenAI `gpt-5.4-mini` with system prompt +
   context to synthesize a 2–4 sentence answer; include citations as `[N]` inline refs
7. Return `200 {"answer": "...", "citations": [{"id": "...", "statement": "...", "source_title": "...", "raw_path": "...", "url": "..."}]}`

**wrangler-query.toml bindings:**
```toml
name = "pkm-query"
main = "worker-query.js"
compatibility_date = "2026-06-01"

[ai]
binding = "AI"

[[vectorize]]
binding = "VECTORIZE"
index_name = "pkm-claims"

[vars]
TURSO_URL = ""   # overridden by secret

# Secrets (wrangler secret put -c wrangler-query.toml):
#   PKM_KEY, TURSO_URL, TURSO_TOKEN, OPENAI_API_KEY
```

**DoD:**
- `npx vitest run test/worker-query.spec.ts` → all passing
- `npx wrangler deploy -c wrangler-query.toml` succeeds

---

### Wave 3 — 06-03: Live verification

**Operator checklist (manual steps before verification run):**
- [ ] `npx wrangler vectorize create pkm-claims --dimensions=768 --metric=cosine`
- [ ] Add `CF_ACCOUNT_ID` + `CF_API_TOKEN` to GH Actions secrets (repo settings)
- [ ] `npx wrangler deploy -c wrangler-query.toml` → get `QUERY_WORKER_URL`
- [ ] Set worker-query secrets (PKM_KEY, TURSO_URL, TURSO_TOKEN, OPENAI_API_KEY)
- [ ] Fire a `repository_dispatch(event_type:"ingest")` (or clip a fresh article) to re-run
  ingest with embedding enabled

**Verification script (mirroring Phase 5 live-verify format):**
```bash
QUERY_WORKER_URL="https://pkm-query.rohitgupta-iitr.workers.dev"

# Criterion 1 — embeddings written during ingest
# Check Turso: SELECT COUNT(*) FROM embeddings_meta WHERE object_kind='claim'
# Expected: > 0

# Criterion 2 — /query returns answer + citations within 5s
time curl -sS "$QUERY_WORKER_URL/query?q=what+is+operating+leverage" \
  -H "X-PKM-Key: $(cat ~/.pkm_key)"
# Expected: {"answer":"...","citations":[...]} in < 5s

# Criterion 3 — citations are valid raw/ paths
# Verify each citation.raw_path exists in pkm-vault

# Criterion 4 — no local server in path
# Mac can be asleep; query is pure edge

# Criterion 5 — 401 on missing key
curl -sS -o /dev/null -w "%{http_code}" "$QUERY_WORKER_URL/query?q=test"
# Expected: 401
```

**Known risk: B-05-02 stuck source.** If the operating-leverage article was never
synthesized (stuck since Phase 5), its claims may not be in Turso and thus not embeddable.
Fix or note as a known gap in the verification doc.

---

## Success Criteria (QURY-01–04 + roadmap Phase 6 gates)

| # | Criterion | Pass condition |
|---|-----------|---------------|
| QURY-01 | Embeddings written at ingest | `SELECT COUNT(*) FROM embeddings_meta WHERE object_kind='claim'` > 0 after first ingest run |
| QURY-02 | `/query` returns cited answer | `{"answer": "...", "citations": [...]}` within 5s |
| QURY-03 | Citations are valid vault paths | Every `raw_path` in citations resolves to an existing file in pkm-vault |
| QURY-04 | No local server | Runtime path: edge Worker → Vectorize → Turso → OpenAI; Mac not involved |
| QURY-05 | Free tier safe | Workers AI usage ≤ 10K/day at current clip rate (~5–10 articles/day × ~20 claims = ~200 embed calls/day) |

---

## New environment variables / secrets summary

| Secret | Set in | Used by |
|--------|--------|---------|
| `CF_ACCOUNT_ID` | GH Actions repo secrets | `ingest.yml` → `embed.py` (Workers AI + Vectorize REST) |
| `CF_API_TOKEN` | GH Actions repo secrets | `ingest.yml` → `embed.py` (Workers AI + Vectorize REST) |
| `PKM_KEY` | CF Worker secret (`wrangler-query.toml`) | `worker-query.js` auth gate |
| `TURSO_URL` | CF Worker secret | `worker-query.js` claims fetch |
| `TURSO_TOKEN` | CF Worker secret | `worker-query.js` claims fetch |
| `OPENAI_API_KEY` | CF Worker secret | `worker-query.js` synthesis |

CF_API_TOKEN scope: `Workers AI:Read` + `Vectorize:Edit` (create in CF dashboard → "My Profile → API Tokens → Create Token").

---

*Phase 6 plan authored: 2026-06-21*
