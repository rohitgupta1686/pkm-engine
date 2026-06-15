---
phase: 02-core-agents
plan: "03"
subsystem: agents
tags: [agents, pydantic, summarizer, concept-extractor, golden-tests, repair-retry]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [summarizer_agent, concept_extractor, ConceptExtractorOutput, ConceptMatch]
  affects: [02-04, Phase 3 pipeline]
tech_stack:
  added: []
  patterns: [BaseAgent subclass, golden-fixture tests, repair-retry validation, tool-calling structured output]
key_files:
  created:
    - pkm/agents/summarizer_agent.py
    - pkm/agents/concept_extractor.py
    - tests/fixtures/golden_summarizer_output.json
    - tests/fixtures/golden_extractor_output.json
  modified:
    - pkm/schemas/agent_io.py
    - tests/test_agents.py
decisions:
  - "ConceptMatch.claim_indices is list[int] — pydantic rejects string indices at the validation gate (mitigates T-02-05)"
  - "chunk_id='null' string convention tested as data contract: confidence <= 0.5 enforced in test_summarizer_chunk_id_rule"
  - "repair-retry test patches pkm.llm.client.anthropic.Anthropic and re-creates LLMClient inside the patch context to use the injected mock"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-15"
  tasks: 2
  files_changed: 6
---

# Phase 2 Plan 3: SummarizerAgent + ConceptExtractor Summary

SummarizerAgent and ConceptExtractor implemented as BaseAgent subclasses with pydantic-validated structured output; golden-fixture tests plus repair-retry propagation test all passing (7 total).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SummarizerAgent + ConceptExtractor + ConceptExtractorOutput schema | ffad21e | pkm/agents/summarizer_agent.py, pkm/agents/concept_extractor.py, pkm/schemas/agent_io.py |
| 2 | Golden-fixture tests + repair-retry test | 091f902 | tests/test_agents.py, tests/fixtures/golden_summarizer_output.json, tests/fixtures/golden_extractor_output.json |

## What Was Built

**SummarizerAgent** (`pkm/agents/summarizer_agent.py`): BaseAgent subclass with `role="summarizer_agent"`, `model=SONNET`, `output_schema=SummarizerOutput`, `prompt_template="summarize.v1.md"`. Returns a validated `SummarizerOutput` pydantic instance.

**ConceptExtractor** (`pkm/agents/concept_extractor.py`): BaseAgent subclass with `role="concept_extractor"`, `model=SONNET`, `output_schema=ConceptExtractorOutput`, `prompt_template="extract_claims.v1.md"`. Returns a validated `ConceptExtractorOutput` pydantic instance.

**Schema additions** (`pkm/schemas/agent_io.py`): Added `ConceptMatch(concept_name, claim_indices: list[int], confidence)` and `ConceptExtractorOutput(claims: list[KeyClaim], concept_matches: list[ConceptMatch])`. All existing models preserved: `KeyClaim`, `SummarizerOutput`, `GraphNode`, `GraphRelationship`, `KGAgentOutput`.

**Golden fixtures**: `golden_summarizer_output.json` includes a claim with `chunk_id="null"` and `confidence=0.4` to exercise the data-contract invariant. `golden_extractor_output.json` has 1 claim and 2 concept_matches.

**Tests** (`tests/test_agents.py`): Replaced both placeholder test classes with:
- `TestSummarizerAgent.test_summarizer_agent_golden` — golden fixture, agent_runs write
- `TestSummarizerAgent.test_summarizer_chunk_id_rule` — chunk_id="null" → confidence <= 0.5 invariant
- `TestSummarizerAgent.test_repair_retry_propagates_on_double_failure` — patches Anthropic client, verifies `pydantic.ValidationError` propagates on double-fail
- `TestConceptExtractor.test_concept_extractor_golden` — golden fixture, agent_runs write

## Test Results

```
tests/test_agents.py::TestReaderAgent::test_reader_agent_golden PASSED
tests/test_agents.py::TestReaderAgent::test_reader_agent_agent_runs_write PASSED
tests/test_agents.py::TestReaderAgent::test_reader_agent_cache_hit_raises PASSED
tests/test_agents.py::TestSummarizerAgent::test_summarizer_agent_golden PASSED
tests/test_agents.py::TestSummarizerAgent::test_summarizer_chunk_id_rule PASSED
tests/test_agents.py::TestSummarizerAgent::test_repair_retry_propagates_on_double_failure PASSED
tests/test_agents.py::TestConceptExtractor::test_concept_extractor_golden PASSED

7 passed in 0.58s
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both agents delegate all text processing to the LLM via prompt files that already exist (`summarize.v1.md`, `extract_claims.v1.md`).

## Threat Flags

No new threat surface introduced. Mitigations from plan threat model implemented:
- T-02-05 (ConceptMatch.claim_indices): pydantic validates list[int] — string indices rejected at deserialization
- T-02-07 (chunk_id="null" confidence bypass): `test_summarizer_chunk_id_rule` asserts the <= 0.5 invariant

## Self-Check: PASSED

- `pkm/agents/summarizer_agent.py` — exists
- `pkm/agents/concept_extractor.py` — exists
- `pkm/schemas/agent_io.py` contains `ConceptExtractorOutput` and `KGAgentOutput` — verified
- `tests/fixtures/golden_summarizer_output.json` — exists
- `tests/fixtures/golden_extractor_output.json` — exists
- `tests/test_agents.py` contains `TestReaderAgent` (not overwritten) — verified
- Commits ffad21e and 091f902 — verified in git log
