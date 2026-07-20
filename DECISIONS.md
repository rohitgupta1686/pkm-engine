# PKM Engine — Decisions Log

Mode A (reversible) and Tier-1 (MVP gate batch) decisions recorded here.
See `PKM_Build_Plan_for_Claude_Code.md` §Operating Modes for the distinction.

---

## Reversible Decisions (Mode A)

Logged autonomously during execution. These are reversible — rework < 1 day.

---

### Execution — local Gemini OCR for image source notes (2026-07-20)

Implemented the approved `pkm ingest-notes --ocr` pre-pass. It is opt-in and
Mac-local: a separate `GEMINI_API_KEY` calls Gemini 3 Flash Preview only for image
embeds referenced by the current source note. The original embed stays intact;
a marked transcription block is supplied in-memory to GLM synthesis. OCR cache
files live in committed vault state at `notes/.ocr-cache/<slug>.json`, keyed by
image SHA, so unchanged images make zero calls. Referenced image changes trigger
re-synthesis; missing/fresh/corrupt/oversized/unsafe-path images fail closed.

Pillow validates and downscales images to a 1536px maximum edge before upload.
OCR uses `max_tokens` (4,096) at Gemini's compatibility endpoint and participates
in the normal run cost cap. It remains intentionally absent from GitHub Actions.

### Research — evaluated OpenRouter / DeepSeek for GLM-5.2; no swap now (2026-07-14)

User asked whether the GLM-5.2 synthesis call should move behind OpenRouter, and to
check DeepSeek pricing. Researched (prices per 1M tokens, output dominates cost;
sources fetched 2026-07-14):

| Option | Input | Output | Cached | Note |
|---|--:|--:|--:|---|
| **GLM-5.2 direct — Z.AI (current)** | 1.40 | 4.40 | 0.26 | sync; explicit cheap cached input |
| GLM-5.2 via OpenRouter | 0.924 | 2.904 | n/a\* | ~34% cheaper, same model; sync |
| GLM-4.6 via OpenRouter | 0.43 | 1.74 | n/a\* | older |
| GLM-4.7 Flash via OpenRouter | 0.00 | 0.00 | 0.00 | free tier |
| DeepSeek v4-flash (direct) | 0.14 | 0.28 | 0.0028 | cheapest paid; 1M ctx; OpenAI-compat |
| DeepSeek v4-pro (direct) | 0.435 | 0.87 | 0.0036 | 1M ctx |

\* OpenRouter prompt-cache behavior is provider-dependent and unconfirmed for GLM-5.2,
so the Z.AI $0.26 cached rate (which benefits the fixed ~1,900-token system prompt every
call) may not carry over. OpenRouter also adds a 5.5% fee on credit top-ups (no per-token
markup). Note the Batch 50% discount is already gone — Z.AI is sync-only.

- **Decision: no swap now.** Total spend to date is ~$0.35, so the ~34% raw cut on the
  same model saves pennies; not worth a vendor change on cost alone. Staying on Z.AI
  GLM-5.2 is simplest and already working.
- **OpenRouter is the documented on-ramp when optionality/privacy is wanted.** Its real
  value is turning model choice into a one-line `SYNTHESIS_MODEL` change (trial DeepSeek
  v4-flash — ~15–30× cheaper — or free GLM-4.7 Flash) with one key and no new provider
  accounts, plus the ability to restrict to providers that don't log/train (a plus for a
  personal vault currently sent straight to a Chinese provider). The bigger cost lever is
  the model (DeepSeek v4-flash), not the gateway.
- **When executed, it's an env-only flip:** `OPENAI_BASE_URL=https://openrouter.ai/api/v1`,
  new `OPENAI_API_KEY`, `SYNTHESIS_MODEL=z-ai/glm-5.2` (or `deepseek/deepseek-chat`), plus a
  `PRICING` entry for the new model id (`compute_cost` raises `KeyError` by design otherwise).
  Verify first: strict `json_schema` structured-output support on the chosen route,
  `max_tokens` vs `max_completion_tokens` acceptance (`pkm/llm/client.py` already branches
  on the Z.AI base URL), and whether prompt caching applies.
- **Sources:** openrouter.ai/z-ai/glm-5.2, openrouter.ai/z-ai/glm-4.6/pricing,
  api-docs.deepseek.com/quick_start/pricing, bigmodel.cn/pricing, and OpenRouter's 5.5%
  top-up fee (ofox.ai breakdown, 2026).

---

### Execution — primary synthesis provider switched to Z.AI GLM-5.2 (2026-07-10)

The planned OpenAI → GLM-5.2 swap is executed. Z.AI's GLM-5.2 docs confirm the
OpenAI-compatible chat-completions endpoint and model id, so the system keeps the
existing `openai.OpenAI(base_url=...)` SDK seam instead of adding a second provider
path.

- **Default endpoint/model:** `OPENAI_BASE_URL=https://api.z.ai/api/paas/v4/`,
  `SYNTHESIS_MODEL=glm-5.2`; `OPENAI_API_KEY` is retained as the env var name but
  now contains the Z.AI API key.
