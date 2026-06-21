# PKM Engine — Decisions Log

Mode A (reversible) and Tier-1 (MVP gate batch) decisions recorded here.
See `PKM_Build_Plan_for_Claude_Code.md` §Operating Modes for the distinction.

---

## Reversible Decisions (Mode A)

Logged autonomously during execution. These are reversible — rework < 1 day.

---

## Phase 5 — Capture Worker

**[T2-05-01] Q1 — R2 offload for >200K text.** Keep the FULL text in the `raw/` body
AND mirror a copy to R2 when `text.length > 200_000`, storing the `r2key` in the
`raw/` front matter. The body is **NEVER reduced to a pointer**. Rationale: the
ingest pipeline (`pkm/pipeline/ingest.py::run_ingest`) cannot read R2 and synthesizes
from `raw_text` read out of the `raw/*.md` body — a pointer body would make the LLM
summarize "[blob in R2: ...]". The R2 mirror is belt-and-suspenders that sets up a
future "pipeline fetches R2" path. Tradeoff: Git still holds >200K text at MVP scale
(rare; Git handles text well). Reversible: a future phase can teach the pipeline to
fetch from R2 and reduce the body. Cross-ref `05-RESEARCH.md` Pitfall 6.

---

**[T2-05-02] Q2 — single fine-grained PAT scoped to `contents:write` on BOTH
`pkm-vault` (commit `raw/`) AND `pkm-engine` (fire `repository_dispatch`).** Stored as
one Worker Secret `GH_PAT` via `wrangler secret put`. Rationale: firing
`repository_dispatch` against `pkm-engine` requires `contents:write` on
`pkm-engine`; the **PKM Cloud Architecture doc §11 only mentions the `pkm-vault`
scope**, which would **403 the dispatch** silently. The README corrects this and
scopes the PAT to both repos. Tradeoff: one token has broader scope than two
isolated tokens (a single compromise touches both repos). Reversible: split into
`VAULT_PAT` + `ENGINE_PAT` any time. `X-PKM-Key` is a separate Worker Secret
(authentication, not GitHub) — see `wrangler.toml`.

---

**[T2-05-03] Q3 — re-clip of an existing `raw/` path.** The Worker does GET-then-PUT;
on an existing path (GET 200) it skips the PUT commit (200 no-op for the commit
step) BUT still fires `repository_dispatch(event_type:"ingest")`. Rationale: gives a
manual re-trigger path from the clipper (re-run the pipeline on a source without
re-clipping the text); downstream pipeline dedups via the `sha256(raw_text)` cache
(ORCH-07 → 0 LLM calls, 0 new rows). Tradeoff: a few GitHub Actions minutes per
re-clip even when nothing changes. Reversible: could suppress the dispatch on a
no-op commit.

