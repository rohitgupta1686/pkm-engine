# Phase 1: Data Layer + Idempotency — Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Source:** Synthesized from PKM_Build_Plan_for_Claude_Code.md, PKM_TECHNICAL_SPECIFICATION.md, PKM Cloud Architecture.md

<domain>
## Phase Boundary

Phase 1 delivers the foundational data layer for the pkm-engine repo: the Turso (libSQL) schema, pydantic models, and the LLM hash-cache that makes re-ingest free. Nothing captures, nothing processes, nothing writes wiki pages yet — this phase is infrastructure only. The sole behavioral proof is that re-ingesting an identical source produces zero new DB rows and zero new LLM calls.

**Working in:** `~/code/pkm-engine` (public GitHub repo, no secrets)
**Not yet:** GitHub Actions, Cloudflare Workers, vault content, agents that call Claude

</domain>

<decisions>
## Implementation Decisions

### Repository Bootstrap
- pyproject.toml with `pkm` as the installable package (`pip install -e .`)
- Python 3.11 target
- `.env.example` (not `.env`) listing: ANTHROPIC_API_KEY, TURSO_URL, TURSO_TOKEN, CF_ACCOUNT_ID, CF_API_TOKEN
- `README.md` covering repo purpose and setup

### Database Connection (settled — cloud doc §6.1)
- Library: `libsql-experimental` (`pip install libsql-experimental`)
- Dual-mode: if `TURSO_URL` env var set → connect to Turso cloud; else → connect to local `pkm.db` SQLite file
- Connection lives in `pkm/store/registry.py` (single connect() function)
- ALL DDL from spec runs unchanged against both modes

### Schema (settled — tech spec §2)
**`migrations/sqlite/001_init.sql`** must include exactly:
- `sources` table: id TEXT PK (src_<sha256[:12]>), content_hash TEXT NOT NULL UNIQUE, type CHECK, title, author, url, publisher, date_published, date_saved NOT NULL, raw_path NOT NULL, wiki_path, credibility REAL DEFAULT 0.5, tags TEXT (JSON array), status CHECK ('captured','summarized','extracted','linked','done','error'), created_at, updated_at
- `chunks` table: id, source_id FK, ordinal INT, char_start, char_end, token_count, text, UNIQUE(source_id, ordinal)
- `summaries` table: source_id PK FK, thesis, body NOT NULL, model, confidence, created_at
- `claims` table: id (clm_<uuid7>), source_id FK, chunk_id FK, statement, subject, predicate, object, claim_type CHECK, confidence DEFAULT 0.5, status CHECK ('candidate','approved','merged','rejected'), valid_from, valid_to, created_at
- `concepts` table: id (cpt_<slug>), name, definition, domain, wiki_path, created_at, updated_at
- `concept_aliases` table: alias, concept_id FK, PRIMARY KEY (alias, concept_id)
- `claim_concepts` table: claim_id FK, concept_id FK, PRIMARY KEY
- `entities` table: id (ent_<type>_<slug>), type, name, properties TEXT (JSON), wiki_path, created_at, updated_at, UNIQUE(type, name)
- `entity_aliases` table: alias, entity_id FK, PRIMARY KEY
- `agent_runs` table: id, agent, source_id, input_hash NOT NULL, model, tokens_in, tokens_out, cost_usd, status NOT NULL, error, started_at, finished_at, UNIQUE(agent, input_hash)
- `embeddings_meta` table: object_id PK, object_kind, collection, model, dim, updated_at
- `claims_fts` VIRTUAL TABLE USING fts5(statement, content='claims', content_rowid='rowid')
- PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;
- All indexes from spec: idx_sources_status, idx_sources_type, idx_chunks_source, idx_claims_source

**Raw-immutability trigger** (CRITICAL — DoD depends on this):
```sql
CREATE TRIGGER sources_raw_immutable
BEFORE UPDATE OF raw_path ON sources
BEGIN
  SELECT RAISE(ABORT, 'raw_path is immutable after write');
END;
```

**`migrations/sqlite/002_graph_tables.sql`** must include:
- `graph_nodes`: id PK, label NOT NULL, name NOT NULL, properties TEXT (JSON), confidence REAL DEFAULT 0.5, provenance TEXT (JSON array), created_at, updated_at
- `graph_edges`: id PK, src FK→graph_nodes, dst FK→graph_nodes, type NOT NULL, description, strength INT CHECK(1..10), confidence REAL DEFAULT 0.5, provenance TEXT (JSON array), created_at, updated_at
- Indexes: idx_nodes_label, idx_edges_src, idx_edges_dst, idx_edges_type

### Schema Auto-Migration
- `registry.py` runs `001_init.sql` and `002_graph_tables.sql` on every startup using IF NOT EXISTS guards
- Migration is idempotent: running twice against an existing schema is a no-op

### Model String Constants (settled — tech spec §5.2)
- `pkm/llm/models.py`: `HAIKU = "claude-haiku-4-5-20251001"`, `SONNET = "claude-sonnet-4-6"`, `OPUS = "claude-opus-4-8"`
- No magic strings elsewhere — all model references use these constants

