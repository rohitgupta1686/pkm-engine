---
phase: 01-data-layer-idempotency
plan: 03
type: execute
wave: 3
depends_on:
  - "01-01"
  - "01-02"
files_modified:
  - /Users/RohitGupta/code/pkm-engine/tests/__init__.py
  - /Users/RohitGupta/code/pkm-engine/tests/conftest.py
  - /Users/RohitGupta/code/pkm-engine/tests/fixtures/sample_raw.md
  - /Users/RohitGupta/code/pkm-engine/tests/test_idempotency.py
autonomous: true
requirements:
  - DATA-03
  - DATA-04
  - DATA-05
  - DATA-06

must_haves:
  truths:
    - "pytest tests/test_idempotency.py exits 0 with all tests passing"
    - "test_source_dedup: inserting same content_hash twice results in exactly 1 row in sources"
    - "test_raw_path_immutable: attempting to UPDATE sources.raw_path raises an exception with 'immutable' in the message"
    - "test_llm_cache_dedup: calling LLMClient.call() twice with identical inputs and a mocked Anthropic client results in: (a) mock API called exactly once, (b) second call returns cached=True, (c) agent_runs has exactly 1 row"
    - "test_auto_migration: connect() on empty DB creates sources, agent_runs, graph_nodes tables"
    - "test_idempotent_migration: connect() called twice on same DB path raises no exception"
  artifacts:
    - path: "/Users/RohitGupta/code/pkm-engine/tests/conftest.py"
      provides: "db_conn pytest fixture using temp directory + auto-migrated in-memory DB"
    - path: "/Users/RohitGupta/code/pkm-engine/tests/fixtures/sample_raw.md"
      provides: "Sample raw markdown file with front matter for fixture use"
    - path: "/Users/RohitGupta/code/pkm-engine/tests/test_idempotency.py"
      provides: "Five test functions covering all DoD items"
  key_links:
    - from: "tests/conftest.py db_conn fixture"
      to: "pkm.store.registry.connect()"
      via: "calls connect(settings) with Settings pointing to temp file"
      pattern: "from pkm.store.registry import connect"
    - from: "tests/test_idempotency.py test_llm_cache_dedup"
      to: "pkm.llm.client.LLMClient._check_cache"
      via: "inserts row directly into agent_runs then calls _check_cache to verify hit"
      pattern: "_check_cache"
---

<objective>
Write the idempotency test suite that proves all five DoD items. Tests are the final behavioral gate for Phase 1: they either pass or they expose gaps in Wave 1/2 that must be fixed before Phase 2 starts.

Purpose: The test is not a formality — it is the executable contract. If it is green, Wave 1+2 are correct.
Output: pytest tests/test_idempotency.py exits 0 with 5 passing tests.
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
<!-- All components created in Wave 1 + Wave 2 — read the actual files before writing tests -->

From pkm/store/registry.py:
  connect(settings: Settings | None = None) -> libsql_experimental.Connection
  Connection supports: .execute(sql, params), .executescript(sql), .fetchall(), .commit()

From pkm/llm/client.py:
  class LLMClient:
    __init__(self, conn, api_key: str)
    _make_input_hash(agent_name: str, model: str, prompt_version: str, input_text: str) -> str
    _check_cache(agent_name: str, input_hash: str) -> dict | None

From pkm/config.py:
  class Settings(BaseSettings):
    anthropic_api_key: str
    db_path: str = "pkm.db"

From migrations/sqlite/001_init.sql:
  sources INSERT columns: (id, content_hash, type, title, author, url, publisher, date_published, date_saved, raw_path, wiki_path, credibility, tags, status, created_at, updated_at)
  agent_runs INSERT columns: (id, agent, source_id, input_hash, model, tokens_in, tokens_out, cost_usd, status, error, started_at, finished_at)

<!-- DoD items from CONTEXT.md that tests must prove -->

