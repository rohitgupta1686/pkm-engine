---
phase: 01-data-layer-idempotency
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - /Users/RohitGupta/code/pkm-engine/pyproject.toml
  - /Users/RohitGupta/code/pkm-engine/.env.example
  - /Users/RohitGupta/code/pkm-engine/README.md
  - /Users/RohitGupta/code/pkm-engine/.gitignore
  - /Users/RohitGupta/code/pkm-engine/pkm/__init__.py
  - /Users/RohitGupta/code/pkm-engine/pkm/config.py
  - /Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql
  - /Users/RohitGupta/code/pkm-engine/migrations/sqlite/002_graph_tables.sql
autonomous: true
requirements:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-05
  - DATA-06
  - DATA-07
  - DATA-08
  - DATA-09

must_haves:
  truths:
    - "Running 001_init.sql against an empty DB creates all core tables without error"
    - "Running 002_graph_tables.sql creates graph_nodes and graph_edges without error"
    - "Running both migration files a second time against an existing schema is a no-op (IF NOT EXISTS)"
    - "sources table has a BEFORE UPDATE OF raw_path trigger that raises ABORT"
    - "agent_runs has UNIQUE(agent, input_hash) constraint"
    - "content_hash column on sources has a UNIQUE constraint"
    - "pkm package is installable via pip install -e ."
    - "Settings class reads TURSO_URL, TURSO_TOKEN, ANTHROPIC_API_KEY from env/dotenv"
  artifacts:
    - path: "/Users/RohitGupta/code/pkm-engine/pyproject.toml"
      provides: "Installable pkm package declaration with all Phase 1 dependencies"
    - path: "/Users/RohitGupta/code/pkm-engine/pkm/config.py"
      provides: "pydantic-settings Settings class with dual-mode DB config"
    - path: "/Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql"
      provides: "Full core schema DDL including raw_path immutability trigger"
    - path: "/Users/RohitGupta/code/pkm-engine/migrations/sqlite/002_graph_tables.sql"
      provides: "graph_nodes and graph_edges DDL"
  key_links:
    - from: "pkm/config.py"
      to: ".env / environment"
      via: "pydantic-settings BaseSettings reads from .env file automatically"
      pattern: "class Settings.*BaseSettings"
    - from: "migrations/sqlite/001_init.sql"
      to: "sources table"
      via: "BEFORE UPDATE OF raw_path trigger"
      pattern: "CREATE TRIGGER sources_raw_immutable"
---

<objective>
Bootstrap the pkm-engine repo: create the installable Python package, pydantic-settings config, and run both migration SQL files that define the full schema. This is the foundation every other plan depends on.

Purpose: Without this, nothing in Wave 2 or 3 can run — no DB connections, no schema, no importable pkm module.
Output: Installable pkm package, Settings class, two migration files with complete DDL, raw_path immutability trigger.
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
<!-- Key constraints from CONTEXT.md decisions section — executor must honor these exactly -->

From 01-CONTEXT.md (D-decisions):

pyproject.toml constraints:
  - package name: pkm
  - python_requires: ">=3.11"
  - dependencies must include: libsql-experimental, pydantic>=2.0, pydantic-settings>=2.0, anthropic>=0.25, pytest, python-dotenv
  - entry point: pkm = "pkm.cli:app" (cli not built in this phase; declare it anyway)

pkm/config.py Settings fields (exact names required):
  anthropic_api_key: str
  turso_url: str = ""          # empty string = local SQLite mode
  turso_token: str = ""
  cf_account_id: str = ""
  cf_api_token: str = ""
  db_path: str = "pkm.db"      # local fallback path
  model_config: reads from .env file automatically (env_file=".env")

001_init.sql PRAGMA lines (must be first two lines):
  PRAGMA journal_mode = WAL;
  PRAGMA foreign_keys = ON;

Immutability trigger (exact SQL — this is DoD):
  CREATE TRIGGER sources_raw_immutable
  BEFORE UPDATE OF raw_path ON sources
  BEGIN
    SELECT RAISE(ABORT, 'raw_path is immutable after write');
  END;

ID patterns (from spec §8.3):
  sources.id: src_<sha256[:12]>
  chunks.id:  chk_<source_id>_<ordinal zero-padded to 3>
  claims.id:  clm_<uuid7>
  concepts.id: cpt_<slug>
  entities.id: ent_<type>_<slug>

