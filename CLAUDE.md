# AI-Assisted PKM System — Project Instructions

## Project

Clip an article → **one readable Markdown note**, produced by a **single OpenAI
GPT-5.4 call per source**. $0 infrastructure, no database, no local daemon.
Ingestion runs in GitHub Actions over a git checkout of the vault; the vault is
plain Markdown read in Obsidian (which provides backlinks/graph/search for free).

> **History:** the engine was redesigned in June 2026 from an 8-phase machine-readable
> knowledge graph (atomic SPO claims, concepts, Turso + Cloudflare Vectorize, a
> 4-agent chain + per-concept synthesis loop) to this single-call form. That graph
> optimization was the root cause of slow/complex/unreadable output. The old planning
> docs in `.planning/` and the spec/architecture docs are **historical** — do not
> treat them as current. The redesign rationale lives in `DECISIONS.md` (2026-06-23
> entry) and `docs/LEGACY_RETIREMENT_PLAN.md`.

**Repos:**
- `pkm-engine` — public GitHub repo (Python single-call pipeline, capture Worker, ingest workflow)
- `pkm-vault` — private GitHub repo (Markdown vault: `raw/` immutable captures, `notes/` synthesized notes)

## Architecture (current)

- **The engine = the prompt:** `pkm/prompts/synthesis.v3.md` (keep in sync with
  `pkm-prototype/SYNTHESIS_PROMPT.md`). One call in `pkm/pipeline/synthesize.py`.
- **Orchestration:** `pkm/pipeline/ingest_note.py` — reads existing note slugs (for
  `[[links]]`) + recent wildcard frames (for variety), writes `notes/<slug>.md`. No DB.
- **Note I/O:** `pkm/store/notes.py`. **LLM transport:** `pkm/llm/client.py` (OpenAI),
  run with `conn=None` (DB-free; `pkm/llm/base_client.py` only caches when given a conn).
- **CLI:** `pkm ingest` / `pkm batch-ingest` (aliases `synthesize` / `batch-synthesize`).
- **Source-notes path:** `pkm ingest-notes` reads a live Markdown capture folder
  (books/podcasts/lectures, one `.md` per source, synced via iCloud/Obsidian; set
  `PKM_SOURCES_DIR`) → `notes/`. Separate prompt `pkm/prompts/synthesis-notes.v1.md`
  (synthesizes *my notes about* a source, not the source text); delta state in
  `notes/.notes-state.json`. Reader `pkm/ingest/md_reader.py`; loop
  `pkm/pipeline/ingest_source_notes.py`. v1 = full re-synthesis on change, no OCR.
- **Model:** `gpt-5.4` locked (`PKM_SYNTHESIS_MODEL`); pricing in `pkm/llm/pricing.py`.
- **Tests:** `tests/test_synthesize.py` + `tests/test_ingest_notes.py` (both run without OpenAI via a fake client).

## Hard Constraints

- **$0 infrastructure** — free tiers only; no paid plan ever
- **Zero local daemon** — nothing runs on the Mac; ingestion is GitHub Actions only
- **`raw/` is immutable** — write-once; re-ingest is idempotent (note-file existence)
- **No secrets committed** — use `.env.example`, GitHub Actions Secrets, Worker Secrets
- **No database** — the Markdown vault in git is the only state

## Operating Mode: YOLO

Default to autonomy. Surface back (Mode C) ONLY for:
1. $0 goal breaks (infra would incur recurring cost)
2. Claude/LLM cost would exceed the spend cap for normal operation
3. A requested change is architecturally infeasible
4. Irreversible/migration-expensive decision not settled by `DECISIONS.md`
5. Trust/blast-radius: widening secret scope, making the vault public, an unnamed third party

Log reversible choices in `DECISIONS.md` (Mode A).

## Known follow-ups

- A markdown-native `lint` (broken `[[wikilinks]]`, orphans) and a notes-count
  `dashboard` could be rebuilt against `notes/` (the old DB-backed ones were retired).
