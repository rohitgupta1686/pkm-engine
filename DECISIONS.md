# PKM Engine — Decisions Log

Mode A (reversible) and Tier-1 (MVP gate batch) decisions recorded here.
See `PKM_Build_Plan_for_Claude_Code.md` §Operating Modes for the distinction.

---

## Reversible Decisions (Mode A)

Logged autonomously during execution. These are reversible — rework < 1 day.

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
