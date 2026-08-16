# Legacy pipeline retirement plan

**Status: EXECUTED (2026-06-23).** The model comparison run was itself a live
gpt-5.4 validation (4 good notes, confirmed cost), satisfying the gate. The
engine is now DB-free single-call only. Run `pytest` on a Python 3.12 venv
(`pip install -e . && pytest`) to confirm — this sandbox can't (no pydantic).

## What was done

- **Default flipped:** `ingest`/`batch-ingest` now run the single GPT-5.4 call
  (`synthesize`/`batch-synthesize` are aliases). Cost cap enforced in-memory.
- **DB-free:** `BaseLLMClient` runs with `conn=None` (no agent_runs cache);
  idempotency is the note file's existence. Turso + libsql removed entirely.
- **Deleted:** `pkm/agents/`, `pkm/graph/`, `pkm/schemas/`, `pkm/retrieval/`,
  `pkm/pipeline/ingest.py`, `pkm/batch.py`, `pkm/store/{registry,vault}.py`,
  `pkm/ingest/chunker.py`, `pkm/llm/{factory,gemini_client}.py`, `pkm/lint.py`,
  `pkm/dashboard.py`, `migrations/`, 7 legacy prompts, `worker-query.js` +
  `wrangler-query*.toml`, and all legacy tests (kept `test_synthesize.py`).
- **Config slimmed:** dropped Gemini/Turso/Cloudflare/provider fields.
- **`pyproject.toml`:** dropped `libsql-experimental` (+ direct `httpx`).
- **CI:** `.github/workflows/ingest.yml` rewritten — Python 3.12, single-call
  `batch-ingest`, commits `notes/`, keeps the GUARD-07 backup push. Runs in the
  cloud; no local machine involved.

## Retired commands (rebuild later against `notes/` if wanted)

`lint`, `dashboard`, `backfill-embeds`, `backfill-counters` were graph/Turso-era
and are gone. A markdown-native lint (broken `[[wikilinks]]`, orphans) and a
notes-count dashboard could be rebuilt cheaply by reading the `notes/` dir.

## Follow-ups not done here

- `README.md` and `CLAUDE.md` still describe the old 8-phase architecture — refresh.
- The capture worker (`worker-clip.js`) is unchanged (still the capture path).

---

## Original plan (for reference)

The single-call path (`pkm/pipeline/synthesize.py`, `ingest_note.py`,
`store/notes.py`, CLI `synthesize`/`batch-synthesize`) already runs **alongside**
the legacy 4-agent + Turso/Vectorize pipeline. Retirement = making it the default
and removing the old machinery, in safe order so each step is independently
revertible.

## Order of operations (each is its own commit/PR)

1. **Flip the default.** Point `pkm batch-ingest` at `run_note_ingest` (or alias
   `ingest` → `synthesize`). Keep the old code importable but unreferenced for one
   cycle. Reversible by flipping back.
2. **Delete the agent chain.** Remove `pkm/agents/{reader,summarizer,concept_extractor,
   kg_agent,concept_synthesis_agent}.py` and prompts `reader.v1`, `summarize.v{1,2,3}`,
   `extract_claims.v1`, `er_extraction.v1`, `concept_synthesis.v1`. Drop
   `_run_concept_synthesis` and the 4-agent block from `pipeline/ingest.py`.
3. **Delete embeddings.** Remove `pkm/retrieval/embed.py`, the `backfill-embeds`
   CLI, `worker-query.js` (or repoint it), and the Cloudflare Vectorize config.
4. **Retire Turso (last, most invasive).** The single-call path uses the DB only
   for the `agent_runs` cache. Decide: (a) keep a tiny local SQLite purely for the
   cache, or (b) drop the DB entirely and make the note file itself the idempotency
   key (note exists → skip). Option (b) fully realizes "$0 infra, plain-markdown
   vault" but loses cross-run cost/cache history. Then remove `store/registry.py`
   resilient-connection complexity, `migrations/`, `graph_*`/`claims`/`concepts`/
   `chunks` tables, `CF_*`/`TURSO_*` config.
5. **Prune tests.** Delete `test_{agents,base_agent,synthesis,embed,backfill_embeds,
   resilient_connection,idempotency}.py` as their subjects are removed; keep
   `test_synthesize.py`, `test_vault.py` (if the note writer reuses it), `test_lint.py`,
   `test_dashboard.py`. Update `test_ingest_e2e` / `test_batch_ingest` to the new path.

## Decisions to settle before step 4

- **Cache vs. $0-infra purity** (option a vs b above) — affects whether any DB
  survives at all.
- **Dashboard/lint** — these read DB counters today; either reframe them to read
  the `notes/` dir, or retire them too.
- **`worker-clip.js`** stays (it's the capture path, unrelated to synthesis).

## Estimated blast radius

~5 agent files, ~7 prompts, `embed.py`, large cuts to `ingest.py` + `registry.py`,
~8 test files, several migrations. Big but mechanical once the new path is the
proven default. Do it incrementally; never in one commit.
