---
phase: 02-core-agents
verified: 2026-06-15T00:00:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
deferred:
  - truth: "ConceptExtractor reads the concept index (AGNT-03 sub-clause)"
    addressed_in: "Phase 3"
    evidence: "AGNT-03 full text: 'reads concept index' — concept index does not exist until Phase 3 vault writer creates wiki/concepts/; Phase 2 ROADMAP success criteria do not include this sub-clause; ConceptExtractor's golden-fixture test passes for the claims+concept_matches output contract"
---

# Phase 2: Core Agents Verification Report

**Phase Goal:** All four MVP agents (Reader, Summarizer, Concept Extractor, KG Agent) pass golden-fixture tests with pydantic-validated structured output.
**Verified:** 2026-06-15
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Each agent passes its golden-fixture test independently | VERIFIED | `pytest tests/test_agents.py` — 8 passed (3 Reader + 3 Summarizer + 1 ConceptExtractor + 1 KGAgent) |
| 2  | Every claim has chunk_id (provenance) or null + confidence <= 0.5 | VERIFIED | `test_summarizer_chunk_id_rule` asserts invariant; golden fixture contains claim with chunk_id="null" and confidence=0.4; pydantic KeyClaim.chunk_id typed str (required, not Optional) |
| 3  | Schema-invalid LLM response triggers repair-retry; valid response passes | VERIFIED | `test_repair_retry_propagates_on_double_failure` patches Anthropic client with malformed response; confirms pydantic.ValidationError propagates on double failure; `LLMClient._extract_result` lines 158-191 show one-repair-retry path |
| 4  | All agent calls write tokens_in, tokens_out, cost_usd to agent_runs | VERIFIED | `LLMClient._write_run` upserts agent_runs on every call; `test_reader_agent_agent_runs_write` asserts tokens_in=42/tokens_out=17; all golden tests assert agent_runs row with status='ok' |
| 5  | All four agents subclass BaseAgent | VERIFIED | ReaderAgent, SummarizerAgent, ConceptExtractor, KGAgent all declared with `class X(BaseAgent)`; BaseAgent.__init_subclass__ enforces 7 ClassVar attributes at definition time |
| 6  | Reader uses HAIKU; Summarizer, ConceptExtractor, KGAgent use SONNET | VERIFIED | ReaderAgent.model == "claude-haiku-4-5-20251001"; all three others == "claude-sonnet-4-6" (confirmed by runtime assertions) |
| 7  | ConceptExtractor produces SPO claims + concept_matches (AGNT-03 core output) | VERIFIED | ConceptExtractor.output_schema is ConceptExtractorOutput; schema has claims: list[KeyClaim] and concept_matches: list[ConceptMatch]; golden fixture parses with 1 claim and 2 concept_matches |

