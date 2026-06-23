# RESUME HERE — finishing the PKM redesign from any device

_Snapshot 2026-06-23. Everything below is reachable from GitHub; nothing depends on
the original Mac. Pick up from "What's left", in order._

## Where things stand

The PKM engine has been **redesigned and the legacy pipeline retired**. The change is
committed and pushed as a PR — NOT yet merged to `main`, so live clipping still runs
the old code until you merge.

- **PR:** https://github.com/rohitgupta1686/pkm-engine/pull/2
  (branch `redesign/single-call-db-free`, commit `c9010ca`).
- **What it does:** one OpenAI **gpt-5.4** call per source → one Markdown note in
  `<vault>/notes/`. No Turso/Vectorize/agents/database. Idempotency = note-file exists.
  Model is LOCKED to gpt-5.4 (blind A/B beat gpt-5.4-mini; ~$0.03/note). 40→16 files.
- **Secrets already set** on the pkm-engine repo: `OPENAI_API_KEY`, `VAULT_PAT`,
  `BACKUP_REMOTE_URL`. ✅
- **Vault:** `pkm-vault` has 11 `raw/` captures and no `notes/` dir yet (created on
  first run). Capture side (`worker-clip.js` + bookmarklet) is unchanged and assumed
  still deployed from the prior setup.

## What's left (do in this order)

1. **(Recommended) One live smoke before merging.** The DB-free `conn=None` code path
   has been static-checked + unit-tested with a fake client, but never made a real
   API call. On any machine with Python **3.12** (NOT 3.14 — no wheels):
   ```bash
   git clone https://github.com/rohitgupta1686/pkm-engine
   cd pkm-engine && git checkout redesign/single-call-db-free
   python3.12 -m venv .venv && source .venv/bin/activate
   pip install -e .
   pytest                       # should be green (only tests/test_synthesize.py)
   # then a real run against a vault checkout:
   export OPENAI_API_KEY=sk-...
   git clone https://github.com/rohitgupta1686/pkm-vault ../pkm-vault
   pkm batch-ingest --new-only --vault ../pkm-vault
   ```
   Eyeball a couple of `../pkm-vault/notes/*.md`. If good, proceed.

2. **Handle the 4 body-less stub captures** (paywall clips with only front-matter:
   doc.cc "sharp tool", livemint NSE IPO, moatsandmasala Hyrox, Verge Midjourney).
   Production `batch-ingest` has no empty-body filter, so it will feed these to the
   model and likely get junk/hallucinated notes. Either:
   - **delete them** from `pkm-vault/raw/`, OR
   - **add a min-body guard** to `run_note_ingest` (skip captures with empty bodies) —
     the durable fix; push to the same PR. (Claude offered to do either.)

3. **Merge PR #2 → `main`.** This is the switch that makes clipping live (Actions runs
   `ingest.yml` from the default branch).

4. **First clip end-to-end.** Clip an article → it should appear as
   `pkm-vault/notes/<slug>.md` within a couple minutes (watch the `ingest` workflow run
   in the pkm-engine Actions tab). Open the vault in Obsidian.

## Open offers Claude can do next session

- Add the empty-body guard to `run_note_ingest` (+ a unit test) and push to PR #2.
- Stage the `git rm` of the 4 stub captures in `pkm-vault`.
- Refresh anything else; `README.md` / `CLAUDE.md` / `.env.example` are already updated.
- Optionally rebuild a markdown-native `lint`/`dashboard` over `notes/` (the old
  DB-backed ones were retired).

## Key files (new engine)

`pkm/pipeline/synthesize.py` · `pkm/pipeline/ingest_note.py` · `pkm/store/notes.py` ·
`pkm/prompts/synthesis.v3.md` (the whole "engine") · `pkm/cli.py` · `pkm/llm/pricing.py`.
Comparison harness: `scripts/compare_models.py`. Smoke runbook:
`docs/SMOKE_TEST_SYNTHESIZE.md`. Retirement record: `docs/LEGACY_RETIREMENT_PLAN.md`.
Decisions: `DECISIONS.md` (2026-06-23 entry). Prototype + samples: separate
`pkm-prototype` repo (`STATE.md`, `notes/`, `SYNTHESIS_PROMPT.md`).