**[T2-05-04] Claim chunk_id FK — map LLM positional labels to real chunks.ids.**
The summarizer/extractor prompts instruct the LLM to emit positional chunk_id
labels ("para_1", "section_body") or the "null" sentinel, because the model
cannot see the deterministic `chk_<hash>_NNN` chunk ids. `claims.chunk_id` has a
hard FK to `chunks(id)` (AD-6), so any non-null value that isn't a real
`chunks.id` crashes `batch_ingest` on the FK — found in the 05-03 live run
(nondeterministic: only fails when the LLM emits a positional label, not
"null"). `run_ingest` now resolves every claim's `chunk_id` via
`_resolve_claim_chunk_id` before insert: a real `chunks.id` is kept; `para_N`
maps to ordinal `N-1`'s chunk id when in range; everything else (including
"null") becomes SQL NULL. Rationale (vs the alternative of dropping the FK):
keeps the provenance contract and the existing
`test_claim_null_chunk_id_sentinel_satisfies_fk` invariant ("a bogus real
chunk_id must still be rejected") intact, with no schema migration. Tradeoff:
the `para_N → ordinal` mapping is heuristic (chunks are ~1200-token windows, not
paragraphs), so provenance is best-effort and some claims land on NULL. The
drop-FK alternative (free-text provenance, richest signal) is deferred to MVP
review as a Type-1 contract change. Reversible: pure ingest-code change, no
migration; re-ingest repopulates `claims.chunk_id`.

---

---

### Phase 3 — Vault Scaffold (03-01)

**Decision:** Build-plan prose maps to DB claims.status value `candidate` — the
schema CHECK constraint in `migrations/sqlite/001_init.sql` does not permit any
other value as the initial claim status. The valid initial status is `candidate`.
SCHEMA.md documents the four valid claims.status values: `candidate`, `approved`,
`merged`, `rejected`. This is locked from Phase 1 and cannot be changed without
a migration.

---

### Phase 1 — Data Layer

**Decision:** `setuptools` package discovery scoped to `pkm*` only — `migrations/`
dir caused flat-layout error if discovered.

**Decision:** `libsql_experimental.execute()` only runs first SQL statement — all
migration runners use `executescript()`.

**Decision:** `anthropic_api_key` has empty string default in Settings for
test-context compatibility.

---

### Phase 1 — Wave 2

**Decision:** INSERT OR REPLACE (not INSERT OR IGNORE) in `_write_run` — ensures
an ok-row overwrites a prior error-row for the same `(agent, input_hash)`.

**Decision:** LLMClient uses tool-calling (`tools=[] + tool_choice`) when
`output_schema` provided — JSON schema enforcement at API level.

**Decision:** LLMClient takes explicit `conn + api_key` — no Settings singleton
inside client for testability.

**Decision:** Migrations dir resolved via `Path(__file__)` so it works regardless
of `cwd` (tests use `os.chdir`).

---

### Phase 2 — Wave 2 (02-04)

**Decision:** Tier 3 embedding resolution stubbed (logs debug, returns None) per
AD-5 MVP constraint — no Opus call, no API spend at extraction time.

**Decision:** `resolver.py` SQL uses parameterized `?` placeholders throughout
(T-02-08 SQL-injection mitigation).

**Decision:** `noisy_or()` is a pure function with no DB dependency — enables
isolated unit testing.

---

### Phase 2 — Wave 2 (02-03)

**Decision:** `chunk_id="null"` string convention as data contract — confidence
<= 0.5 enforced in test; Python `None` is not used; the string `"null"` is the
sentinel value for untraceable claims.

**Decision:** `repair-retry` test patches `pkm.llm.client.anthropic.Anthropic`
and re-creates `LLMClient` inside the patch context — cannot patch after
`__init__` because `self.client` is bound at construction time.

**Decision:** `ConceptMatch.claim_indices` is `list[int]` — pydantic rejects
string indices at validation gate (mitigates T-02-05).

---

### Phase 2 — Wave 1 (02-01)

**Decision:** `BaseAgent` uses `__init_subclass__` (not `@abstractmethod`) for
ClassVar enforcement — ClassVars cannot be abstract methods; `__init_subclass__`
fires at class-definition time giving immediate `TypeError`.

**Decision:** No `LLMClient` import in `pkm.agents.base` — client injected via
`run()` arg to avoid coupling and enable `MagicMock` testing.

**Decision:** `chunk_id` uses positional IDs (`para_1`, `para_2`) when source
lacks explicit markers; string `"null"` reserved for untraceable claims with
confidence <= 0.5.

---

## Tier-1 Batch (for MVP gate review)

Tier-1 decisions: proceed on default, list here, revisit at Phase 8 MVP gate.

---

**[T1-01] Vectorize chosen over Turso native vectors** (default per cloud doc §7.2)

Better for the edge query Worker; 5M vectors free; co-located with other
Cloudflare services. Revisit at MVP gate if Turso native vectors reach parity.

---

**[T1-02] Cloud pipeline LLM backend switched Anthropic → OpenAI GPT-5.4-mini** (locked 2026-06-19)

The cloud GitHub Actions ingest pipeline moves from the Anthropic SDK to OpenAI
`gpt-5.4-mini-2026-03-17` via the standard synchronous Chat Completions API.
Resolved via fresh-context Opus adversarial pass (verdict: lock-with-conditions)
and explicit user Mode-C acceptance of three conditions:

1. **Dispatch path = standard sync API, NOT Batch.** The OpenAI Batch API is
   async with a 24h SLA and cannot satisfy the locked Phase-4 `<10-minute`
   dispatch budget (`04-03-PLAN.md`, `ingest.yml: timeout-minutes: 10`). A Batch
   bulk/backfill path is deferred to a separate follow-up PLAN; it must not
   claim the `<10-min` criterion or block the dispatch flow.
2. **$0-infra exception (bounded per-token spend).** OpenAI is pay-as-you-go,
   not a free tier, so this modifies the `$0 infrastructure` hard constraint.
   Accepted in spirit (per-token usage ≠ recurring infra) but gated on a
   **per-run token/$ ceiling that aborts the batch** plus real `cost_usd`
   computation from usage — both MUST exist before the workflow runs on
   Actions. `client.py:220` currently hardcodes `cost_usd = 0.0`; that is a
   blocker for wiring this in. Revisit at MVP gate.
3. **Cache-bust accepted (one-time full re-ingest).** `_make_input_hash`
   (`client.py:27-29`) includes the model string in the cache key, so the model
   change busts every `agent_runs` ok-row. First post-switch run re-runs all
   agents for all sources once, rewrites wiki pages, and costs one full pass.
   Accepted deliberately — no hash-remap migration. Note: any future model
   bump will re-bust the cache the same way; a cache-versioning scheme that
   separates model identity from cache validity is the durable fix (deferred).

Migration is Type-2 (reversible-in-a-day): confined to `pkm/llm/client.py`
(rewrite SDK import, constructor, `_call_api`, structured-output,
repair-retry, usage/error handling), `pkm/llm/models.py` (model constants),
`pkm/config.py`, `pkm/cli.py`,
`.github/workflows/ingest.yml` (`OPENAI_API_KEY` secret), `docs/SECRETS.md`,
and the agent `model` ClassVars. Agent prompts under `pkm/prompts/*.md` reference
"the `structured_output` tool" (Anthropic tool-calling wording) — must be reworded
for OpenAI `response_format: json_schema` (strict). Agents themselves are
provider-agnostic (only declare pydantic `output_schema`), so blast radius stays
in `client.py` + prompt wording. No DB schema migration.

**Provider architecture (refined during 04-04 planning):** OpenAI SDK is the sole
client; the `anthropic` dependency, `anthropic_api_key`, `llm_provider`, and
`ollama_*` Settings fields are **removed entirely** (no runtime provider branch —
that would be the "parallel provider path" the decision forbids). Added: `openai_api_key`,
`openai_base_url` (default `https://api.openai.com/v1`), `llm_model` (default `MINI`),
`run_cost_cap_usd`, `run_token_cap`. Agents read `settings.llm_model` (one model for
all agents — the HAIKU/SONNET distinction collapses to a single gpt-5.4-mini). Any
Anthropic-model usage routes through an OpenAI-compatible endpoint (e.g. CLIProxyAPI)
via the OpenAI SDK + `openai_base_url` + `llm_model` set to a claude-* id; CLIProxyAPI
`/v1/chat/completions` support is unverified, so local Claude dev is a nice-to-have, not
a 04-04 gate.

Relates to memory `project-pkm-llm-backend-decision` (resolved).

---

## Phase 8 MVP-gate review (2026-06-21)

Recorded at the Phase 8 MVP gate. This section records **dispositions and
condition verification only** — it does NOT lock any new Type-1 decision. The
MVP-ready / V1-advancement call is a human judgment reserved for the
`08-MVP-REVIEW.md` checkpoint (Type-1, irreversible per CLAUDE.md "Stop at MVP
gate"). Language here is "reaffirm" / "PASS" / "carried to MVP review", never
"locked".

### T1-01 — Vectorize over Turso native vectors

**Disposition: reaffirm.** Turso native vectors have not reached parity on the
edge-query-worker use case. Vectorize is live and load-bearing: the
`pkm-claims` Vectorize index was created and 160 claims embedded in Phase 6
Wave 3; `worker-query.js` (deployed `https://pkm-query.rohitgupta-iitr.workers.dev`)
depends on it for embed → search → synthesis. No change at the MVP gate.

### T1-02 — OpenAI GPT-5.4-mini backend (locked 2026-06-19)

Three locked conditions, each verified against the current code (file:line):

1. **Dispatch = sync API, not Batch — PASS.**
   `.github/workflows/ingest.yml:20` → `timeout-minutes: 10`, matching the
   locked `<10-minute` dispatch budget. `pkm/llm/client.py` uses the
   synchronous Chat Completions endpoint (`_call_api` → `client.chat.completions`);
   no Batch API call exists in the codebase. The 24h-async Batch path remains
   deferred and does not claim the `<10-min` criterion.

2. **cost_usd computed from usage, not hardcoded 0.0 — PASS.**
   `pkm/llm/client.py:352` → `cost_usd = compute_cost(model, tokens_in,
   cached_tokens, tokens_out)`. `pkm/llm/pricing.py:40` → `p = PRICING[model]`
   raises `KeyError` on unknown model (fail-loud, never returns 0.0 — the
   original `client.py:220` blocker cited in the lock is resolved). This is
   load-bearing for MVP-06: the cost actuals in `PROGRESS.md` are derived from
   the real `agent_runs.cost_usd` values this path writes (see PROGRESS.md
   "Cost Actuals" — `SUM(cost_usd) FROM agent_runs`).

3. **Cache-bust accepted — PASS.**
   `pkm/llm/client.py:168-174` → `_make_input_hash(agent_name, model,
   prompt_version, input_text)` includes the model string in the SHA-256 cache
   key, so the model change busts every `agent_runs` ok-row. The one-time full
   re-ingest has occurred — the ~160-claim corpus reflects post-switch ingest
   (Phase 6 Wave 3). The durable cache-versioning fix (separating model
   identity from cache validity) remains deferred as noted in the lock.

**All three conditions PASS. No revision to T1-02 at the MVP gate.**

### Tier-1-class items accumulated since Phase 1 — carried to MVP review

- **[T2-05-04] drop-FK / free-text-provenance deferral — carried to MVP review.**
  The current ingest path resolves `claims.chunk_id` heuristically (`para_N →
  ordinal`; everything else → SQL NULL), so provenance is best-effort and some
  claims land on NULL `chunk_id` (the missing-provenance count recorded in
  `docs/PHASE8_VERIFICATION.md` MVP-03). T2-05-04 explicitly defers the
  drop-FK / free-text-provenance alternative to MVP review **as a Type-1
  contract change**. It is NOT locked here; the human decides at the
  `08-MVP-REVIEW.md` checkpoint whether to accept the best-effort limitation
  for MVP or pursue the contract change in V1.

No other Tier-1-class decisions found outside the Tier-1 Batch section.

---