- **Pricing:** `pkm/llm/pricing.py` now includes `glm-5.2` at $1.40 input,
  $0.26 cached input, $4.40 output per 1M tokens (Z.AI pricing page checked
  2026-07-10), preserving the existing fail-loud cost guardrail.
- **Compatibility:** GLM-5.2 expects `max_tokens`, while OpenAI GPT fallback paths
  still use `max_completion_tokens`; `pkm/llm/client.py` branches on GLM / Z.AI
  base URL. Covered by `tests/test_llm_client.py`.
- **Article ingest:** Z.AI's documented compatibility surface is synchronous
  `/chat/completions`, not OpenAI's Batch API. `pkm batch-ingest` therefore uses
  the synchronous per-source path for GLM/Z.AI; the OpenAI Batch API code from
  the 2026-07-09 entry remains available as an OpenAI fallback.
- **Workflows:** per-clip ingest and weekly digest pass the Z.AI base URL and
  `SYNTHESIS_MODEL=glm-5.2` explicitly. Env overrides use bare settings names
  (`SYNTHESIS_MODEL`, `RUN_COST_CAP_USD`) because `Settings` has no env prefix.
- **Rollback:** set `OPENAI_BASE_URL=https://api.openai.com/v1`,
  `SYNTHESIS_MODEL=gpt-5.5`, and put an OpenAI key back into `OPENAI_API_KEY`;
  OpenAI pricing entries, the `max_completion_tokens` path, and Batch API
  transport remain in code.

---

### Execution — strip GLM-5.2's stray outer code fence at write time (2026-07-10)

After the GLM-5.2 switch, GLM intermittently returned the *entire* note — YAML
front matter and all — wrapped in a triple-backtick code fence. This trapped the
`---` delimiters inside the fence, so Obsidian rendered the note as one gray code
block and `sanitize_frontmatter` (which needs `---` at byte 0) no-op'd, writing the
broken note verbatim; the downstream frontmatter-review pass then skipped it. Two
notes from the 2026-07-10 ingest were affected.

- **Fix:** new `strip_outer_code_fence` sanitizer in `pkm/store/notes.py`, wired as
  the first step in `write_note` (before `sanitize_frontmatter`). It unwraps a
  leading bare/`markdown`/`md` fence + matching trailing fence only when both are
  present, which is unambiguous because a well-formed note always starts with `---`.
  Idempotent; leaves interior code/mermaid blocks intact.
- **Scope:** this is the same write-time "absorb the model's output quirks" seam as
  the existing frontmatter/mermaid sanitizers — a provider behavior difference, not
  a prompt change. GPT-5.4 rarely emitted the wrapping fence; GLM-5.2 does.
- **Repair:** the two already-written broken notes were re-run through the sanitizer
  chain in place (pkm-vault repo), restoring parseable front matter.
- **Tests:** `tests/test_synthesize.py` covers bare/`markdown` wrap, no-op on a
  well-formed note, idempotency, interior-mermaid preservation, and end-to-end
  `write_note` unwrap.
- **Follow-up (not done):** callouts occasionally emit bare `- ` bullets missing the
  `> ` prefix inside `[!question]` blocks — prompt-level, tracked separately.

---

### Article ingest → OpenAI Batch API on `gpt-5.5`, fired per-clip (2026-07-09)

Two changes to the article path (`raw/` → `notes/`), requested by the user:

1. **Model `gpt-5.4` → `gpt-5.5`.** New default in `pkm/config.py` (`synthesis_model`
   → `GPT55` in `pkm/llm/models.py`) and a `PRICING["gpt-5.5"]` entry ($5.00 / $30.00
   per 1M in/out — 2× gpt-5.4). Adding the pricing entry is mandatory: `compute_cost`
   raises `KeyError` on an unknown model by design, so every path (`ingest`, `digest`,
   `ingest-notes`) would have broken otherwise.
2. **Batch API for `batch-ingest`.** The nightly/per-clip article path now submits all
   new captures as ONE OpenAI Batch job instead of N synchronous calls. Batch bills at
   **50% off**, so `gpt-5.5` via batch = **$2.50 / $15.00** — the *same* per-token cost
   as the old `gpt-5.4` sync path. A cost-neutral model upgrade. New `batch: bool` param
   on `compute_cost` applies the 0.5 discount; new `pkm/pipeline/batch_ingest.py`
   (`prepare_requests` + `run_batch_ingest`) reuses the sync path's pre-synthesis
   decisions and `write_note`; batch transport (`build_batch_request` / `submit_batch` /
   `poll_batch` / `collect_batch`) added to `pkm/llm/client.py`, sharing the request body
   with `_generate` via a new `_chat_kwargs`. Tests: `tests/test_batch_ingest.py`
   (`FakeBatchClient`, no OpenAI). `digest` / single `ingest` / `ingest-notes` stay
   synchronous but on `gpt-5.5`.

