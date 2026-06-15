---
phase: "02-core-agents"
plan: "02"
subsystem: "agents"
tags: ["reader_agent", "base_agent", "haiku", "golden_fixture", "agent_runs"]
dependency_graph:
  requires: ["02-01"]
  provides: ["ReaderAgent", "tests/test_agents.py", "golden fixture infrastructure"]
  affects: ["tests/test_agents.py (plans 03-04 extend this file)"]
tech_stack:
  added: []
  patterns: ["TDD red-green", "mock LLM injection", "agent_runs write via mock helper"]
key_files:
  created:
    - pkm/agents/reader_agent.py
    - pkm/prompts/reader.v1.md
    - tests/test_agents.py
    - tests/fixtures/golden_reader_output.md
  modified: []
decisions:
  - "output_schema=None on ReaderAgent: Reader returns plain string, not pydantic; consistent with LLMClient returning result['result'] as str when output_schema=None"
  - "build_mock_llm_client writes real agent_runs rows: mock simulates LLMClient.call() exactly including DB write so downstream SQL assertions work without real API calls"
  - "Placeholder test classes (TestSummarizerAgent, TestConceptExtractor, TestKGAgent) added now: plans 03-04 extend test_agents.py so they need the module to pre-exist"
metrics:
  duration_seconds: 167
  completed_date: "2026-06-15"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 0
---

# Phase 2 Plan 2: ReaderAgent + Golden Fixture Tests Summary

ReaderAgent subclassing BaseAgent with HAIKU model and golden-fixture test infrastructure wiring BaseAgent→LLMClient→agent_runs chain end-to-end without real API calls.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ReaderAgent implementation | fce14f6 | pkm/agents/reader_agent.py, pkm/prompts/reader.v1.md |
| 2 | Golden-fixture test + agent_runs write | 3608a9d | tests/test_agents.py, tests/fixtures/golden_reader_output.md |

## What Was Built

**Task 1 — ReaderAgent**

`pkm/agents/reader_agent.py` declares `class ReaderAgent(BaseAgent)` with:
- `role = "reader_agent"`, `model = HAIKU` ("claude-haiku-4-5-20251001")
- `output_schema = None`, `input_schema = None` — Reader returns cleaned Markdown string
- `memory_tier = "stateless"` — no prior context needed
- Inherits `run()` from BaseAgent without override

`pkm/prompts/reader.v1.md` instructs the model to return clean Markdown with YAML front matter (id, type, title, author, url, date_published, date_saved, content_hash, tags); preserve body verbatim; omit unknown fields; no JSON or commentary.

**Task 2 — Golden Fixture + Tests**

`tests/fixtures/golden_reader_output.md` — minimal valid golden output with YAML front matter matching sample_raw.md values (id: src_abc123deadbee, type: Article, title: The Art of Taking Smart Notes).

`tests/test_agents.py` — `TestReaderAgent` with 3 tests:
- `test_reader_agent_golden`: mock returns golden output → result is str, contains "---", agent_runs row exists with status="ok"
- `test_reader_agent_agent_runs_write`: tokens_in=42, tokens_out=17 written correctly to agent_runs
- `test_reader_agent_cache_hit_raises`: cached=True response raises RuntimeError

Helper `build_mock_llm_client(conn, result, tokens_in, tokens_out)` returns MagicMock whose `.call()` side_effect writes real agent_runs rows and returns expected dict shape — no real API budget consumed.

Placeholder classes for plans 03-04: `TestSummarizerAgent`, `TestConceptExtractor`, `TestKGAgent`.

## Verification Results

```
pytest tests/test_agents.py::TestReaderAgent -v
3 passed in 0.04s
```

All 3 tests pass. Full chain verified: BaseAgent._load_prompt() → mock LLMClient.call() → agent_runs INSERT → result returned as str.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — fixture data matches sample_raw.md exactly; no placeholder/TODO text in implementation.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. Test mocks are purely in-process.

## Self-Check: PASSED

- [x] pkm/agents/reader_agent.py exists
- [x] pkm/prompts/reader.v1.md exists
- [x] tests/test_agents.py exists
- [x] tests/fixtures/golden_reader_output.md exists
- [x] Commit fce14f6 exists (Task 1)
- [x] Commit 3608a9d exists (Task 2)
- [x] pytest tests/test_agents.py::TestReaderAgent — 3 passed
