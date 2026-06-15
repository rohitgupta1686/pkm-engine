---
phase: 01-data-layer-idempotency
plan: 02
subsystem: database
tags: [libsql, anthropic, pydantic, hash-cache, agent_runs, migrations, tool-calling]

# Dependency graph
requires:
  - phase: 01-data-layer-idempotency
    plan: 01
    provides: "pyproject.toml, pkm/config.py, migrations/sqlite/001_init.sql, 002_graph_tables.sql"
provides:
  - pkm.llm.models: HAIKU, SONNET, OPUS exact model string constants
  - pkm.store.registry.connect(): dual-mode libsql connection with auto-migration
  - pkm.llm.client.LLMClient: SHA-256 hash-cache dedup, tool-calling structured output, repair-retry
  - pkm.schemas.*: SourceRecord, ClaimRecord, ConceptRecord, EntityRecord, GraphNodeRecord/EdgeRecord, ChunkRecord, agent_io (KeyClaim/SummarizerOutput/GraphNode/GraphRelationship/KGAgentOutput)
affects:
  - 01-03 (Wave 3 idempotency test uses registry.connect() and LLMClient._check_cache)
  - Phase 2 agents import schemas from pkm.schemas.*

# Tech tracking
tech-stack:
  added:
    - libsql-experimental (libsql.connect() dual-mode local/Turso)
    - anthropic (Anthropic SDK with tool-calling structured output)
    - pydantic (schema validation with Field ge/le constraints)
  patterns:
    - Hash cache pattern: sha256(agent+model+prompt_version+input) hex stored in agent_runs
    - INSERT OR REPLACE for upsert-safe ok-row over error-row (not INSERT OR IGNORE)
    - Tool-calling structured output: tools=[{"name":"structured_output","input_schema":...}] + tool_choice
    - One-shot repair-retry on ValidationError with error feedback appended to messages
    - Dual-mode DB connect: TURSO_URL truthy → cloud; else → local SQLite

key-files:
  created:
    - pkm/llm/__init__.py
    - pkm/llm/models.py
    - pkm/llm/client.py
    - pkm/store/__init__.py
    - pkm/store/registry.py
    - pkm/schemas/__init__.py
    - pkm/schemas/source.py
    - pkm/schemas/claim.py
    - pkm/schemas/concept.py
    - pkm/schemas/entity.py
    - pkm/schemas/graph.py
    - pkm/schemas/chunk.py
    - pkm/schemas/agent_io.py
  modified: []

key-decisions:
  - "INSERT OR REPLACE (not INSERT OR IGNORE) in _write_run so a successful ok-row always overwrites a prior error-row for the same (agent, input_hash)"
  - "Tool-calling structured output: LLMClient uses tools=[]+tool_choice when output_schema provided, guaranteeing JSON schema enforcement at the API level"
  - "One repair-retry only on ValidationError: append error text and re-send — no infinite loops"
  - "LLMClient takes conn + api_key explicitly — no Settings import inside client, keeping it testable without env vars"
  - "registry.py resolve migrations dir relative to __file__ (Path(__file__).parent.parent.parent / migrations / sqlite)"

patterns-established:
  - "Hash cache pattern: every LLM call checks agent_runs for (agent, input_hash, status='ok') before hitting API"
  - "Dual-mode connect: Settings.turso_url truthy → cloud libsql; else → local SQLite file"
  - "Pydantic schemas mirror SQL schema as app-level types; agent_io schemas enforce Field(ge=0,le=1) constraints"

requirements-completed:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-04
  - DATA-05
  - DATA-06
  - DATA-07
  - DATA-08
  - DATA-09

# Metrics
duration: 15min
completed: 2026-06-15
---

# Phase 1 Plan 02: Data Layer Wave 2 — Runtime Components Summary

**libsql registry with auto-migration, SHA-256 hash-cache LLMClient with tool-calling structured output and repair-retry, and all pydantic DB+agent schemas**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-15T00:00:00Z
- **Completed:** 2026-06-15T00:15:00Z
- **Tasks:** 2
- **Files created:** 13

## Accomplishments

