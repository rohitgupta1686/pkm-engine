---
phase: 01-data-layer-idempotency
plan: 02
type: execute
wave: 2
depends_on:
  - "01-01"
files_modified:
  - /Users/RohitGupta/code/pkm-engine/pkm/llm/__init__.py
  - /Users/RohitGupta/code/pkm-engine/pkm/llm/models.py
  - /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py
  - /Users/RohitGupta/code/pkm-engine/pkm/store/__init__.py
  - /Users/RohitGupta/code/pkm-engine/pkm/store/registry.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/__init__.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/source.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/claim.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/concept.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/entity.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/graph.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/chunk.py
  - /Users/RohitGupta/code/pkm-engine/pkm/schemas/agent_io.py
autonomous: true
requirements:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-04
  - DATA-05
  - DATA-06
  - DATA-07
  - DATA-08
  - DATA-09

must_haves:
  truths:
    - "pkm.llm.models exports HAIKU, SONNET, OPUS with exact model string values from spec"
    - "registry.connect() with no TURSO_URL opens local pkm.db file using libsql_experimental"
    - "registry.connect() with TURSO_URL set connects to Turso cloud with auth_token"
    - "registry.connect() auto-runs both migration files on startup; second run is idempotent"
    - "LLMClient.call() checks agent_runs for a matching (agent, input_hash) ok row before hitting the API"
    - "LLMClient.call() writes agent, input_hash, model, tokens_in, tokens_out, cost_usd, status to agent_runs after a live call"
    - "cache key is sha256(agent_name + model + prompt_version + input_text) as a hex string"
    - "All pydantic schemas import without error and field constraints match spec exactly"
  artifacts:
    - path: "/Users/RohitGupta/code/pkm-engine/pkm/llm/models.py"
      provides: "HAIKU, SONNET, OPUS string constants"
      exports: ["HAIKU", "SONNET", "OPUS"]
    - path: "/Users/RohitGupta/code/pkm-engine/pkm/store/registry.py"
      provides: "connect() function returning libsql connection with auto-migration"
      exports: ["connect"]
    - path: "/Users/RohitGupta/code/pkm-engine/pkm/llm/client.py"
      provides: "LLMClient with hash-cache and agent_runs write"
      exports: ["LLMClient"]
    - path: "/Users/RohitGupta/code/pkm-engine/pkm/schemas/agent_io.py"
      provides: "KeyClaim, SummarizerOutput, GraphNode, GraphRelationship, KGAgentOutput pydantic models"
      exports: ["KeyClaim", "SummarizerOutput", "GraphNode", "GraphRelationship", "KGAgentOutput"]
  key_links:
    - from: "pkm/store/registry.py connect()"
      to: "migrations/sqlite/001_init.sql"
      via: "reads and executes migration file content using pathlib + conn.executescript()"
      pattern: "executescript.*001_init"
    - from: "pkm/llm/client.py LLMClient.call()"
      to: "agent_runs table"
      via: "SELECT before API call (cache check), INSERT after (write result)"
      pattern: "SELECT.*agent_runs.*input_hash"
    - from: "pkm/llm/client.py"
      to: "pkm/llm/models.py"
      via: "imports HAIKU, SONNET, OPUS — no model strings hardcoded in client.py"
      pattern: "from pkm.llm.models import"
---

<objective>
Implement the three runtime components that Wave 3 tests will exercise: model constants, DB registry with auto-migration, and the LLM client with hash-cache. Also define all pydantic schemas so Phase 2 agents can import them directly.

Purpose: These are the contracts everything else builds on. The idempotency test requires a working registry (to run migrations and query agent_runs) and a working LLMClient (to verify cache hits).
Output: pkm.store.registry.connect(), pkm.llm.client.LLMClient, pkm.llm.models constants, all schemas.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/ROADMAP.md
@/Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md

Working directory for all file creation: /Users/RohitGupta/code/pkm-engine

<interfaces>
<!-- Produced by Wave 1 — executor must import from these -->

From pkm/config.py (created in Wave 1):
  class Settings(BaseSettings):
    anthropic_api_key: str
    turso_url: str = ""
    turso_token: str = ""
    db_path: str = "pkm.db"
  settings = Settings()   # module-level singleton

From migrations/sqlite/001_init.sql (created in Wave 1):
  agent_runs table columns: id, agent, source_id, input_hash, model, tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at
  UNIQUE(agent, input_hash) constraint exists