**Score:** 7/7 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | ConceptExtractor reads concept index at runtime | Phase 3 | Phase 3 vault writer creates wiki/concepts/ — the concept index that AGNT-03 requires does not exist until Phase 3. Phase 2 ROADMAP success criteria do not include this sub-clause. The ConceptExtractor's output contract (claims + concept_matches) is fully verified. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pkm/agents/base.py` | BaseAgent ABC with 7 ClassVar enforcement and run() | VERIFIED | 162 lines; class BaseAgent(ABC); __init_subclass__ checks all 7 attrs; _load_prompt() and run() implemented |
| `pkm/agents/__init__.py` | Package init | VERIFIED | Exists |
| `pkm/agents/reader_agent.py` | ReaderAgent(BaseAgent), model=HAIKU, output_schema=None | VERIFIED | 36 lines; all 7 ClassVars set; model=HAIKU confirmed |
| `pkm/agents/summarizer_agent.py` | SummarizerAgent(BaseAgent), model=SONNET, output_schema=SummarizerOutput | VERIFIED | 34 lines; output_schema=SummarizerOutput |
| `pkm/agents/concept_extractor.py` | ConceptExtractor(BaseAgent), model=SONNET, output_schema=ConceptExtractorOutput | VERIFIED | 33 lines; output_schema=ConceptExtractorOutput |
| `pkm/agents/kg_agent.py` | KGAgent(BaseAgent), model=SONNET, output_schema=KGAgentOutput | VERIFIED | 27 lines; all 7 ClassVars set as plain class attributes (no ClassVar annotation — __init_subclass__ uses hasattr which passes regardless) |
| `pkm/schemas/agent_io.py` | SummarizerOutput, KGAgentOutput, ConceptExtractorOutput, ConceptMatch, KeyClaim, GraphNode, GraphRelationship | VERIFIED | 56 lines; all 7 models present; ConceptMatch.claim_indices: list[int] rejects string indices |
| `pkm/graph/resolver.py` | resolve(conn, name, entity_type) three-tier implementation | VERIFIED | 52 lines; Tier 1 exact match, Tier 2 alias join, Tier 3 stub returns None; parameterized ? placeholders throughout |
| `pkm/graph/confidence.py` | noisy_or(s_old, s_new) pure function | VERIFIED | 19 lines; formula `1.0 - (1.0 - s_old) * (1.0 - s_new)` confirmed |
| `pkm/prompts/summarize.v1.md` | Prompt with chunk_id rules | VERIFIED | Contains chunk_id requirement; confidence rules; role/task/output schema/constraints/example sections |
| `pkm/prompts/extract_claims.v1.md` | Prompt with concept_matches | VERIFIED | Contains chunk_id, concept_matches; SPO claim format; canonicalization guidance |
| `pkm/prompts/er_extraction.v1.md` | Prompt for KG extraction | VERIFIED | Exists; contains relationship types and node slug format |
| `pkm/prompts/reader.v1.md` | Prompt with YAML front matter instructions | VERIFIED | Exists; instructs YAML front matter fields; body preservation |
| `tests/test_base_agent.py` | 9 unit tests for BaseAgent | VERIFIED | 9 tests covering importability, ClassVar enforcement, _load_prompt, run() kwargs, cache-hit, prompt inclusion |
| `tests/test_agents.py` | Golden-fixture tests for all 4 agents; repair-retry test | VERIFIED | 8 tests; TestReaderAgent (3), TestSummarizerAgent (3), TestConceptExtractor (1), TestKGAgent (1) |
| `tests/test_resolver.py` | Resolver + noisy-OR unit tests | VERIFIED | 5 tests; TestResolver (4: exact, alias, miss, wrong-type), TestNoisyOr (1: 4 formula values) |
| `tests/fixtures/golden_reader_output.md` | Golden Reader output with front matter | VERIFIED | Contains "---" and src_abc123deadbee |
| `tests/fixtures/golden_summarizer_output.json` | Valid SummarizerOutput JSON with null chunk_id claim | VERIFIED | Contains chunk_id="null" with confidence=0.4; parses to valid SummarizerOutput |
| `tests/fixtures/golden_extractor_output.json` | Valid ConceptExtractorOutput JSON | VERIFIED | 1 claim, 2 concept_matches; parses cleanly |
| `tests/fixtures/golden_kg_output.json` | Valid KGAgentOutput JSON | VERIFIED | 2 nodes, 1 relationship; contains ent_concept_atomic-notes |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `pkm/agents/base.py` | `pkm/llm/client.py` | LLMClient injected as run() arg | WIRED | base.py has no import of LLMClient; client passed as arg to run(); llm_client.call() called with correct kwargs confirmed by test_run_calls_llm_client_with_correct_kwargs |
| `pkm/agents/reader_agent.py` | `pkm/agents/base.py` | `class ReaderAgent(BaseAgent)` | WIRED | Direct inheritance |
| `pkm/agents/summarizer_agent.py` | `pkm/schemas/agent_io.py` | `output_schema = SummarizerOutput` | WIRED | Import and assignment both present |
| `pkm/agents/concept_extractor.py` | `pkm/schemas/agent_io.py` | `output_schema = ConceptExtractorOutput` | WIRED | Import and assignment both present |
| `pkm/agents/kg_agent.py` | `pkm/schemas/agent_io.py` | `output_schema = KGAgentOutput` | WIRED | Import and assignment both present |
| `pkm/graph/resolver.py` | entities + entity_aliases tables | `conn.execute()` parameterized SQL | WIRED | Tier 1 queries entities; Tier 2 JOINs entity_aliases; all ? placeholders confirmed |
| `tests/test_agents.py` | `pkm/llm/client.py` | `test_repair_retry_propagates_on_double_failure` | WIRED | Creates real LLMClient, patches anthropic.Anthropic, verifies ValidationError propagation |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 22 Phase 2 tests pass | `pytest tests/test_agents.py tests/test_resolver.py tests/test_base_agent.py -v` | 22 passed in 0.69s | PASS |
| ReaderAgent.model == HAIKU | Python import assertion | True | PASS |
| SummarizerAgent/ConceptExtractor/KGAgent.model == SONNET | Python import assertion | True for all three | PASS |
| noisy_or(0.5, 0.5) == 0.75 | Python assertion | 0.75 | PASS |
| SummarizerOutput rejects confidence > 1.0 | pydantic.ValidationError raised | ValidationError raised | PASS |
| ConceptMatch rejects string claim_indices | pydantic.ValidationError raised | ValidationError raised | PASS |
| chunk_id="null" claim has confidence=0.4 <= 0.5 | Golden fixture invariant | Passes | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| AGNT-01 | 02-02 | Reader agent (Haiku) normalizes raw bytes/URL → clean Markdown + front matter | SATISFIED | ReaderAgent.model=HAIKU; output_schema=None (returns str); reader.v1.md instructs front matter normalization; 3 golden tests pass |
| AGNT-02 | 02-03 | Summarizer agent (Sonnet) produces thesis + key_claims[] + caveats[] with source spans and pydantic validation | SATISFIED | SummarizerAgent.model=SONNET; output_schema=SummarizerOutput; chunk_id invariant tested; golden fixture + repair-retry test pass |
| AGNT-03 | 02-03 | Concept Extractor (Sonnet) produces atomic SPO claims + concept matches; reads concept index | PARTIAL — core output satisfied; "reads concept index" deferred to Phase 3 | ConceptExtractor.model=SONNET; output_schema=ConceptExtractorOutput(claims+concept_matches); concept index does not exist until Phase 3 vault creation |
| AGNT-04 | 02-04 | KG Agent (Sonnet) produces graph nodes[] + relationships[] with entity resolution and provenance | SATISFIED | KGAgent.model=SONNET; output_schema=KGAgentOutput; resolver.py implements three-tier resolution; provenance format "src_id#chunk_id" in fixture |
| AGNT-05 | 02-03 | All agents validate output against pydantic schema with one repair-retry on schema-invalid response | SATISFIED | LLMClient._extract_result lines 158-191 implement one-repair-retry; test_repair_retry_propagates_on_double_failure verifies propagation path |
| AGNT-06 | 02-02, 02-03, 02-04 | All agents write cost (tokens_in, tokens_out, cost_usd) to agent_runs table per call | SATISFIED | LLMClient._write_run called on both success and error paths; mock helper writes real agent_runs rows; token counts asserted in test_reader_agent_agent_runs_write |