- `pkm.store.registry.connect()`: dual-mode (local SQLite / Turso cloud) via libsql-experimental, auto-runs both migration files on every startup with IF NOT EXISTS idempotency
- `pkm.llm.client.LLMClient`: SHA-256 hash-cache dedup (checks `agent_runs` for status='ok' before API call), tool-calling structured output when `output_schema` provided, one-shot repair-retry on ValidationError, exponential backoff on 429/529, writes ok or error row to `agent_runs` on every live call
- All pydantic schemas: 7 DB-mirror models (SourceRecord, ClaimRecord, ConceptRecord, EntityRecord, GraphNodeRecord, GraphEdgeRecord, ChunkRecord) + 5 agent_io models (KeyClaim, SummarizerOutput, GraphNode, GraphRelationship, KGAgentOutput) with exact spec constraints
- Model constants: HAIKU, SONNET, OPUS exact strings from spec, no model strings hardcoded anywhere else

## Task Commits

1. **Task 1: Model constants, pydantic schemas, and DB registry** - `957f198` (feat)
2. **Task 2: LLM client with hash-cache and agent_runs write** - `641155f` (feat)

## Files Created

- `pkm/llm/__init__.py` — Package marker
- `pkm/llm/models.py` — HAIKU, SONNET, OPUS constants
- `pkm/llm/client.py` — LLMClient with hash-cache, tool-calling, repair-retry, agent_runs write
- `pkm/store/__init__.py` — Package marker
- `pkm/store/registry.py` — connect() dual-mode libsql with auto-migration
- `pkm/schemas/__init__.py` — Package marker
- `pkm/schemas/source.py` — SourceRecord pydantic model
- `pkm/schemas/claim.py` — ClaimRecord pydantic model
- `pkm/schemas/concept.py` — ConceptRecord pydantic model
- `pkm/schemas/entity.py` — EntityRecord pydantic model
- `pkm/schemas/graph.py` — GraphNodeRecord, GraphEdgeRecord pydantic models
- `pkm/schemas/chunk.py` — ChunkRecord pydantic model
- `pkm/schemas/agent_io.py` — KeyClaim, SummarizerOutput, GraphNode, GraphRelationship, KGAgentOutput

## Decisions Made

- **INSERT OR REPLACE in _write_run**: INSERT OR IGNORE would silently drop an ok-row when a prior error-row exists for the same (agent, input_hash) UNIQUE constraint, causing indefinite re-execution. INSERT OR REPLACE overwrites correctly.
- **Tool-calling for structured output**: uses `tools=[{"name":"structured_output","input_schema":schema.model_json_schema()}]` + `tool_choice={"type":"tool","name":"structured_output"}` which forces the model to respond via the tool, guaranteeing JSON schema enforcement at API level.
- **LLMClient takes explicit conn + api_key**: no Settings singleton inside the client class — keeps it testable in isolation without env vars.
- **Migrations resolved via `__file__`**: `Path(__file__).parent.parent.parent / "migrations" / "sqlite"` — works regardless of cwd, which is important since tests call `os.chdir(tempdir)`.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required for this wave.

## Next Phase Readiness

- Wave 3 (idempotency test) can now import `pkm.store.registry.connect()` and `pkm.llm.client.LLMClient`
- `_check_cache` returns None on empty DB, returns dict on hit — test can mock the ok-row directly via SQL INSERT to verify cache bypass
- All schema imports work: `from pkm.schemas.agent_io import KGAgentOutput` etc.
- Phase 2 agents can import all pydantic schemas from `pkm.schemas.*`

## Threat Surface Scan

No new network endpoints or auth paths introduced. LLMClient receives api_key explicitly from caller — key not logged or stored in agent_runs. The `error` column in agent_runs may contain Anthropic API error messages; Anthropic errors do not echo key material (T-02-01, accepted).

## Self-Check: PASSED

- `pkm/llm/models.py` exists: FOUND
- `pkm/store/registry.py` exists: FOUND
- `pkm/llm/client.py` exists: FOUND
- `pkm/schemas/agent_io.py` exists: FOUND
- Task 1 commit `957f198`: FOUND
- Task 2 commit `641155f`: FOUND
- Verification "ALL OK" printed for both tasks: CONFIRMED

---
*Phase: 01-data-layer-idempotency*
*Completed: 2026-06-15*
