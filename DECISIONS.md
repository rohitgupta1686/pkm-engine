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