**Per-clip trigger.** Uncommented `repository_dispatch: types: [ingest]` in
`.github/workflows/ingest.yml` so a note is synthesized right after a clip lands (the
capture Worker already fires `repository_dispatch(ingest)` on every clip — no Worker
change). The nightly `schedule` stays on as an idempotent backstop (`--new-only`).
`timeout-minutes` 30 → 360 because the job now block-polls the batch.

**Decisions within this:**
- *Blocking poll in one job*, not a split submit/collect workflow. Preserves the
  DB-free / single-job / no-state-handoff design; pkm-engine is public → free Actions
  minutes. In-job `batch_timeout_sec` (90 min) cancels a stalled batch so it can't bill
  without committing a note; next run re-submits.
- *Cost cap moved pre-submit.* Batch is all-at-once, so the old in-memory per-item
  early-abort can't apply. `prepare_requests` estimates tokens and defers sources once a
  batch's projected (batch-rate) cost would exceed `run_cost_cap_usd`; deferred sources
  are picked up next run.
- *Intra-batch limitation accepted.* Requests are built from one up-front notes snapshot,
  so notes in the same batch can't cross-link to / vary wildcard frames against each
  other. Immaterial at per-clip volume (batch ≈ 1); only the backstop batch co-locates
  multiple notes.

**Latency trade:** "immediately" = the trigger fires the instant a clip lands, not that
the note appears in seconds — the Batch API is async (minutes typically, up to a 24h SLA).
We took the 50% discount over sync's ~13s latency, which is what "use the batch API" implies.

**Config env note (correctness):** `Settings` sets no `env_prefix`, so env overrides bind
to the bare field name uppercased (`SYNTHESIS_MODEL`, `RUN_COST_CAP_USD`, `BATCH_TIMEOUT_SEC`)
— the `PKM_`-prefixed names in older docs/workflow did **not** bind (the old
`PKM_RUN_COST_CAP_USD` was a no-op that happened to equal the default). Left the prefix
alone (a blanket `PKM_` would break `OPENAI_API_KEY`); drove the model via the code default
and corrected the workflow comment.

---

### Reversal — cloud OpenAI `pkm-engine` is primary again; digest ported; `pkm-engine-local` to standby (2026-07-09)

**Reverses the 2026-06-25 entry below.** The user wants `pkm-engine` (OpenAI
`gpt-5.4`, GitHub Actions) to be the go-forward engine for all ingests again,
to burn the existing OpenAI credit, with a later planned swap OpenAI → GLM-5.2
once that credit is exhausted (see the GLM runbook further down). Empirically,
the two engines were near-siblings: the synthesis prompts are byte-identical
across repos, and `pkm-engine` already had the richer machinery (cost cap,
`pkm/llm/pricing.py`, `BaseLLMClient` cache/cost seam). The only real feature
gap was the weekly digest, which lived solely in `pkm-engine-local`.

- **Articles** (`raw/` → `notes/`): nightly batch CI on OpenAI. Re-enabled the
  `schedule: cron "0 3 * * *"` in `.github/workflows/ingest.yml` (kept
  `repository_dispatch` commented — nightly batching is enough).
- **Weekly digest** (`notes/` → one cross-note briefing): ported from
  `pkm-engine-local/pkm_local/digest.py` into `pkm/pipeline/digest.py` +
  `pkm/prompts/digest.v1.md` + a `pkm digest` CLI subcommand, and given its own
  weekly CI workflow (`.github/workflows/digest.yml`, Sundays 04:00 UTC, its own
  `concurrency: group: digest` so it never contends with the nightly ingest).
  The only real adaptation from the local version: the local engine folds the
  whole prompt into a single user turn with a `_TASK_BRIDGE` (a CLIProxyAPI/
  Claude-OAuth workaround); on OpenAI the digest prompt is a normal **system**
  message and the notes-block context is the **user** message, exactly like
  `pkm/pipeline/synthesize.py` already does. Tests: `tests/test_digest.py`
  (fake client, no OpenAI calls). No pricing change — `gpt-5.4` was already in
  `pkm/llm/pricing.py`.
- **Book/podcast source-notes**: no code change — `pkm ingest-notes` already
  exists in `pkm-engine` and reads `SOURCES_DIR`. Runs **manually on the
  Mac** with OpenAI instead of on the Mac with `pkm-engine-local`/CLIProxyAPI —
  the iCloud source folder is only reachable from the Mac, and the mid-sync
  safety guard only works reading iCloud directly. See the README's
  "Book/podcast source-notes (Mac-run)" section.
- **`pkm-engine-local`**: retired to standby (code untouched, no longer the
  primary path). Reversible: re-disable the two cron triggers and switch the
  Mac-run source-notes command back to `pkm-local ingest-notes` to revert.

---

### Switching provider to GLM-5.2 (superseded by 2026-07-10 execution)