agent_runs.input_hash = sha256(agent_name + model + prompt_version + input_text) as hex
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Repo scaffold — pyproject.toml, .env.example, README, .gitignore, pkm/__init__.py, pkm/config.py</name>
  <files>
    /Users/RohitGupta/code/pkm-engine/pyproject.toml
    /Users/RohitGupta/code/pkm-engine/.env.example
    /Users/RohitGupta/code/pkm-engine/README.md
    /Users/RohitGupta/code/pkm-engine/.gitignore
    /Users/RohitGupta/code/pkm-engine/pkm/__init__.py
    /Users/RohitGupta/code/pkm-engine/pkm/config.py
  </files>
  <read_first>
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md (decisions section: Repository Bootstrap + Config)
    - /Users/RohitGupta/code/pkm-engine/pyproject.toml (read first if it exists — do not overwrite existing content blindly)
  </read_first>
  <action>
    Create /Users/RohitGupta/code/pkm-engine/ if it does not exist.

    pyproject.toml: Use [build-system] with setuptools. [project] name="pkm", version="0.1.0", requires-python=">=3.11". dependencies list must include: "libsql-experimental", "pydantic>=2.0", "pydantic-settings>=2.0", "anthropic>=0.25", "python-dotenv". [project.optional-dependencies] dev = ["pytest", "pytest-asyncio"]. [project.scripts] pkm = "pkm.cli:app". [tool.pytest.ini_options] testpaths = ["tests"].

    .env.example: List all five env vars with placeholder values — ANTHROPIC_API_KEY=sk-ant-..., TURSO_URL=libsql://your-db.turso.io, TURSO_TOKEN=eyJ..., CF_ACCOUNT_ID=, CF_API_TOKEN=. Include a comment "# Leave TURSO_URL empty to use local pkm.db (offline dev)".

    README.md: Brief description: "pkm-engine — AI-assisted Personal Knowledge Management pipeline". Sections: Setup (pip install -e ., cp .env.example .env), Local dev (TURSO_URL blank = uses pkm.db), Running tests (pytest tests/).

    .gitignore: Include pkm.db, *.db, .env, __pycache__/, *.pyc, .pytest_cache/, dist/, *.egg-info/, .venv/.

    pkm/__init__.py: Single line: __version__ = "0.1.0"

    pkm/config.py: Define Settings(BaseSettings) with exactly these fields and defaults per the interfaces block above. Use model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8"). Export a module-level singleton: settings = Settings(). Import: from pydantic_settings import BaseSettings, SettingsConfigDict.
  </action>
  <verify>
    <automated>cd /Users/RohitGupta/code/pkm-engine && pip install -e . -q && python -c "from pkm.config import settings; print(settings.db_path)"</automated>
  </verify>
  <acceptance_criteria>
    - pip install -e . exits 0 with no import errors
    - python -c "from pkm.config import settings; print(settings.db_path)" prints "pkm.db"
    - python -c "from pkm.config import Settings; s = Settings(turso_url='x'); print(s.turso_url)" prints "x"
    - .env.example contains lines matching: ANTHROPIC_API_KEY=, TURSO_URL=, TURSO_TOKEN=, CF_ACCOUNT_ID=, CF_API_TOKEN=
    - .gitignore contains "pkm.db" and ".env" (verified by: grep -c "pkm.db" /Users/RohitGupta/code/pkm-engine/.gitignore)
  </acceptance_criteria>
  <done>pkm package importable, settings reads from env, repo hygiene files present.</done>
</task>

<task type="auto">
  <name>Task 2: Migration SQL — 001_init.sql (full schema + trigger) and 002_graph_tables.sql</name>
  <files>
    /Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql
    /Users/RohitGupta/code/pkm-engine/migrations/sqlite/002_graph_tables.sql
  </files>
  <read_first>
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-CONTEXT.md (decisions section: Schema — full DDL spec)
    - /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/PKM_TECHNICAL_SPECIFICATION.md §2.1 and §2.2 (authoritative DDL source)
  </read_first>
  <action>
    Create /Users/RohitGupta/code/pkm-engine/migrations/sqlite/ directory.

    001_init.sql must start with PRAGMA journal_mode = WAL; and PRAGMA foreign_keys = ON; then CREATE TABLE IF NOT EXISTS for all tables in this exact order: sources, chunks, summaries, claims, concepts, concept_aliases, claim_concepts, entities, entity_aliases, agent_runs, embeddings_meta. Then CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts. Then all CREATE INDEX IF NOT EXISTS statements. Then the immutability trigger.

    Tables must match the spec exactly (CONTEXT.md decisions section has the full field list for each table). Key constraints to enforce:
    - sources.content_hash: TEXT NOT NULL UNIQUE
    - sources.status: CHECK (status IN ('captured','summarized','extracted','linked','done','error')) DEFAULT 'captured'
    - sources.type: CHECK (type IN ('Article','Book','Paper','Newsletter','Podcast','Meeting','Note'))
    - chunks: UNIQUE(source_id, ordinal)
    - claims.claim_type: CHECK (claim_type IN ('fact','opinion','prediction','definition','causal','statistic'))
    - claims.status: CHECK (status IN ('candidate','approved','merged','rejected')) DEFAULT 'candidate'
    - agent_runs: UNIQUE(agent, input_hash)
    - agent_runs.status: TEXT NOT NULL (ok|error — no CHECK needed, keeps it flexible)
    - claims_fts: CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(statement, content='claims', content_rowid='rowid')

    Immutability trigger (write verbatim — do not paraphrase):
      CREATE TRIGGER IF NOT EXISTS sources_raw_immutable
      BEFORE UPDATE OF raw_path ON sources
      BEGIN
        SELECT RAISE(ABORT, 'raw_path is immutable after write');
      END;

    Indexes: idx_sources_status ON sources(status), idx_sources_type ON sources(type), idx_chunks_source ON chunks(source_id), idx_claims_source ON claims(source_id).

    002_graph_tables.sql must create: graph_nodes (id PK, label NOT NULL, name NOT NULL, properties TEXT JSON, confidence REAL DEFAULT 0.5, provenance TEXT JSON array, created_at NOT NULL, updated_at NOT NULL), graph_edges (id PK, src FK→graph_nodes ON DELETE CASCADE, dst FK→graph_nodes ON DELETE CASCADE, type NOT NULL, description TEXT, strength INTEGER CHECK(strength BETWEEN 1 AND 10), confidence REAL DEFAULT 0.5, provenance TEXT, created_at NOT NULL, updated_at NOT NULL). All CREATE TABLE IF NOT EXISTS. Indexes: idx_nodes_label, idx_edges_src, idx_edges_dst, idx_edges_type.
  </action>
  <verify>
    <automated>cd /Users/RohitGupta/code/pkm-engine && python -c "
