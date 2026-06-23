# Live smoke test — single-call note synthesis

The single-call path (`pkm synthesize`) is fully wired and unit-tested with a fake
client, but the real OpenAI/GPT-5.4 call cannot run from the build environment
(no key, no `openai` SDK installed, no local proxy). Run this on a machine that
has the API access.

## Pre-flight (must do first)

1. **Confirm the model snapshot.** `PKM_SYNTHESIS_MODEL` defaults to `gpt-5.4`.
   Set it to the exact snapshot you intend to bill against.
2. **Add real pricing.** `pkm/llm/pricing.py` currently has a clearly-marked
   PLACEHOLDER `gpt-5.4` entry (deliberate overestimate). Replace it with ground
   truth, or the recorded `cost_usd` will be wrong (the run still succeeds — it
   only affects cost accounting and the batch cap).
3. **Install + configure.**
   ```bash
   cd pkm-engine
   pip install -e .            # pulls the openai SDK + pydantic
   cp .env.example .env        # then edit:
   #   OPENAI_API_KEY=sk-...
   #   PKM_SYNTHESIS_MODEL=<confirmed snapshot>
   #   VAULT_PATH=/absolute/path/to/pkm-vault
   ```
   (A local OpenAI-compatible proxy works too: set `OPENAI_BASE_URL` and point
   `PKM_SYNTHESIS_MODEL` at whatever model it serves — a $0 way to validate the
   wiring before spending on real GPT-5.4.)

## Run

Single capture:
```bash
pkm synthesize --raw "$VAULT_PATH/raw/economist-com__america-s-carmakers-cannot-escape-chines__9174f51fb090d0515c70ed0430ef388f.md"
```
Whole vault (idempotent; skips notes that already exist):
```bash
pkm batch-synthesize --new-only
```

## What to check

- **It wrote a note:** `<vault>/notes/<slug>.md` exists and the JSON result shows
  `"status": "ok"` with non-zero `tokens_in`/`tokens_out`.
- **Format parity with the prototype:** front matter, TL;DR, beats, one visual at
  most, same-unit-only bar chart, a wildcard only when earned (and not always
  "Zoom out" — the recent-frames feed should vary it once a few notes exist).
- **Mermaid renders in Obsidian** with no literal `\n` in node labels.
- **`Connects to`** links only to slugs that exist in `notes/`, never self-links.
- **Cost/cache:** re-running the same capture without `--new-only` should hit the
  `agent_runs` cache (no second API charge); `--new-only` skips before calling.

## If it fails

- `KeyError` in cost → pricing entry for the model is missing (see Pre-flight 2).
- Empty/short note → check the raw capture actually has a body (4 of the 11 vault
  captures are body-less paywall clips and should not be synthesized).
- Truncated output → `DEFAULT_MAX_COMPLETION_TOKENS` (16384) then a 32768 retry;
  a full note is ~2–3k tokens so this should never trigger.