From migrations/sqlite/002_graph_tables.sql (created in Wave 1):
  graph_nodes, graph_edges tables exist

<!-- Exact values required from spec -->

llm/models.py constants (exact strings — do not paraphrase):
  HAIKU = "claude-haiku-4-5-20251001"
  SONNET = "claude-sonnet-4-6"
  OPUS = "claude-opus-4-8"

cache key formula (exact):
  hashlib.sha256((agent_name + model + prompt_version + input_text).encode()).hexdigest()

LLMClient.call() signature (minimum):
  def call(self, agent_name: str, model: str, prompt_version: str, messages: list[dict], input_text: str, source_id: str | None = None, output_schema: type[BaseModel] | None = None) -> dict

registry.connect() signature:
  def connect(settings: Settings | None = None) -> libsql_experimental.Connection

Pydantic schemas from spec §6.1 (copy exactly):
  KeyClaim fields: statement: str, subject: str | None, predicate: str | None, object: str | None,
                   claim_type: Literal["fact","opinion","prediction","definition","causal","statistic"],
                   chunk_id: str, confidence: float = Field(ge=0, le=1)
  SummarizerOutput fields: thesis: str, key_claims: list[KeyClaim], caveats: list[str],
                            summary_confidence: float = Field(ge=0, le=1)
  GraphNode fields: id: str, label: str, name: str, properties: dict = {}, confidence: float = Field(ge=0, le=1),
                    provenance: list[str]
  GraphRelationship fields: src: str, dst: str, type: str, description: str,
                             strength: int = Field(ge=1, le=10), confidence: float = Field(ge=0, le=1),
                             provenance: list[str]
  KGAgentOutput fields: nodes: list[GraphNode], relationships: list[GraphRelationship]
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Model constants, pydantic schemas, and DB registry with auto-migration</name>
  <files>
    /Users/RohitGupta/code/pkm-engine/pkm/llm/__init__.py
    /Users/RohitGupta/code/pkm-engine/pkm/llm/models.py
    /Users/RohitGupta/code/pkm-engine/pkm/store/__init__.py
    /Users/RohitGupta/code/pkm-engine/pkm/store/registry.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/__init__.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/source.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/claim.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/concept.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/entity.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/graph.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/chunk.py
    /Users/RohitGupta/code/pkm-engine/pkm/schemas/agent_io.py
  </files>
  <read_first>
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md (decisions: Model Constants, Schema Auto-Migration, Pydantic Models)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/PKM_TECHNICAL_SPECIFICATION.md §6.1 (pydantic class definitions — copy exactly)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/PKM Cloud Architecture.md §6.1 (libSQL connect() pattern — the ONLY change from local SQLite)
    - /Users/RohitGupta/code/pkm-engine/pkm/config.py (Settings class — read before using it)
    - /Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql (confirms agent_runs columns)
  </read_first>
  <action>
    pkm/llm/__init__.py: Empty (just a package marker).

    pkm/llm/models.py: Three constants only. HAIKU = "claude-haiku-4-5-20251001", SONNET = "claude-sonnet-4-6", OPUS = "claude-opus-4-8". No other code in this file.

    pkm/store/__init__.py: Empty.

    pkm/store/registry.py: Import libsql_experimental as libsql, pathlib.Path, and Settings from pkm.config. Define connect(settings: Settings | None = None) function. If settings is None, import and use the module-level singleton from pkm.config. Connection logic: if settings.turso_url is truthy, call libsql.connect(database=settings.turso_url, auth_token=settings.turso_token); else call libsql.connect(settings.db_path). After connecting, call _run_migrations(conn) which: resolves the migrations directory relative to this file as Path(__file__).parent.parent.parent / "migrations" / "sqlite", then executes 001_init.sql and 002_graph_tables.sql in order using conn.executescript(path.read_text()). Return the connection. Do not raise exceptions from migration runs when IF NOT EXISTS guards are present. Also export a get_migrations_dir() helper returning the Path for use in tests.

    pkm/schemas/__init__.py: Empty.

    pkm/schemas/source.py: SourceRecord(BaseModel) mirroring the sources table. Fields: id: str, content_hash: str, type: str, title: str | None = None, author: str | None = None, url: str | None = None, publisher: str | None = None, date_published: str | None = None, date_saved: str, raw_path: str, wiki_path: str | None = None, credibility: float = 0.5, tags: list[str] = [], status: str = "captured", created_at: str, updated_at: str.

    pkm/schemas/claim.py: ClaimRecord(BaseModel) mirroring claims table. Fields: id: str, source_id: str, chunk_id: str | None = None, statement: str, subject: str | None = None, predicate: str | None = None, object: str | None = None, claim_type: str | None = None, confidence: float = 0.5, status: str = "candidate", valid_from: str | None = None, valid_to: str | None = None, created_at: str.

    pkm/schemas/concept.py: ConceptRecord(BaseModel) mirroring concepts table. Fields: id: str, name: str, definition: str | None = None, domain: str | None = None, wiki_path: str, created_at: str, updated_at: str.

    pkm/schemas/entity.py: EntityRecord(BaseModel) mirroring entities table. Fields: id: str, type: str, name: str, properties: dict = {}, wiki_path: str | None = None, created_at: str, updated_at: str.

    pkm/schemas/graph.py: GraphNodeRecord(BaseModel) and GraphEdgeRecord(BaseModel) mirroring graph_nodes and graph_edges tables. GraphNodeRecord fields: id: str, label: str, name: str, properties: dict = {}, confidence: float = 0.5, provenance: list[str] = [], created_at: str, updated_at: str. GraphEdgeRecord fields: id: str, src: str, dst: str, type: str, description: str | None = None, strength: int | None = None, confidence: float = 0.5, provenance: list[str] = [], created_at: str, updated_at: str.

    pkm/schemas/chunk.py: ChunkRecord(BaseModel) mirroring the chunks table. Fields: id: str, source_id: str, ordinal: int, char_start: int | None = None, char_end: int | None = None, token_count: int | None = None, text: str.

    pkm/schemas/agent_io.py: Define KeyClaim, SummarizerOutput, GraphNode, GraphRelationship, KGAgentOutput exactly as in spec §6.1 (see interfaces block for exact field definitions). Import: from pydantic import BaseModel, Field; from typing import Literal.
  </action>
  <verify>
    <automated>cd /Users/RohitGupta/code/pkm-engine && python -c "
