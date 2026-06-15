---
phase: 02-core-agents
plan: "04"
subsystem: agents/graph
tags: [kg_agent, entity-resolution, confidence, graph, tdd]
dependency_graph:
  requires: [02-01, 02-02, 02-03]
  provides: [KGAgent, graph/resolver.py, graph/confidence.py]
  affects: [phase-03-pipeline]
tech_stack:
  added: []
  patterns: [noisy-OR confidence update, three-tier entity resolution, parameterized SQL queries]
key_files:
  created:
    - pkm/agents/kg_agent.py
    - pkm/graph/__init__.py
    - pkm/graph/resolver.py
    - pkm/graph/confidence.py
    - tests/fixtures/golden_kg_output.json
    - tests/test_resolver.py
  modified:
    - tests/test_agents.py
decisions:
  - "Tier 3 embedding resolution stubbed (returns None + debug log) per spec AD-5 MVP constraint"
  - "Parameterized SQL ? placeholders used throughout resolver.py (T-02-08 mitigation)"
  - "noisy_or() is a pure function with no DB dependency — maximally testable"
metrics:
  duration_seconds: 110
  completed_date: "2026-06-15"
  tasks_completed: 2
  files_created: 6
  files_modified: 1
---

# Phase 02 Plan 04: KGAgent + Graph Infrastructure Summary

KGAgent (fourth and final MVP agent), three-tier entity resolver, and noisy-OR confidence update — all four BaseAgent subclasses now complete with 13 passing tests.

## What Was Built

### Task 1: KGAgent + graph/resolver.py + graph/confidence.py

**pkm/agents/kg_agent.py** — Fourth and final BaseAgent subclass:
- `role = "kg_agent"`, `model = SONNET`, `output_schema = KGAgentOutput`, `memory_tier = "working"`
- Uses `er_extraction.v1.md` prompt (already existed from Phase 1)

**pkm/graph/confidence.py** — Noisy-OR confidence update (AD-6):
- `noisy_or(s_old, s_new) = 1 - (1 - s_old) * (1 - s_new)`
- Pure function, no side effects, no DB dependency

**pkm/graph/resolver.py** — Three-tier entity resolution (AD-5):
- Tier 1: `SELECT id FROM entities WHERE type=? AND name=?` (exact match)
- Tier 2: `JOIN entity_aliases` on type + alias string
- Tier 3: MVP stub — logs debug message, returns `None`
- All SQL queries use parameterized `?` placeholders (T-02-08 mitigation)

**pkm/graph/__init__.py** — Package init file

### Task 2: Tests

**tests/fixtures/golden_kg_output.json** — Valid KGAgentOutput with 2 Concept nodes and 1 RELATED_TO relationship

**tests/test_agents.py** — Replaced `class TestKGAgent: pass` placeholder with:
- `test_kg_agent_golden`: mock returns parsed KGAgentOutput; asserts `isinstance(result, KGAgentOutput)`, `len(nodes) >= 1`, `agent_runs` row with `status='ok'`

**tests/test_resolver.py** — New standalone test file:
- `TestResolver.test_exact_match`: tier 1 hit returns entity id
- `TestResolver.test_alias_match`: tier 2 alias hit returns entity id
- `TestResolver.test_miss_returns_none`: no match returns None
- `TestResolver.test_wrong_type_returns_none`: type mismatch returns None
- `TestNoisyOr.test_formula_values`: verifies 4 known formula values

## Test Results

```
tests/test_agents.py::TestReaderAgent::test_reader_agent_golden PASSED
tests/test_agents.py::TestReaderAgent::test_reader_agent_agent_runs_write PASSED
tests/test_agents.py::TestReaderAgent::test_reader_agent_cache_hit_raises PASSED
tests/test_agents.py::TestSummarizerAgent::test_summarizer_agent_golden PASSED
tests/test_agents.py::TestSummarizerAgent::test_summarizer_chunk_id_rule PASSED
tests/test_agents.py::TestSummarizerAgent::test_repair_retry_propagates_on_double_failure PASSED
tests/test_agents.py::TestConceptExtractor::test_concept_extractor_golden PASSED
tests/test_agents.py::TestKGAgent::test_kg_agent_golden PASSED
tests/test_resolver.py::TestResolver::test_exact_match PASSED
tests/test_resolver.py::TestResolver::test_alias_match PASSED
tests/test_resolver.py::TestResolver::test_miss_returns_none PASSED
tests/test_resolver.py::TestResolver::test_wrong_type_returns_none PASSED
tests/test_resolver.py::TestNoisyOr::test_formula_values PASSED

13 passed in 0.65s
```

(Plan projected 12; actual count is 13 because 02-02 delivered 3 TestReaderAgent tests, not 2.)

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or external integrations introduced. resolver.py accesses the local SQLite DB via parameterized queries (T-02-08 mitigated as required by the plan's threat register).

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| Embedding tier returns None | `pkm/graph/resolver.py` lines 50-55 | MVP constraint per AD-5; Cloudflare Vectorize integration deferred to Phase 4+ |

This stub does not block the plan's goal (entity resolution works via tiers 1 and 2). Phase 3 pipeline will call `resolve()` and create new entities when `None` is returned.

## Self-Check: PASSED

- [x] `pkm/agents/kg_agent.py` exists
- [x] `pkm/graph/__init__.py` exists
- [x] `pkm/graph/resolver.py` exists and contains `def resolve(` and `entity_aliases`
- [x] `pkm/graph/confidence.py` exists and contains `def noisy_or(` and `1.0 - (1.0 - s_old)`
- [x] `tests/fixtures/golden_kg_output.json` exists and contains `ent_concept_atomic-notes`
- [x] `tests/test_resolver.py` exists with `class TestResolver` and `class TestNoisyOr`
- [x] Task 1 commit: `09e83b5`
- [x] Task 2 commit: `909c8bc`
- [x] 13 tests pass, 0 failed