This was the original runbook for a future provider switch. It is now superseded
by the 2026-07-10 execution entry above: `glm-5.2` pricing exists, the token
parameter branch exists, `GLM52` exists, and the workflows now target Z.AI.

---

### Source-notes ingest — `pkm ingest-notes`, Markdown in iCloud, full re-synthesis (2026-06-30)

A second input path beside article clips: personal notes on long-form sources I'm
consuming — **books AND podcasts/lectures/talks/courses**. One `.md` per source in
a capture folder (an Obsidian vault synced via iCloud), read by a new local CLI
`pkm ingest-notes`. The input is *my fragmentary notes about* a source, not the
source's full text, so it uses a separate prompt (`pkm/prompts/synthesis-notes.v1.md`)
with sections What this is / Big ideas / Notes & highlights / My reactions /
Connects to. Reuses the single-call machinery: `synthesize_note` gained a
`prompt_template`/`prompt_version`/`agent_name` parameter so the article path is
byte-unchanged; `write_note`, slugs, cross-links and the cost cap are shared.

Three v1-scope choices, each chosen for simplicity over the original (Opus-reviewed)
design and each reversible:

1. **Format = Markdown, not `.docx`.** Binary Word files create non-mergeable iCloud
   conflict copies (→ orphaned notes) and need `python-docx`; plain text makes the
   delta SHA bulletproof and drops the dependency. The user already lives in Obsidian.
2. **Full re-synthesis on any body change** (skip when content SHA is unchanged) —
   *not* the originally designed incremental paragraph-append. Re-running one clean
   call keeps the note coherent and is on-brand with the June-2026 single-call
   redesign. Append-optimization is deferred until per-source cost is a real problem.
3. **State keyed by slug** in `notes/.notes-state.json` (committed in the vault).
   Renaming a capture file changes its slug → treated as a new source, old note
   orphaned. The rename-proof `pkm_id`-in-frontmatter anchor is a documented future
   upgrade; state is rebuildable any time.

iCloud safety: files modified within 60s (mid-sync) or unreadable are skipped that
run. OCR of pasted page/slide photos is deferred (`![[image]]` refs pass through
untouched; a `--ocr` flag is the planned follow-up). Spend is capped exactly like
`batch-ingest` (soft cap, may overshoot by one call). Tests: `tests/test_ingest_notes.py`
(14, fake client, no OpenAI). Constraints held: $0 infra, no DB, no secrets; the
"zero local daemon" constraint is already relaxed for the local-engine path this
runs alongside. Reversible: delete the new modules + prompt + state file to revert.

---

### Sibling engine `pkm-engine-local` — local Claude account via CLIProxyAPI (2026-06-25)

A second, additive engine lives in `../pkm-engine-local`. It routes each synthesis
call to a [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) instance on
localhost (port 8317) that fronts a device's own Claude account over OAuth, instead
of the OpenAI API. The two share one vault and produce byte-identical notes (the
prompt `synthesis.v3.md` and `store/notes.py` conventions are copied verbatim). The
local engine delivers the prompt in the **user turn** (a Claude Code OAuth token
makes the upstream inject its own "You are Claude Code" identity into the system
slot, which otherwise out-prioritizes a system-message prompt and triggers a
refusal). Model: `claude-opus-4-8`.

This engine (`pkm-engine`) keeps its single-call OpenAI code intact, but its CI
**ingest workflow auto-triggers were disabled** (`repository_dispatch` +
nightly `schedule` commented out; `workflow_dispatch` kept) so CI no longer
pre-empts the local run and re-incurs OpenAI spend on every clip. The capture
worker is unchanged — it still commits `raw/*.md` and may still fire
`repository_dispatch(ingest)`, which is now a no-op. OpenAI ingestion remains a
manual fallback (run the workflow by hand, or re-enable the triggers).

Rationale: the user runs the system only on two Macs (two Claude accounts) and
wants $0 LLM spend by using the existing flat-rate Claude subscriptions rather than
paying per-token for OpenAI. CLIProxyAPI is a localhost daemon GitHub Actions can't
reach, so synthesis necessarily relocates onto the Mac and runs as a manual command
(`make ingest` / `make publish`). The capture path (clip → `raw/`) is unchanged.

**Constraints knowingly traded — scoped to the new engine only:** "Zero local
daemon — nothing runs on the Mac" and "ingestion is GitHub Actions only" do NOT
hold for `pkm-engine-local` (the proxy is a user-launched process; ingestion is
local + manual). All other hard constraints hold and are in fact reinforced: $0
infra (free tier + existing subscription, no per-call cost), `raw/` immutable, no
database, no secrets committed. Surfaced to the user (Mode C) before building; they
chose a separate engine over amending this one. Reversible: deleting the sibling
repo restores the original single-engine setup with no change here.

---

### Frontmatter sanitizer — quote free-text fields at write time (2026-06-24)

The model writes each note's YAML frontmatter itself. Two notes ingested 2026-06-24
had titles containing `: ` (e.g. `title: The Existence Project: Inside…`), which
YAML reads as a nested mapping → the block failed to parse, so Obsidian saw no
metadata and the notes vanished from every Dataview view (`Home.md`, Card Catalog).

