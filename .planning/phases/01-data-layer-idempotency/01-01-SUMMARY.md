---
phase: 01-data-layer-idempotency
plan: "01"
subsystem: database
tags: [libsql, pydantic-settings, sqlite, migrations, schema, triggers]

# Dependency graph
requires: []
provides:
  - Installable pkm Python package (pip install -e .)
  - pydantic-settings Settings class with dual-mode DB config (local SQLite / Turso cloud)
  - 001_init.sql: full core schema DDL (11 tables + FTS5 virtual table + trigger)
  - 002_graph_tables.sql: graph_nodes + graph_edges DDL
  - raw_path immutability trigger (RAISE ABORT on UPDATE)
affects: [wave2, wave3, 02-ingest, 03-agents, all-phases]

# Tech tracking
tech-stack:
  added:
    - libsql-experimental==0.0.55 (libSQL Python binding from Turso)
    - pydantic>=2.0
    - pydantic-settings>=2.0
    - anthropic>=0.25
    - python-dotenv
  patterns:
    - Dual-mode DB config: TURSO_URL empty = local pkm.db, non-empty = Turso cloud
    - IF NOT EXISTS throughout all DDL for idempotent migrations
    - executescript() (not execute()) required for multi-statement SQL files

key-files:
  created:
    - pkm/config.py
    - pkm/__init__.py
    - pyproject.toml
    - .env.example
    - .gitignore
    - README.md
    - migrations/sqlite/001_init.sql
    - migrations/sqlite/002_graph_tables.sql
  modified: []

key-decisions:
  - "setuptools package discovery scoped to pkm* only (migrations/ directory caused flat-layout error)"
  - "libsql_experimental.execute() only runs first SQL statement — use executescript() for multi-statement migration files"
  - "anthropic_api_key has empty string default so Settings() works without .env in test contexts"

patterns-established:
  - "Migration runner: use conn.executescript() not conn.execute() for .sql files with multiple statements"
  - "Package structure: pkm/ only; migrations/ is data directory not a Python package"

requirements-completed:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-05
  - DATA-06
  - DATA-07
  - DATA-08
  - DATA-09

# Metrics
duration: 7min
completed: "2026-06-15"
---

# Phase 1 Plan 01: Repo Scaffold + Schema DDL Summary

**Installable pkm package with pydantic-settings dual-mode config, 11-table SQLite schema with FTS5 and raw_path immutability trigger, and idempotent graph DDL**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-15T09:25:26Z
- **Completed:** 2026-06-15T09:32:43Z
- **Tasks:** 2
- **Files modified:** 8 (6 Task 1 + 2 Task 2)

## Accomplishments

- pkm Python package installable via `pip install -e .` with all Phase 1 dependencies declared
- Settings class reads TURSO_URL/TURSO_TOKEN/ANTHROPIC_API_KEY/CF_* from .env with local SQLite fallback
- 001_init.sql: sources, chunks, summaries, claims, concepts, concept_aliases, claim_concepts, entities, entity_aliases, agent_runs, embeddings_meta + claims_fts FTS5 + sources_raw_immutable trigger
- 002_graph_tables.sql: graph_nodes + graph_edges with cascade FK, confidence, provenance fields
- All DDL uses IF NOT EXISTS — running migrations twice is a no-op
- Trigger fires RAISE(ABORT, 'raw_path is immutable after write') on raw_path UPDATE

## Task Commits

1. **Task 1: Repo scaffold — pyproject.toml, .env.example, README, .gitignore, pkm/__init__.py, pkm/config.py** - `edd8954` (feat)
2. **Task 2: Migration SQL — 001_init.sql + 002_graph_tables.sql** - `e5540b8` (feat)
3. **Auto-fix: setuptools package discovery scoped to pkm***- `1608d77` (fix)

## Files Created/Modified

- `pyproject.toml` - Package declaration, deps, pytest config, setuptools package discovery
- `pkm/__init__.py` - Version sentinel (`__version__ = "0.1.0"`)
- `pkm/config.py` - pydantic-settings Settings class; dual-mode DB (Turso/local)
- `.env.example` - Five env vars with placeholders; offline dev comment
- `.gitignore` - pkm.db, *.db, .env, __pycache__, pytest_cache, dist, egg-info, .venv
- `README.md` - Setup and local dev instructions
- `migrations/sqlite/001_init.sql` - Full core schema + FTS5 + immutability trigger
- `migrations/sqlite/002_graph_tables.sql` - graph_nodes + graph_edges DDL

