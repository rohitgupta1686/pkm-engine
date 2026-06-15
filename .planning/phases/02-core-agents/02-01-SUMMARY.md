---
phase: 02-core-agents
plan: 01
subsystem: agents
tags: [pydantic, abc, agents, prompts, llm, knowledge-graph]

# Dependency graph
requires:
  - phase: 01-data-layer
    provides: LLMClient.call() with cache/retry, pydantic output schemas (SummarizerOutput, KGAgentOutput)
provides:
  - BaseAgent ABC with 7 ClassVar attributes enforced at class-definition time via __init_subclass__
  - BaseAgent.run() shared implementation handling prompt loading, LLMClient delegation, cache detection
  - pkm/prompts/summarize.v1.md with chunk_id and confidence rules for SummarizerOutput
  - pkm/prompts/extract_claims.v1.md with SPO claims and concept_matches output schema
  - pkm/prompts/er_extraction.v1.md with GraphNode/GraphRelationship extraction and 9 allowed relationship types
affects:
  - 02-02 ReaderAgent (subclasses BaseAgent)
  - 02-03 Summarizer + Concept Extractor (subclass BaseAgent, use summarize.v1.md + extract_claims.v1.md)
  - 02-04 KGAgent (subclasses BaseAgent, uses er_extraction.v1.md)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BaseAgent ABC: concrete agents declare 7 ClassVars; single run() implementation in base"
    - "Prompt loading via Path(__file__).parent.parent / prompts / prompt_template — cwd-independent"
    - "No LLMClient import in base.py — injected via run() arg for testability"
    - "TDD RED/GREEN: failing tests committed first, then implementation"
    - "chunk_id required on every KeyClaim; positional IDs (para_1, para_2) used if source lacks explicit markers"

key-files:
  created:
    - pkm/agents/__init__.py
    - pkm/agents/base.py
    - pkm/prompts/__init__.py
    - pkm/prompts/summarize.v1.md
    - pkm/prompts/extract_claims.v1.md
    - pkm/prompts/er_extraction.v1.md
    - tests/test_base_agent.py
  modified: []

key-decisions:
  - "BaseAgent uses __init_subclass__ (not @abstractmethod) for ClassVar enforcement — ClassVars can't be abstract methods; __init_subclass__ fires at class-definition time giving immediate TypeError"
  - "No LLMClient import in pkm.agents.base — client injected via run() to avoid circular imports and simplify unit testing with MagicMock"
  - "Prompt files use plain Markdown (no code fences) with YAML-like indented examples per plan spec"
  - "chunk_id uses positional IDs (para_1, para_2) when source lacks explicit chunk markers — avoids null chunk_id except for truly untraceable claims with confidence <= 0.5"

patterns-established:
  - "Agent pattern: subclass BaseAgent, set 7 ClassVars, no logic needed — run() handles everything"
  - "Prompt versioning: <name>.v<N>.md filenames; prompt_version ClassVar used as LLMClient cache key"
  - "Test pattern: TDD RED commit (test(02-01): ...) then GREEN commit (feat(02-01): ...)"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-06-15
---

# Phase 2 Plan 01: BaseAgent ABC + Prompt Files Summary

**BaseAgent ABC with __init_subclass__ ClassVar enforcement, single run() delegation to LLMClient, and three versioned prompt files for Summarizer, Concept Extractor, and KG Agent**

## Performance

- **Duration:** 25 min
- **Started:** 2026-06-15T00:00:00Z
- **Completed:** 2026-06-15T00:25:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- BaseAgent ABC with 7 ClassVar attributes enforced at class-definition time: any subclass missing role, model, prompt_template, prompt_version, input_schema, output_schema, or memory_tier raises TypeError immediately
- Single run() implementation handles prompt loading, message building, LLMClient delegation, and cache detection — concrete agents only declare class attributes
- Three versioned prompt files (summarize.v1.md, extract_claims.v1.md, er_extraction.v1.md) covering all Phase 2 agents, each with role/task/input schema/output schema/constraints/example sections

## Task Commits

Each task was committed atomically:

1. **Task 1: BaseAgent ABC (RED — failing tests)** - `f73c85a` (test)
2. **Task 1: BaseAgent ABC (GREEN — implementation)** - `e7bd0b6` (feat)
3. **Task 2: Prompt files (3)** - `5768611` (feat)

_Note: Task 1 used TDD — test commit (RED) followed by implementation commit (GREEN)._

## Files Created/Modified

- `pkm/agents/__init__.py` — Package init for agents module
- `pkm/agents/base.py` — BaseAgent ABC: __init_subclass__ enforcement, _load_prompt(), run()
- `pkm/prompts/__init__.py` — Package init for prompts directory
- `pkm/prompts/summarize.v1.md` — Summarizer prompt: SummarizerOutput schema, chunk_id rules, confidence guidance, example
- `pkm/prompts/extract_claims.v1.md` — Concept Extractor prompt: SPO claims, concept_matches, canonical naming
- `pkm/prompts/er_extraction.v1.md` — KG Agent prompt: GraphNode stable slugs, 9 relationship types, provenance format
- `tests/test_base_agent.py` — 9 unit tests covering importability, ClassVar enforcement, _load_prompt, run() behavior

## Decisions Made

- Used `__init_subclass__` (not `@abstractmethod`) for ClassVar enforcement: Python ClassVars cannot be decorated as abstract methods. `__init_subclass__` fires at class-definition time, giving immediate TypeError before any instance is created.
- No LLMClient import in `pkm.agents.base`: the client is injected as a run() argument. This avoids coupling BaseAgent to infrastructure and makes unit testing trivial with `MagicMock`.
- `_load_prompt()` uses `Path(__file__).parent.parent / "prompts" / self.prompt_template`, which resolves correctly regardless of the caller's working directory.
- chunk_id uses positional IDs (`para_1`, `para_2`, `section_intro`) when the source lacks explicit chunk markers. The string literal `"null"` is reserved only for truly untraceable claims, with confidence forced to <= 0.5.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- BaseAgent ABC complete; Wave 2 plans (02-02, 02-03, 02-04) can proceed in parallel
- Each concrete agent needs: set 7 ClassVars, call `super().__init__()` implicitly (no custom __init__ needed), and the prompt file already exists for all three agents
- ReaderAgent (02-02) will need its own prompt file (reader.v1.md) — not included in this plan

---
*Phase: 02-core-agents*
*Completed: 2026-06-15*