Fix: `sanitize_frontmatter()` in `store/notes.py`, wired into `write_note` so every
write path is covered. It leniently extracts the `--- … ---` block (it can't be
`yaml.safe_load`ed — it's malformed by definition) and re-emits **only** the
free-text `title`/`source` lines via `yaml.safe_dump` (delegating quote/colon/pipe
escaping to the library, not hand-rolled). Structured fields (`saved`, `tags`,
`url`, `type`, `reading_time`) are left byte-for-byte to preserve Dataview's date
and list semantics. Idempotent. Titles kept **verbatim** — no `|`→`—` rewrite
(canonical metadata shouldn't silently diverge from the source; the pipe is YAML-
safe once quoted). Prompt template now shows `title: "<…>"` as defense-in-depth, but
the code sanitizer is the guarantee. `pyyaml>=6.0` promoted to a declared dep
(was transitive). Tests cover colon/pipe/quotes/apostrophes/idempotence. The two
broken notes were healed in `pkm-vault` by running the same function over their
on-disk text (no model call) — committed there separately.

Alternatives considered & rejected: (a) prompt-only quoting — relies on model
compliance, no guarantee; (b) full parse→`yaml.safe_dump` of the whole dict — can't
parse the malformed block, and stringifies `tags`/`saved`, breaking Dataview.

---

### Redesign — Single-call synthesis + model lock (2026-06-23)

The 8-phase graph pipeline (atomic SPO claims, concepts, Turso/Vectorize, 4-agent
chain + per-concept synthesis) is being replaced by ONE LLM call per source →
one readable Markdown note (`pkm/pipeline/synthesize.py` + `ingest_note.py` +
`store/notes.py`; prompt `pkm/prompts/synthesis.v3.md`). Rationale: the graph
optimization was the root cause of slow/complex/unreadable output. See
`docs/LEGACY_RETIREMENT_PLAN.md` for the staged teardown.

**Model locked: `gpt-5.4`** (`PKM_SYNTHESIS_MODEL`, full model — NOT the mini the
legacy pipeline pinned). Pricing added to `pkm/llm/pricing.py`: $2.50 / $0.25 /
$15.00 per 1M in/cached/out. ~$0.032/note, ~13s/note. Decision basis: a blind
4-capture A/B vs `gpt-5.4-mini` (`scripts/compare_models.py`). Both near-tied on
faithfulness + scannability, but gpt-5.4 reliably produced the apt Mermaid visual
AND an earned wildcard on every note while mini omitted both on all 4 — i.e. only
the full model delivers the redesign's "scannable, visual, surprising" thesis. The
mini is ~3.7x cheaper and remains the fallback if cost ever needs cutting.

---

## Phase 5 — Capture Worker

**[T2-05-01] Q1 — R2 offload for >200K text.** Keep the FULL text in the `raw/` body
AND mirror a copy to R2 when `text.length > 200_000`, storing the `r2key` in the
`raw/` front matter. The body is **NEVER reduced to a pointer**. Rationale: the
ingest pipeline (`pkm/pipeline/ingest.py::run_ingest`) cannot read R2 and synthesizes
from `raw_text` read out of the `raw/*.md` body — a pointer body would make the LLM
summarize "[blob in R2: ...]". The R2 mirror is belt-and-suspenders that sets up a
future "pipeline fetches R2" path. Tradeoff: Git still holds >200K text at MVP scale
(rare; Git handles text well). Reversible: a future phase can teach the pipeline to
fetch from R2 and reduce the body. Cross-ref `05-RESEARCH.md` Pitfall 6.

---

**[T2-05-02] Q2 — single fine-grained PAT scoped to `contents:write` on BOTH
`pkm-vault` (commit `raw/`) AND `pkm-engine` (fire `repository_dispatch`).** Stored as
one Worker Secret `GH_PAT` via `wrangler secret put`. Rationale: firing
`repository_dispatch` against `pkm-engine` requires `contents:write` on
`pkm-engine`; the **PKM Cloud Architecture doc §11 only mentions the `pkm-vault`
scope**, which would **403 the dispatch** silently. The README corrects this and
scopes the PAT to both repos. Tradeoff: one token has broader scope than two
isolated tokens (a single compromise touches both repos). Reversible: split into
`VAULT_PAT` + `ENGINE_PAT` any time. `X-PKM-Key` is a separate Worker Secret
(authentication, not GitHub) — see `wrangler.toml`.

---

**[T2-05-03] Q3 — re-clip of an existing `raw/` path.** The Worker does GET-then-PUT;
on an existing path (GET 200) it skips the PUT commit (200 no-op for the commit
step) BUT still fires `repository_dispatch(event_type:"ingest")`. Rationale: gives a
manual re-trigger path from the clipper (re-run the pipeline on a source without
re-clipping the text); downstream pipeline dedups via the `sha256(raw_text)` cache
(ORCH-07 → 0 LLM calls, 0 new rows). Tradeoff: a few GitHub Actions minutes per
re-clip even when nothing changes. Reversible: could suppress the dispatch on a
no-op commit.

**[T2-05-04] Claim chunk_id FK — map LLM positional labels to real chunks.ids.**
The summarizer/extractor prompts instruct the LLM to emit positional chunk_id
labels ("para_1", "section_body") or the "null" sentinel, because the model
cannot see the deterministic `chk_<hash>_NNN` chunk ids. `claims.chunk_id` has a
hard FK to `chunks(id)` (AD-6), so any non-null value that isn't a real
`chunks.id` crashes `batch_ingest` on the FK — found in the 05-03 live run
(nondeterministic: only fails when the LLM emits a positional label, not
"null"). `run_ingest` now resolves every claim's `chunk_id` via
`_resolve_claim_chunk_id` before insert: a real `chunks.id` is kept; `para_N`
maps to ordinal `N-1`'s chunk id when in range; everything else (including
"null") becomes SQL NULL. Rationale (vs the alternative of dropping the FK):
keeps the provenance contract and the existing
`test_claim_null_chunk_id_sentinel_satisfies_fk` invariant ("a bogus real
chunk_id must still be rejected") intact, with no schema migration. Tradeoff:
the `para_N → ordinal` mapping is heuristic (chunks are ~1200-token windows, not
paragraphs), so provenance is best-effort and some claims land on NULL. The
drop-FK alternative (free-text provenance, richest signal) is deferred to MVP
review as a Type-1 contract change. Reversible: pure ingest-code change, no
migration; re-ingest repopulates `claims.chunk_id`.

---

---

### Phase 3 — Vault Scaffold (03-01)

**Decision:** Build-plan prose maps to DB claims.status value `candidate` — the
schema CHECK constraint in `migrations/sqlite/001_init.sql` does not permit any
other value as the initial claim status. The valid initial status is `candidate`.
SCHEMA.md documents the four valid claims.status values: `candidate`, `approved`,
`merged`, `rejected`. This is locked from Phase 1 and cannot be changed without
a migration.

---

### Phase 1 — Data Layer

**Decision:** `setuptools` package discovery scoped to `pkm*` only — `migrations/`
dir caused flat-layout error if discovered.

**Decision:** `libsql_experimental.execute()` only runs first SQL statement — all
migration runners use `executescript()`.

**Decision:** `anthropic_api_key` has empty string default in Settings for
test-context compatibility.

---

### Phase 1 — Wave 2

**Decision:** INSERT OR REPLACE (not INSERT OR IGNORE) in `_write_run` — ensures
an ok-row overwrites a prior error-row for the same `(agent, input_hash)`.

**Decision:** LLMClient uses tool-calling (`tools=[] + tool_choice`) when
`output_schema` provided — JSON schema enforcement at API level.

**Decision:** LLMClient takes explicit `conn + api_key` — no Settings singleton
inside client for testability.

**Decision:** Migrations dir resolved via `Path(__file__)` so it works regardless
of `cwd` (tests use `os.chdir`).

---

### Phase 2 — Wave 2 (02-04)

**Decision:** Tier 3 embedding resolution stubbed (logs debug, returns None) per
AD-5 MVP constraint — no Opus call, no API spend at extraction time.

**Decision:** `resolver.py` SQL uses parameterized `?` placeholders throughout
(T-02-08 SQL-injection mitigation).

**Decision:** `noisy_or()` is a pure function with no DB dependency — enables
isolated unit testing.

---

### Phase 2 — Wave 2 (02-03)

**Decision:** `chunk_id="null"` string convention as data contract — confidence
<= 0.5 enforced in test; Python `None` is not used; the string `"null"` is the
sentinel value for untraceable claims.

**Decision:** `repair-retry` test patches `pkm.llm.client.anthropic.Anthropic`
and re-creates `LLMClient` inside the patch context — cannot patch after
`__init__` because `self.client` is bound at construction time.

**Decision:** `ConceptMatch.claim_indices` is `list[int]` — pydantic rejects
string indices at validation gate (mitigates T-02-05).

---

### Phase 2 — Wave 1 (02-01)

**Decision:** `BaseAgent` uses `__init_subclass__` (not `@abstractmethod`) for
ClassVar enforcement — ClassVars cannot be abstract methods; `__init_subclass__`
fires at class-definition time giving immediate `TypeError`.

**Decision:** No `LLMClient` import in `pkm.agents.base` — client injected via
`run()` arg to avoid coupling and enable `MagicMock` testing.

**Decision:** `chunk_id` uses positional IDs (`para_1`, `para_2`) when source
lacks explicit markers; string `"null"` reserved for untraceable claims with
confidence <= 0.5.

---

## Tier-1 Batch (for MVP gate review)

Tier-1 decisions: proceed on default, list here, revisit at Phase 8 MVP gate.

---

**[T1-01] Vectorize chosen over Turso native vectors** (default per cloud doc §7.2)

Better for the edge query Worker; 5M vectors free; co-located with other
Cloudflare services. Revisit at MVP gate if Turso native vectors reach parity.

---

**[T1-02] Cloud pipeline LLM backend switched Anthropic → OpenAI GPT-5.4-mini** (locked 2026-06-19)

The cloud GitHub Actions ingest pipeline moves from the Anthropic SDK to OpenAI
`gpt-5.4-mini-2026-03-17` via the standard synchronous Chat Completions API.
Resolved via fresh-context Opus adversarial pass (verdict: lock-with-conditions)
and explicit user Mode-C acceptance of three conditions:

1. **Dispatch path = standard sync API, NOT Batch.** The OpenAI Batch API is
   async with a 24h SLA and cannot satisfy the locked Phase-4 `<10-minute`
   dispatch budget (`04-03-PLAN.md`, `ingest.yml: timeout-minutes: 10`). A Batch
   bulk/backfill path is deferred to a separate follow-up PLAN; it must not
   claim the `<10-min` criterion or block the dispatch flow.
2. **$0-infra exception (bounded per-token spend).** OpenAI is pay-as-you-go,
   not a free tier, so this modifies the `$0 infrastructure` hard constraint.
   Accepted in spirit (per-token usage ≠ recurring infra) but gated on a
   **per-run token/$ ceiling that aborts the batch** plus real `cost_usd`
   computation from usage — both MUST exist before the workflow runs on
   Actions. `client.py:220` currently hardcodes `cost_usd = 0.0`; that is a
   blocker for wiring this in. Revisit at MVP gate.
3. **Cache-bust accepted (one-time full re-ingest).** `_make_input_hash`
   (`client.py:27-29`) includes the model string in the cache key, so the model
   change busts every `agent_runs` ok-row. First post-switch run re-runs all
   agents for all sources once, rewrites wiki pages, and costs one full pass.
   Accepted deliberately — no hash-remap migration. Note: any future model
   bump will re-bust the cache the same way; a cache-versioning scheme that
   separates model identity from cache validity is the durable fix (deferred).

Migration is Type-2 (reversible-in-a-day): confined to `pkm/llm/client.py`
(rewrite SDK import, constructor, `_call_api`, structured-output,
repair-retry, usage/error handling), `pkm/llm/models.py` (model constants),
`pkm/config.py`, `pkm/cli.py`,
`.github/workflows/ingest.yml` (`OPENAI_API_KEY` secret), `docs/SECRETS.md`,
and the agent `model` ClassVars. Agent prompts under `pkm/prompts/*.md` reference
"the `structured_output` tool" (Anthropic tool-calling wording) — must be reworded
for OpenAI `response_format: json_schema` (strict). Agents themselves are
provider-agnostic (only declare pydantic `output_schema`), so blast radius stays
in `client.py` + prompt wording. No DB schema migration.

**Provider architecture (refined during 04-04 planning):** OpenAI SDK is the sole
client; the `anthropic` dependency, `anthropic_api_key`, `llm_provider`, and
`ollama_*` Settings fields are **removed entirely** (no runtime provider branch —
that would be the "parallel provider path" the decision forbids). Added: `openai_api_key`,
`openai_base_url` (default `https://api.openai.com/v1`), `llm_model` (default `MINI`),
`run_cost_cap_usd`, `run_token_cap`. Agents read `settings.llm_model` (one model for
all agents — the HAIKU/SONNET distinction collapses to a single gpt-5.4-mini). Any
Anthropic-model usage routes through an OpenAI-compatible endpoint (e.g. CLIProxyAPI)
via the OpenAI SDK + `openai_base_url` + `llm_model` set to a claude-* id; CLIProxyAPI
`/v1/chat/completions` support is unverified, so local Claude dev is a nice-to-have, not
a 04-04 gate.

Relates to memory `project-pkm-llm-backend-decision` (resolved).

---

## Phase 8 MVP-gate review (2026-06-21)

Recorded at the Phase 8 MVP gate. This section records **dispositions and
condition verification only** — it does NOT lock any new Type-1 decision. The
MVP-ready / V1-advancement call is a human judgment reserved for the
`08-MVP-REVIEW.md` checkpoint (Type-1, irreversible per CLAUDE.md "Stop at MVP
gate"). Language here is "reaffirm" / "PASS" / "carried to MVP review", never
"locked".

### T1-01 — Vectorize over Turso native vectors

**Disposition: reaffirm.** Turso native vectors have not reached parity on the
edge-query-worker use case. Vectorize is live and load-bearing: the
`pkm-claims` Vectorize index was created and 160 claims embedded in Phase 6
Wave 3; `worker-query.js` (deployed `https://pkm-query.rohitgupta-iitr.workers.dev`)
depends on it for embed → search → synthesis. No change at the MVP gate.

### T1-02 — OpenAI GPT-5.4-mini backend (locked 2026-06-19)

Three locked conditions, each verified against the current code (file:line):

1. **Dispatch = sync API, not Batch — PASS.**
   `.github/workflows/ingest.yml:20` → `timeout-minutes: 10`, matching the
   locked `<10-minute` dispatch budget. `pkm/llm/client.py` uses the
   synchronous Chat Completions endpoint (`_call_api` → `client.chat.completions`);
   no Batch API call exists in the codebase. The 24h-async Batch path remains
   deferred and does not claim the `<10-min` criterion.

2. **cost_usd computed from usage, not hardcoded 0.0 — PASS.**
   `pkm/llm/client.py:352` → `cost_usd = compute_cost(model, tokens_in,
   cached_tokens, tokens_out)`. `pkm/llm/pricing.py:40` → `p = PRICING[model]`
   raises `KeyError` on unknown model (fail-loud, never returns 0.0 — the
   original `client.py:220` blocker cited in the lock is resolved). This is
   load-bearing for MVP-06: the cost actuals in `PROGRESS.md` are derived from
   the real `agent_runs.cost_usd` values this path writes (see PROGRESS.md
   "Cost Actuals" — `SUM(cost_usd) FROM agent_runs`).

3. **Cache-bust accepted — PASS.**
   `pkm/llm/client.py:168-174` → `_make_input_hash(agent_name, model,
   prompt_version, input_text)` includes the model string in the SHA-256 cache
   key, so the model change busts every `agent_runs` ok-row. The one-time full
   re-ingest has occurred — the ~160-claim corpus reflects post-switch ingest
   (Phase 6 Wave 3). The durable cache-versioning fix (separating model
   identity from cache validity) remains deferred as noted in the lock.

**All three conditions PASS. No revision to T1-02 at the MVP gate.**

### Tier-1-class items accumulated since Phase 1 — carried to MVP review

- **[T2-05-04] drop-FK / free-text-provenance deferral — carried to MVP review.**
  The current ingest path resolves `claims.chunk_id` heuristically (`para_N →
  ordinal`; everything else → SQL NULL), so provenance is best-effort and some
  claims land on NULL `chunk_id` (the missing-provenance count recorded in
  `docs/PHASE8_VERIFICATION.md` MVP-03). T2-05-04 explicitly defers the
  drop-FK / free-text-provenance alternative to MVP review **as a Type-1
  contract change**. It is NOT locked here; the human decides at the
  `08-MVP-REVIEW.md` checkpoint whether to accept the best-effort limitation
  for MVP or pursue the contract change in V1.

No other Tier-1-class decisions found outside the Tier-1 Batch section.

---

---

## 2026-06-22 — LLM provider abstraction + Gemini (free tier) as default

**Decision (Type-2, reversible by one config flag — flagged for MVP review as a
vendor-surface change).** Operator directed moving LLM calls to Google AI Studio
(Gemini Flash, free tier) to hold the $0 goal on inference. Implemented as a
provider abstraction so OpenAI remains pluggable.

- **Shared orchestration** (`pkm/llm/base_client.py::BaseLLMClient`): hash cache,
  `agent_runs` writes, validate→truncation-retry→repair-retry, cost hook — vendor
  independent. `call(...)` contract unchanged, so the 4 agents + concept synthesis
  are untouched.
- **Providers**: `pkm/llm/client.py::LLMClient` (OpenAI, refactored onto the base,
  test patch points preserved) and `pkm/llm/gemini_client.py::GeminiClient`
  (native Gemini REST over httpx). Selected via `pkm/llm/factory.build_llm_client`
  from `settings.llm_provider` ("gemini" default | "openai").
- **Model selection**: agents pass the logical sentinel `gemini-flash-auto`
  (stable cache key); `GeminiClient` lists Flash models at startup (logged) and
  tries them in DECREASING version order (3.5 → 3.1 → 3 → 2.5 …, full flash before
  flash-lite), falling back on failure. Concrete model recorded in
  `agent_runs.model`.
- **Cost**: `GeminiClient._cost` returns 0.0 (free tier). Reverses the OpenAI
  ~$0.35/mo line in PROGRESS.md for forward ingestions.
- **Cache / re-ingest**: per operator, existing pages stay as-is — Gemini applies
  only to FORWARD ingestions. Existing sources dedup-skip (`--new-only` +
  `wiki_path` set) and never reach the model-keyed cache, so no re-ingest is
  triggered by the provider switch.
- **CI**: `ingest.yml` wires `GEMINI_API_KEY` + `PKM_LLM_PROVIDER`, but is pinned
  to `openai` until the operator adds the `GEMINI_API_KEY` secret (Claude cannot
  mint the key — requires the operator's Google login). Flip to `gemini` after the
  secret exists.
- **Tests**: +9 (`tests/test_gemini_client.py`); 173 pass. Worker `/query`
  synthesis still on OpenAI (out of scope this change).

**Constraint note (rate limits):** Gemini free tier is RPM/RPD-limited; the
existing exponential backoff absorbs 429s (slower batches, not failures).