DoD item 1 (DATA-03): Re-ingesting same content_hash = 0 new rows in sources
  Test approach: INSERT a source row. Attempt INSERT again with same content_hash. Catch IntegrityError or similar. Assert COUNT(*) FROM sources = 1.

DoD item 2 (DATA-05): sources_raw_immutable trigger fires on UPDATE OF raw_path
  Test approach: INSERT a source row. Execute UPDATE sources SET raw_path='other' WHERE id=?. Assert exception raised with 'immutable' in message.

DoD item 3 (DATA-04): LLM cache dedup — second call with same input_hash hits cache, 0 API calls
  Test approach: Insert a row into agent_runs with status='ok' and known input_hash. Call LLMClient._check_cache with same agent+input_hash. Assert result is not None (cache hit). This proves the dedup gate works without making a live API call.

DoD item 4 (DATA-06): connect() auto-migrates empty DB
  Test approach: Call connect(settings) on a fresh temp file. Assert 'sources' in tables, 'agent_runs' in tables, 'graph_nodes' in tables.

DoD item 5 (DATA-06 continued): connect() twice on same DB is a no-op
  Test approach: Call connect() twice on same db_path. Assert no exception raised and tables still exist.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Test fixtures — conftest.py, sample_raw.md, tests/__init__.py</name>
  <files>
    /Users/RohitGupta/code/pkm-engine/tests/__init__.py
    /Users/RohitGupta/code/pkm-engine/tests/conftest.py
    /Users/RohitGupta/code/pkm-engine/tests/fixtures/sample_raw.md
  </files>
  <read_first>
    - /Users/RohitGupta/code/pkm-engine/pkm/store/registry.py (read connect() signature before writing fixture)
    - /Users/RohitGupta/code/pkm-engine/pkm/config.py (Settings fields — db_path)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md (decisions: Idempotency Test, Claude's Discretion)
  </read_first>
  <action>
    tests/__init__.py: Empty file.

    tests/conftest.py:
      Import: pytest, tempfile, pathlib, os, from pkm.config import Settings, from pkm.store.registry import connect.

      Define fixture db_conn (scope="function"): Create a tempfile.TemporaryDirectory. Construct db_path = tmp_dir / "test.db" as a string. Create Settings(anthropic_api_key="test-key", db_path=db_path) — do NOT read actual ANTHROPIC_API_KEY from env; hardcode "test-key" so tests run without secrets. Call connect(s) to get conn. Yield conn. Teardown: conn is not explicitly closed (libsql auto-closes with temp dir removal).

      Define fixture sample_content() returning a dict with: content_hash="abc123deadbeef01", raw_path="raw/2026/06/test_article.md", source_id="src_abc123deadbee", type="Article", date_saved="2026-01-01T00:00:00Z", created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z".

    tests/fixtures/sample_raw.md: A minimal raw capture file. Include YAML front matter block (--- delimited) with fields: id, type, source_type, title, author, url, date_saved, content_hash, tags. Body: two short paragraphs of placeholder text (~100 words total). Purpose: used as the canonical input for idempotency tests that simulate re-ingest of identical content.
  </action>
  <verify>
    <automated>cd /Users/RohitGupta/code/pkm-engine && python -m pytest tests/conftest.py --collect-only -q 2>&1 | grep -v "^$"</automated>
  </verify>
  <acceptance_criteria>
    - pytest --collect-only exits 0 (no import errors in conftest)
    - python -c "import tests; from tests.conftest import db_conn" exits 0
    - tests/fixtures/sample_raw.md exists and contains "---" (YAML front matter delimiter): grep -c "^---" tests/fixtures/sample_raw.md returns 2
    - conftest.py contains "anthropic_api_key" and "test-key" (no real key): grep -c "test-key" tests/conftest.py returns at least 1
  </acceptance_criteria>
  <done>Test infrastructure in place; db_conn fixture creates a fresh migrated DB per test function.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Idempotency tests — five DoD-gate tests covering DATA-03, DATA-04, DATA-05, DATA-06</name>
  <files>
    /Users/RohitGupta/code/pkm-engine/tests/test_idempotency.py
  </files>
  <read_first>
    - /Users/RohitGupta/code/pkm-engine/tests/conftest.py (db_conn fixture — read actual implementation)
    - /Users/RohitGupta/code/pkm-engine/pkm/llm/client.py (LLMClient._check_cache and _make_input_hash signatures)
    - /Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql (exact column order for INSERT statements)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md (decisions: Idempotency Test — exact test assertions required)
  </read_first>
  <behavior>
    - test_auto_migration: db_conn fixture table list contains 'sources', 'agent_runs', 'graph_nodes'
    - test_idempotent_migration: calling connect() a second time on same db_path raises no exception and table list is unchanged
    - test_source_dedup: inserting two sources with identical content_hash results in exactly 1 row in sources; second INSERT raises an exception (IntegrityError or similar from UNIQUE constraint)
    - test_raw_path_immutable: after inserting a source row, UPDATE sources SET raw_path='new' raises an exception whose string representation contains 'immutable'
    - test_llm_cache_dedup: mock the Anthropic client; call LLMClient.call() twice with identical (agent_name, model, prompt_version, input_text); assert (a) mock API was invoked exactly once, (b) second call returns {"cached": True}, (c) SELECT COUNT(*) FROM agent_runs returns 1
  </behavior>
  <action>
    Create tests/test_idempotency.py.

    Imports: pytest, from pkm.store.registry import connect, from pkm.config import Settings, from pkm.llm.client import LLMClient.

    Helper _insert_source(conn, source_id, content_hash, raw_path): execute INSERT INTO sources with all NOT NULL columns. Use static values for non-critical fields: type='Article', date_saved='2026-01-01T00:00:00Z', created_at='2026-01-01T00:00:00Z', updated_at='2026-01-01T00:00:00Z'. Commit after insert.

    test_auto_migration(db_conn): Query sqlite_master for table names. Assert 'sources' in names. Assert 'agent_runs' in names. Assert 'graph_nodes' in names. Assert 'graph_edges' in names.

    test_idempotent_migration(tmp_path): Create Settings(anthropic_api_key="test-key", db_path=str(tmp_path/"idempotent.db")). Call connect(s) twice. No exception. After second connect, verify sources still in tables.

    test_source_dedup(db_conn): Call _insert_source(db_conn, "src_aaa111bbb222", "hash_unique_abc", "raw/test.md"). Then attempt second _insert_source with SAME content_hash but different id "src_xxx999yyy888". Wrap second call in pytest.raises(Exception) — accept any exception (libsql may raise different types). Assert SELECT COUNT(*) FROM sources WHERE content_hash='hash_unique_abc' returns exactly 1.

    test_raw_path_immutable(db_conn): Call _insert_source(db_conn, "src_imm111aaa", "hash_immutable_1", "raw/original.md"). Execute try/except: db_conn.execute("UPDATE sources SET raw_path='raw/changed.md' WHERE id='src_imm111aaa'"), db_conn.commit(). In the except block, assert 'immutable' in str(e).lower(). If no exception is raised, call pytest.fail("immutability trigger did not fire").

    test_llm_cache_dedup(db_conn): Use unittest.mock to mock the Anthropic client so no real API call is made.
      from unittest.mock import MagicMock, patch
      Build mock_response = MagicMock(): mock_response.usage.input_tokens = 10, mock_response.usage.output_tokens = 5, mock_response.content = [MagicMock(type="text", text="ok")].
      Use patch("pkm.llm.client.anthropic.Anthropic") as mock_anthropic_cls: mock_anthropic_cls.return_value.messages.create.return_value = mock_response.
      Inside the patch context: instantiate client = LLMClient(conn=db_conn, api_key="test-key"). Call result1 = client.call("reader_agent", "claude-haiku-4-5-20251001", "v1", [{"role": "user", "content": "test"}], input_text="hello world"). Assert result1["cached"] == False.
      Call result2 = client.call("reader_agent", "claude-haiku-4-5-20251001", "v1", [{"role": "user", "content": "test"}], input_text="hello world"). Assert result2["cached"] == True.
      Assert mock_anthropic_cls.return_value.messages.create.call_count == 1 (API called exactly once, not twice).
      Assert db_conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 1 (exactly one row written).
  </action>
  <verify>
    <automated>cd /Users/RohitGupta/code/pkm-engine && python -m pytest tests/test_idempotency.py -v 2>&1</automated>
  </verify>
  <acceptance_criteria>
    - pytest tests/test_idempotency.py exits 0
    - Output shows 5 tests PASSED: test_auto_migration, test_idempotent_migration, test_source_dedup, test_raw_path_immutable, test_llm_cache_dedup
    - No test is marked SKIPPED or XFAIL
    - No warnings about missing fixtures
    - test_raw_path_immutable passes without relying on a specific exception class (catches any Exception and checks for 'immutable' in message)
    - test_llm_cache_dedup: mock API call count == 1, result2["cached"] == True, agent_runs row count == 1
  </acceptance_criteria>
  <done>pytest tests/test_idempotency.py exits 0. All five Phase 1 DoD items proven by automated tests.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| test fixtures → DB | Tests use in-process temp DBs; no network calls, no real API keys |
| conftest.py Settings | api_key hardcoded as "test-key" — must never be replaced with real key in test code |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-03-01 | Information Disclosure | conftest.py api_key | mitigate | api_key hardcoded as "test-key"; grep in CI can confirm no real key in test files |
| T-03-02 | Tampering | test_raw_path_immutable | mitigate | Test explicitly fails if trigger does not fire (pytest.fail call) — not silently passing on missing trigger |
| T-03-SC | Tampering | pytest install | accept | pytest is industry-standard test runner; no exotic install behavior |
</threat_model>

<verification>
Final phase-level verification after Wave 3 completes:

1. cd /Users/RohitGupta/code/pkm-engine && pytest tests/test_idempotency.py -v
   Expected: 5 passed, 0 failed, 0 errors

2. Trigger check: grep -c "sources_raw_immutable" migrations/sqlite/001_init.sql
   Expected: 1

3. Auto-migration check: python -c "
   import tempfile, os
   from pkm.config import Settings
   from pkm.store.registry import connect
   with tempfile.TemporaryDirectory() as d:
       s = Settings(anthropic_api_key='x', db_path=d+'/fresh.db')
       conn = connect(s)
       tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
       assert 'sources' in tables
       assert 'agent_runs' in tables
       print('migration ok')
   "
   Expected: prints "migration ok"

4. Model constants check: python -c "from pkm.llm.models import HAIKU; assert HAIKU=='claude-haiku-4-5-20251001'"
   Expected: exits 0

5. Full import check: python -c "
   from pkm.config import settings
   from pkm.llm.models import HAIKU, SONNET, OPUS
   from pkm.llm.client import LLMClient
   from pkm.store.registry import connect
   from pkm.schemas.agent_io import KeyClaim, SummarizerOutput, KGAgentOutput
   from pkm.schemas.source import SourceRecord
   from pkm.schemas.graph import GraphNodeRecord
   print('all imports ok')
   "
   Expected: prints "all imports ok"
</verification>

<success_criteria>
- pytest tests/test_idempotency.py exits 0 (5 tests pass)
- sources table has raw_path immutability trigger (test_raw_path_immutable proves it fires)
- connect() auto-runs both migration files on empty DB (test_auto_migration proves tables exist)
- Re-inserting same content_hash = exactly 1 row (test_source_dedup proves constraint)
- LLM cache hit returns non-None after matching agent_run row inserted (test_llm_cache_dedup proves dedup gate)
</success_criteria>

<output>
Create /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-03-SUMMARY.md when done.
</output>