from pkm.llm.models import HAIKU, SONNET, OPUS
assert HAIKU == 'claude-haiku-4-5-20251001', f'got {HAIKU}'
assert SONNET == 'claude-sonnet-4-6', f'got {SONNET}'
assert OPUS == 'claude-opus-4-8', f'got {OPUS}'

from pkm.schemas.agent_io import KeyClaim, SummarizerOutput, GraphNode, GraphRelationship, KGAgentOutput
kc = KeyClaim(statement='test', claim_type='fact', chunk_id='chk_1', confidence=0.8)
assert kc.subject is None

from pkm.schemas.source import SourceRecord
from pkm.schemas.graph import GraphNodeRecord, GraphEdgeRecord

import os, tempfile, pathlib
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    from pkm.config import Settings
    s = Settings(anthropic_api_key='dummy', db_path=str(pathlib.Path(d) / 'test.db'))
    from pkm.store.registry import connect
    conn = connect(s)
    tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
    assert 'sources' in tables, f'missing sources, got {tables}'
    assert 'graph_nodes' in tables, f'missing graph_nodes'
    # second connect is idempotent
    conn2 = connect(s)
    print('ALL OK')
"</automated>
  </verify>
  <acceptance_criteria>
    - Script above prints "ALL OK" with exit code 0
    - HAIKU == "claude-haiku-4-5-20251001" exactly
    - SONNET == "claude-sonnet-4-6" exactly
    - OPUS == "claude-opus-4-8" exactly
    - KeyClaim(statement="s", claim_type="fact", chunk_id="c", confidence=0.5) instantiates with no error
    - KeyClaim(statement="s", claim_type="fact", chunk_id="c", confidence=1.5) raises ValidationError (confidence > 1)
    - connect(settings) against fresh empty file creates tables including sources, agent_runs, graph_nodes
    - connect(settings) called twice on same file raises no error (IF NOT EXISTS idempotency confirmed)
    - grep -c "from pkm.llm.models import" /Users/RohitGupta/code/pkm-engine/pkm/store/registry.py returns 0 (registry does not import models — only config and libsql)
  </acceptance_criteria>
  <done>All schemas importable, model constants exact, connect() auto-migrates and is idempotent.</done>
</task>