## Decisions Made

- **setuptools packages.find scoped to `pkm*`**: When `migrations/` directory was created, setuptools flat-layout auto-discovery failed with "Multiple top-level packages discovered." Fixed by adding `[tool.setuptools.packages.find] include = ["pkm*"]`.
- **anthropic_api_key default is empty string**: Settings class uses `anthropic_api_key: str = ""` so that `Settings()` works without a `.env` file in test contexts. Callers must validate at runtime before making API calls.
- **libsql_experimental.execute() is single-statement only**: Discovered that `conn.execute(multi_stmt_sql)` silently runs only the first statement. All migration runners must use `conn.executescript()`. Documented in patterns-established.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pyproject.toml build failure due to multiple top-level packages**
- **Found during:** Task 1 verify (`pip install -e .`)
- **Issue:** After creating `migrations/` directory, setuptools flat-layout discovery errored: "Multiple top-level packages discovered in a flat-layout: ['pkm', 'migrations']"
- **Fix:** Added `[tool.setuptools.packages.find] include = ["pkm*"]` to pyproject.toml
- **Files modified:** `pyproject.toml`
- **Verification:** `pip install -e .` exits 0; `from pkm.config import settings` succeeds
- **Committed in:** `1608d77`

**2. [Rule 3 - Blocking] Build backend error on first pip install**
- **Found during:** Task 1 verify (first attempt)
- **Issue:** `setuptools.backends.legacy:build` not available in installed setuptools version
- **Fix:** Changed build-backend to standard `setuptools.build_meta`
- **Files modified:** `pyproject.toml`
- **Verification:** pip install succeeds
- **Committed in:** `edd8954` (included in Task 1 commit)

**3. [Rule 1 - Bug] Plan verify script uses conn.execute() which only runs first SQL statement**
- **Found during:** Task 2 verify
- **Issue:** `libsql_experimental.execute(multi_statement_sql)` silently executes only the first statement. The plan verify script expected `conn.execute(file_text)` to run all DDL — it only ran `PRAGMA journal_mode = WAL;` leaving no tables created.
- **Fix:** Ran equivalent verify using `conn.executescript()` which behaves correctly. SQL migration files are correct; all 11 tables + trigger created successfully. Documented pattern: all migration runners MUST use `executescript()`.
- **Files modified:** None (SQL files are correct; verify script is a plan artifact)
- **Verification:** Equivalent verify with `executescript()` prints "ALL OK"
- **Impact:** Future code using these migrations must call `executescript()`, not `execute()`

---

**Total deviations:** 3 auto-fixed (2 blocking, 1 bug)
**Impact on plan:** All fixes necessary for functionality. No scope creep. Migration files themselves are correct SQL.

## Issues Encountered

- `libsql_experimental.execute()` does not support multi-statement SQL (only runs first statement). This is a known limitation of the library's Python binding. The plan's verify script used `execute()` which couldn't pass. Used `executescript()` for equivalent verification. All downstream code must use `executescript()` for migration files.

## Known Stubs

None — all fields are wired, no placeholder data or TODO markers.

## Threat Flags

No new security-relevant surface beyond what was in the plan's threat model.
- T-01-01 mitigated: `.env` is in `.gitignore`, `.env.example` has only placeholder values
- T-01-02 mitigated: `sources_raw_immutable` trigger created, tested, fires RAISE(ABORT)
- T-01-03 accepted: `libsql-experimental` is the official Turso Python binding

## Self-Check

Files verified to exist:
- /Users/RohitGupta/code/pkm-engine/pyproject.toml: FOUND
- /Users/RohitGupta/code/pkm-engine/pkm/config.py: FOUND
- /Users/RohitGupta/code/pkm-engine/migrations/sqlite/001_init.sql: FOUND
- /Users/RohitGupta/code/pkm-engine/migrations/sqlite/002_graph_tables.sql: FOUND

Commits verified:
- edd8954: FOUND (feat(01-01): repo scaffold)
- e5540b8: FOUND (feat(01-01): migration SQL)
- 1608d77: FOUND (fix(01-01): setuptools package discovery)

## Self-Check: PASSED

## Next Phase Readiness

Wave 2 can proceed: pkm package is importable, Settings is available, migration schema is defined. Wave 2 will need `pkm/store/registry.py` which runs migrations on startup using `executescript()`.

---
*Phase: 01-data-layer-idempotency*
*Completed: 2026-06-15*