**Note on REQUIREMENTS.md checkbox state:** AGNT-01, AGNT-04, AGNT-06 show `[x]` in REQUIREMENTS.md. AGNT-02, AGNT-03, AGNT-05 show `[ ]` — these are tracking gaps in the file; the implementations exist and all tests pass. The checkbox state in REQUIREMENTS.md was not updated after Phase 2 completion.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `pkm/graph/resolver.py` | 47 | "embedding tier not implemented for MVP" in logger.debug | INFO | Intentional MVP stub per plan spec AD-5; resolver returns None for tier 3; explicitly documented in 02-04-SUMMARY.md Known Stubs section; not a blocker |

No TBD, FIXME, or XXX markers found in any Phase 2 file.

### Human Verification Required

None. All must-haves verified programmatically.

### Gaps Summary

No gaps. All seven Phase 2 ROADMAP success criteria are verified against the codebase:

1. Each agent passes golden-fixture test independently — 22 tests pass (8 agent golden tests, 9 BaseAgent unit tests, 5 resolver tests).
2. Every claim has chunk_id or null + confidence <= 0.5 — enforced by KeyClaim.chunk_id: str (required), tested by test_summarizer_chunk_id_rule, golden fixture contains the null+0.4 case.
3. Schema-invalid LLM response triggers repair-retry — LLMClient._extract_result one-repair path exists and double-failure propagation is tested.
4. All agent calls write tokens_in, tokens_out, cost_usd to agent_runs — LLMClient._write_run called on all paths, asserted in tests.

The AGNT-03 "reads concept index" sub-clause is the only unimplemented item; it is deferred to Phase 3 where the concept index (wiki/concepts/) is created. The Phase 2 ROADMAP success criteria do not include this sub-clause, so it does not block phase passage.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_