import libsql_experimental as libsql, pathlib
conn = libsql.connect(':memory:')
conn.execute(pathlib.Path('migrations/sqlite/001_init.sql').read_text())
conn.execute(pathlib.Path('migrations/sqlite/002_graph_tables.sql').read_text())
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'sources' in tables
assert 'agent_runs' in tables
assert 'graph_nodes' in tables
# verify trigger
conn.execute(\"INSERT INTO sources VALUES ('src_test','hash1','Article',NULL,NULL,NULL,NULL,NULL,'2026-01-01T00:00:00Z','raw/test.md',NULL,0.5,NULL,'captured','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')\")
try:
    conn.execute(\"UPDATE sources SET raw_path='raw/other.md' WHERE id='src_test'\")
    assert False, 'trigger did not fire'
except Exception as e:
    assert 'immutable' in str(e).lower(), f'wrong error: {e}'
print('ALL OK')
"</automated>
  </verify>
  <acceptance_criteria>
    - Script above prints "ALL OK" with exit code 0
    - Running 001_init.sql twice against same in-memory DB raises no error (IF NOT EXISTS guards)
    - Running 002_graph_tables.sql twice raises no error (IF NOT EXISTS guards)
    - grep -c "sources_raw_immutable" migrations/sqlite/001_init.sql returns 1
    - grep -c "UNIQUE.*agent.*input_hash\|UNIQUE (agent, input_hash)" migrations/sqlite/001_init.sql returns at least 1 (or UNIQUE constraint visible in agent_runs CREATE TABLE statement)
    - grep -c "content_hash.*UNIQUE\|UNIQUE.*content_hash" migrations/sqlite/001_init.sql returns at least 1
  </acceptance_criteria>
  <done>Both migration files apply cleanly to an empty in-memory DB; trigger fires on raw_path update; idempotent (IF NOT EXISTS throughout).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| env vars → config | ANTHROPIC_API_KEY and TURSO_TOKEN read from .env; must never be committed |
| migration SQL → DB | SQL runs with full DDL privileges; malformed SQL could corrupt schema |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-01 | Information Disclosure | .env file | mitigate | .gitignore includes .env; .env.example has only placeholder values |
| T-01-02 | Tampering | 001_init.sql immutability trigger | mitigate | Trigger uses RAISE(ABORT) which rolls back the transaction; tested in verify step |
| T-01-03 | Elevation of Privilege | libsql-experimental install | accept | Well-known package (libSQL official Python binding from Turso); pinned in pyproject.toml |
| T-01-SC | Tampering | pip installs | mitigate | All packages are established PyPI packages; verify with pip show before first use |
</threat_model>

<verification>
After both tasks complete:
1. cd /Users/RohitGupta/code/pkm-engine && pip install -e . exits 0
2. python -c "from pkm.config import settings" exits 0
3. Both migration files apply to :memory: DB and trigger fires correctly (see Task 2 verify script)
4. grep sources_raw_immutable migrations/sqlite/001_init.sql finds the trigger
</verification>

<success_criteria>
- pkm package importable after pip install -e .
- Settings(turso_url="") gives db_path="pkm.db"; Settings(turso_url="libsql://x") gives turso_url="libsql://x"
- Both SQL migrations apply to empty DB in sequence with no errors
- Trigger blocks raw_path update with error containing "immutable"
- Running migrations twice is a no-op
</success_criteria>

<output>
Create /Users/RohitGupta/Library/Mobile Documents/com~apple~CloudDocs/Personal Knowledge Management/.planning/phases/01-data-layer-idempotency/01-01-SUMMARY.md when done.
</output>