<task type="auto">
  <name>Task 2: LLM client with hash-cache and agent_runs write</name>
  <files>
    /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py
  </files>
  <read_first>
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md (decisions: LLM Client + Hash Cache)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/PKM Cloud Architecture.md §8 (hash cache design — item #1)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/PKM_TECHNICAL_SPECIFICATION.md §5.2 (idempotency: hash agent+prompt_version+input; skip if ok row exists)
    - /Users/RohitGupta/code/pkm-engine/pkm/llm/models.py (read actual constants before referencing)
    - /Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql (read agent_runs column list)
  </read_first>
  <action>
    Create pkm/llm/client.py.

    Imports: hashlib, uuid, datetime, time, json, from typing import Any, from pydantic import BaseModel, ValidationError, import anthropic, from pkm.llm.models import HAIKU, SONNET, OPUS (import but use for type hints/defaults only — caller passes model string).

    LLMClient class:
      __init__(self, conn, api_key: str): stores self.conn and self.client = anthropic.Anthropic(api_key=api_key).

      _make_input_hash(self, agent_name: str, model: str, prompt_version: str, input_text: str) -> str:
        return hashlib.sha256((agent_name + model + prompt_version + input_text).encode()).hexdigest()

      _check_cache(self, agent_name: str, input_hash: str) -> dict | None:
        Query agent_runs: SELECT id, status FROM agent_runs WHERE agent = ? AND input_hash = ? AND status = 'ok'. Return the first row as a dict {"id": ..., "status": ...} if found, else None. This is the dedup gate.

      _write_run(self, run_id: str, agent_name: str, source_id: str | None, input_hash: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float, status: str, error: str | None, started_at: str, finished_at: str) -> None:
        Use INSERT OR REPLACE INTO agent_runs (id, agent, source_id, input_hash, model, tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?). Commit.
        Rationale: INSERT OR REPLACE ensures that a successful ok-row overwrites a prior error-row for the same (agent, input_hash). INSERT OR IGNORE would silently drop the ok-row if an error-row already exists, causing indefinite re-execution.

      _call_api(self, model: str, messages: list[dict], output_schema: type[BaseModel] | None) -> tuple[object, int, int]:
        Build kwargs = {"model": model, "max_tokens": 4096, "messages": messages}.
        If output_schema is not None: build tool definition as {"name": "structured_output", "description": f"Return output matching the {output_schema.__name__} schema", "input_schema": output_schema.model_json_schema()}. Add tools=[tool_def] and tool_choice={"type": "tool", "name": "structured_output"} to kwargs.
        Call self.client.messages.create(**kwargs) with exponential backoff: wrap in a for loop (range(3)). On anthropic.APIStatusError where status_code in (429, 529), sleep 2**attempt seconds and continue. On other exceptions, raise immediately.
        Return (response, response.usage.input_tokens, response.usage.output_tokens).

      _extract_result(self, response: object, output_schema: type[BaseModel] | None, messages: list[dict], model: str) -> Any:
        If output_schema is None: find first content block with type == "text", return its text.
        If output_schema is not None:
          Find the tool_use content block (type == "tool_use", name == "structured_output"). Extract block.input as raw_data (dict).
          Try: return output_schema(**raw_data) (validated pydantic object).
          On ValidationError as first_err:
            Build repair messages: append {"role": "assistant", "content": response.content} and {"role": "user", "content": f"Your response failed schema validation: {first_err}. Fix it and call structured_output again."}.
            Call self.client.messages.create(model=model, max_tokens=4096, messages=messages + repair_messages, tools=[same tool], tool_choice=same) — one retry only, no further retries on second failure.
            Extract tool_use block from repair response, try output_schema(**repair_data). If this also raises ValidationError, raise it (do not retry again).

      call(self, agent_name: str, model: str, prompt_version: str, messages: list[dict], input_text: str, source_id: str | None = None, output_schema: type[BaseModel] | None = None) -> dict:
        1. input_hash = _make_input_hash(agent_name, model, prompt_version, input_text).
        2. cached = _check_cache(agent_name, input_hash). If cached is not None, return {"cached": True, "input_hash": input_hash}.
        3. started_at = datetime.datetime.utcnow().isoformat() + "Z".
        4. Try:
           response, tokens_in, tokens_out = _call_api(model, messages, output_schema).
           result = _extract_result(response, output_schema, messages, model).
           cost_usd = 0.0  # placeholder; exact pricing not hardcoded.
           finished_at = datetime.datetime.utcnow().isoformat() + "Z".
           run_id = "run_" + uuid.uuid4().hex[:20].
           _write_run(run_id, agent_name, source_id, input_hash, model, tokens_in, tokens_out, cost_usd, "ok", None, started_at, finished_at).
           return {"cached": False, "input_hash": input_hash, "result": result, "tokens_in": tokens_in, "tokens_out": tokens_out}.
        5. Except Exception as e:
           finished_at = datetime.datetime.utcnow().isoformat() + "Z".
           run_id = "run_" + uuid.uuid4().hex[:20].
           _write_run(run_id, agent_name, source_id, input_hash, model, 0, 0, 0.0, "error", str(e), started_at, finished_at).
           raise.

    Do NOT import or use settings singleton inside LLMClient — caller passes conn and api_key explicitly. This keeps it testable without env vars.
  </action>
  <verify>
    <automated>cd /Users/RohitGupta/code/pkm-engine && python -c "
from pkm.llm.client import LLMClient
import hashlib
# Verify hash formula matches spec
h = hashlib.sha256(('reader_agent' + 'claude-haiku-4-5-20251001' + 'v1' + 'hello world').encode()).hexdigest()
assert len(h) == 64, 'hash should be 64-char hex'

# Verify client instantiates (no API call)
import libsql_experimental as libsql, pathlib, tempfile, os
with tempfile.TemporaryDirectory() as d:
    from pkm.config import Settings
    s = Settings(anthropic_api_key='dummy', db_path=str(d+'/t.db'))
    from pkm.store.registry import connect
    conn = connect(s)
    client = LLMClient(conn=conn, api_key='dummy')
    assert hasattr(client, '_make_input_hash')
    assert hasattr(client, '_check_cache')
    assert hasattr(client, '_write_run')
    assert hasattr(client, 'call')

    # Verify cache check returns None on empty DB
    result = client._check_cache('test_agent', h)
    assert result is None, f'expected None, got {result}'
    print('ALL OK')
"</automated>
  </verify>
  <acceptance_criteria>
    - Script above prints "ALL OK" with exit code 0
    - LLMClient(conn=conn, api_key="dummy") instantiates without importing ANTHROPIC_API_KEY from env
    - _make_input_hash("a","b","c","d") returns sha256("abcd") as 64-char hex string
    - _check_cache on empty agent_runs table returns None
    - grep -c "def _make_input_hash" /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py returns 1
    - grep -c "sha256" /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py returns at least 1
    - grep -c "INSERT.*agent_runs\|_write_run" /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py returns at least 2 (cache check path and write path)
    - No hardcoded model strings in client.py: grep -v "^#\|^from\|^import" /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py | grep -c "claude-" returns 0
  </acceptance_criteria>
  <done>LLMClient with hash-cache dedup and agent_runs write is implemented and structurally verifiable without live API calls.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| LLMClient → Anthropic API | API key passed explicitly; must not be logged or stored in agent_runs |
| agent_runs.input_hash | Hash of prompt content; content is not stored — only the hash |
| libsql connect() | auth_token passed to cloud; local path trusts filesystem |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-01 | Information Disclosure | LLMClient._write_run | mitigate | error field in agent_runs may contain API error messages; these should not include key material — Anthropic errors do not echo keys |
| T-02-02 | Tampering | agent_runs UNIQUE constraint | mitigate | INSERT OR IGNORE prevents duplicate run records; cache check uses AND status='ok' so error rows don't suppress retries |
| T-02-03 | Denial of Service | exponential backoff on 429 | accept | 3 retries max with 2^n backoff is bounded; caller can set timeout externally |
| T-02-SC | Tampering | anthropic pip install | accept | anthropic is the official Anthropic Python SDK; well-established PyPI package |
</threat_model>

<verification>
After both tasks complete:
1. python -c "from pkm.llm.models import HAIKU, SONNET, OPUS; assert HAIKU=='claude-haiku-4-5-20251001'" exits 0
2. python -c "from pkm.schemas.agent_io import KGAgentOutput" exits 0
3. connect(settings) on fresh DB creates all tables including agent_runs and graph_nodes
4. LLMClient._check_cache returns None on empty agent_runs
5. All schema files importable without ValidationError at import time
</verification>

<success_criteria>
- Model constants match spec exactly (verified by assertion)
- connect() auto-migrates and is idempotent
- LLMClient hash formula matches sha256(agent+model+prompt_version+input) spec
- _check_cache returns None on miss; caller flow can avoid API call on hit
- All pydantic schemas import cleanly with correct field constraints
</success_criteria>

<output>
Create /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-02-SUMMARY.md when done.
</output>