### LLM Client + Hash Cache (settled — AD-3, cloud doc §8)
- `pkm/llm/client.py` wraps Anthropic SDK
- Cache key: `sha256(agent_name + model + prompt_version + input_text)` as hex string
- Before every LLM call: check `agent_runs` for row with matching `input_hash` and `status='ok'` → if found, return cached (skip API call, 0 tokens)
- After every LLM call: write to `agent_runs` (agent, input_hash, model, tokens_in, tokens_out, cost_usd, status, started_at, finished_at)
- Structured output via tool-calling (strict JSON schema) — not raw text completion
- One repair-retry on schema-invalid response
- Retries: exponential backoff on 429/529 (rate limit / overload)

### Pydantic Models (settled — tech spec §6.1)
`pkm/schemas/agent_io.py` must define at minimum:
- `KeyClaim(BaseModel)`: statement, subject|None, predicate|None, object|None, claim_type Literal, chunk_id str, confidence float ge=0 le=1
- `SummarizerOutput(BaseModel)`: thesis str, key_claims list[KeyClaim], caveats list[str], summary_confidence float
- `GraphNode(BaseModel)`: id, label, name, properties dict={}, confidence float, provenance list[str]
- `GraphRelationship(BaseModel)`: src, dst, type, description, strength int ge=1 le=10, confidence float, provenance list[str]
- `KGAgentOutput(BaseModel)`: nodes list[GraphNode], relationships list[GraphRelationship]

`pkm/schemas/source.py`, `claim.py`, `concept.py`, `entity.py`, `graph.py`: pydantic models mirroring the SQL schema for use as app-level types

### Config (pydantic-settings)
`pkm/config.py` with `class Settings(BaseSettings)`:
- `anthropic_api_key: str`
- `turso_url: str = ""` (empty = local SQLite)
- `turso_token: str = ""`
- `cf_account_id: str = ""`
- `cf_api_token: str = ""`
- `db_path: str = "pkm.db"` (local fallback path)
- Reads from `.env` file automatically

### Idempotency Test (DoD gate)
`tests/test_idempotency.py` must:
1. Create a test source with known content_hash
2. Insert via `sources` table
3. Attempt to insert same content_hash again → assert unique constraint prevents second row
4. Simulate two LLM call attempts with same input_hash → assert second call hits cache, makes 0 API calls
5. Assert `agent_runs` has exactly 1 row after two identical call attempts

### Claude's Discretion
- Project layout details beyond what's specified (conftest.py structure, test fixtures format)
- Specific retry backoff parameters (reasonable defaults)
- Whether to use pytest-asyncio or sync tests
- Internal helper utilities in registry.py

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema Authority
- `PKM_TECHNICAL_SPECIFICATION.md §2` — Full DDL (sources, chunks, summaries, claims, concepts, entities, agent_runs, graph tables)
- `PKM Cloud Architecture.md §6` — libSQL connection pattern (the ONLY change from local SQLite)

### Model Constants
- `PKM_TECHNICAL_SPECIFICATION.md §5.2` — Exact model strings: claude-haiku-4-5-20251001, claude-sonnet-4-6, claude-opus-4-8

### Hash Cache Design
- `PKM Cloud Architecture.md §8` — LLM cost minimization: hash cache is item #1; AD-3 (hash every call)
- `PKM_TECHNICAL_SPECIFICATION.md §5.2` — "hash (agent, prompt_version, input); skip if agent_runs has matching ok row"

### Agent I/O Schemas
- `PKM_TECHNICAL_SPECIFICATION.md §6.1` — Pydantic class definitions (copy exactly, including field constraints)

### Idempotency Contract
- `PKM_Build_Plan_for_Claude_Code.md §2` — "Idempotency is sacred. The content-hash LLM cache and write-once raw/ are gates, not nice-to-haves."
- `PKM_TECHNICAL_SPECIFICATION.md §10` — test_idempotency.py requirement in test strategy

</canonical_refs>

<specifics>
## Specific Ideas

- Use `uuid7` for clm_ IDs (time-ordered UUIDs) — import from `uuid7` package or implement as timestamp-based UUID
- `cpt_<slug>` IDs: slug is kebab-case of concept name, lowercase
- `src_<hash12>`: first 12 chars of sha256 hex of normalized content
- Keep large text OUT of Turso — `chunks.text` is an exception but chunk size is bounded (1200 tokens ≈ ~4800 chars); summaries.body (markdown) is also stored but is short
- FTS5 virtual table needs a content= reference to the physical claims table for the tokenizer to work
- For local dev, the local SQLite file (`pkm.db`) should be in `.gitignore`

</specifics>

<deferred>
## Deferred Ideas

- Chroma vector store — V1 only
- Neo4j migration — V2 only
- Embedded Turso replica — V1 optimization (noted in cloud doc §6.2)
- Three-tier entity resolution embedding tier — stubbed in Phase 2; not in Phase 1
- FastAPI routes — not needed until Phase 3

</deferred>

---
*Phase: 01-data-layer-idempotency*
*Context gathered: 2026-06-15 via document synthesis (PKM build plan + tech spec + cloud architecture)*
