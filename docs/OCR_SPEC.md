# SPEC — `--ocr` for source-notes ingest (v1)

**Status:** Implemented locally (2026-07-20); awaiting live Gemini smoke test and visual review
**Classification:** Type-1 (new capability + new vendor: Google Gemini)
**Date:** 2026-07-20
**Touches:** source-notes path only (`pkm ingest-notes`). The article/clip path is out of scope for v1.

---

## 1. Goal

Transcribe Obsidian image embeds (`![[image N.jpg]]`) in source-note captures into
text **before** the note goes to GLM-5.2 synthesis, so image-only sections (e.g. the
"Liking" chapter of `Influence.md`, which exists only as 7 photos) produce real
content instead of a "captured but not readable" gap.

One vision call per image, via Google Gemini through its OpenAI-compatible endpoint,
reusing the existing `LLMClient`. Free-tier, $0.

## 2. Why Gemini / this shape

- GLM-5.2 is text-only; synthesis stays on it. OCR is a **separate pre-pass**.
- Gemini `gemini-2.5-flash` is vision-capable, free-tier eligible (10K RPD), and
  speaks the OpenAI Chat Completions shape via
  `https://generativelanguage.googleapis.com/v1beta/openai/` — so `pkm/llm/client.py`
  works unchanged (base_url + key + model swap).
- Verified against docs 2026-07-20: base64 data-URI images in `image_url` content
  parts; JPEG/PNG/WEBP/HEIC supported; 258 tokens per 768×768 tile; 20 MB inline
  request cap; File API only needed >~5 MB (our images are ~3 MB → inline is fine
  **per image**).

## 3. Constraints discovered from the live data

| Fact | Consequence for design |
|---|---|
| Images ~3 MB each, 7 per note | 21 MB > 20 MB inline cap → **one image per call**, never batched into one request |
| Images are flat siblings in `Sources/` | Resolution = `capture.path.parent / "<embed target>"`; no attachment-folder config to parse |
| Filenames contain spaces (`image 9.jpg`) | Embed target maps verbatim to filename; preserve spaces, no slugify |
| Folder holds more images than any note references (image 6–8 unreferenced) | OCR **only** embeds parsed from *this note's body*, never `glob` the folder |
| `compute_cost` KeyErrors on unknown model | Add Gemini pricing entry OR bypass cost tracking on OCR path (see §6) |
| iCloud mid-sync half-writes (existing MIN_AGE_SECONDS guard is on the `.md` only) | Extend freshness/read-error handling to referenced **images** |
| Delta SHA is over the `.md` body text only | If a user swaps an image file but keeps the embed name, body SHA is unchanged → OCR won't refresh. Fold image content hashes into the OCR cache key (see §7) |

## 4. Design

### 4.1 Config (`pkm/config.py`)
```
gemini_api_key: str = ""                     # env GEMINI_API_KEY
gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
ocr_model: str = "gemini-2.5-flash"          # env OCR_MODEL
ocr_enabled: bool = False                    # master switch; --ocr flag overrides per-run
```

### 4.2 OCR client builder (`pkm/cli.py`)
`_build_ocr_client(settings)` → second `LLMClient(None, settings.gemini_api_key,
settings.gemini_base_url)`. Distinct from the synthesis client. If `--ocr` set but
`gemini_api_key` empty → hard error (don't silently skip and mislead).

### 4.3 New module `pkm/ingest/ocr.py`
- `IMAGE_EMBED_RE` — match `![[<target>]]` where target ends in a supported image
  ext (`.png/.jpg/.jpeg/.webp/.heic/.heif`), case-insensitive. Also match Markdown
  `![](path)` for completeness.
- `resolve_embed(capture_path, target) -> Path | None` — sibling-file resolution;
  `None` if missing (logged, left as-is in body).
- `transcribe_image(ocr_client, model, image_path, cache) -> str` — read bytes,
  guard size (skip + warn if >18 MB after headroom), base64 data-URI, one
  `ocr_client.call(...)` with the OCR prompt; return transcript text. Uses/updates
  the OCR cache (§7).
- `enrich_body(body, capture_path, ocr_client, model, cache) -> (new_body, stats)` —
  replace each resolved embed with a fenced transcription block **keeping the
  original embed line** so Obsidian still renders the image:

  ```
  ![[image 9.jpg]]
  <!-- ocr:image 9.jpg -->
  > (transcribed) …text…
  <!-- /ocr -->
  ```

  Unresolved/failed embeds are left untouched. Returns per-image stats for the summary.

### 4.4 Integration point (`pkm/pipeline/ingest_source_notes.py`)
- New params: `ocr_client=None`, `ocr_model=None`, `ocr_enabled=False`.
- After `parse_capture`, **before** `run_note_ingest`: if OCR on and the body has
  embeds, call `enrich_body` and feed the enriched text to
  `capture.raw_for_synthesis()`'s body. Cheapest correct wiring: add an optional
  `body_override` to `raw_for_synthesis()` (front matter unchanged; only body swapped).
- Delta/skip logic **unchanged** — still keyed on the raw `.md` body SHA, plus the
  image-hash extension in §7. OCR never runs for `unchanged` notes.

### 4.5 CLI (`pkm ingest-notes --ocr`)
Flag flips `ocr_enabled` for the run regardless of the config default; builds the OCR
client and threads it through. Summary gains `ocr: {images_transcribed, cached,
failed, skipped_too_large, tokens_in, tokens_out}`.

## 5. OCR prompt (new file `pkm/prompts/ocr.v1.md`)
System prompt, roughly:
> You transcribe photographed pages of books/articles. Output ONLY the text visible
> in the image, verbatim, preserving paragraph breaks and lists. Do not summarize,
> interpret, translate, or add commentary. If the image has no legible text, output
> exactly `[no legible text]`. Ignore page furniture (page numbers, headers) unless
> part of a sentence.

Versioned like the others (`ocr-v1`) for cache-key identity.

## 6. Cost / $0 analysis
- Volume: a handful of books × ~7 images, re-OCR'd only when an image changes.
  `Influence` = 7 images × ~1–2K tokens ≈ ~10K input tokens, once. Trivial.
- Free tier (10K RPD `gemini-2.5-flash`) covers this with vast headroom → **$0**.
- **`compute_cost` handling:** add a `"gemini-2.5-flash"` PRICING entry at the
  *published paid rate* (so cost math is honest if the free tier is ever exceeded),
  but the OCR path runs `conn=None` and we surface tokens, not dollars, in the
  summary. Decision: **add the pricing entry** — never let the path KeyError, never
  log a false $0. (Paid rate to confirm at build time; free-tier reality is $0.)
- No batch API for OCR in v1 (per-image sync calls; volume doesn't justify it, and
  the OpenAI-compat layer can't do Gemini batch anyway).

## 7. OCR cache (idempotence — the important bit)
Re-synthesis is full on any body change, so without a cache we'd re-OCR every image
every time the user edits one line of text. Cache OCR output in the **vault** state
sidecar (`notes/.notes-state.json`), NOT iCloud:
```
"<slug>": {
  ...existing fields...,
  "ocr": { "<image filename>": { "img_sha": "<sha256 of image bytes>", "text_sha": "<sha of transcript>", "chars": N } }
}
```
- Transcript **text** is cached in a sibling file per note to keep the JSON small:
  `notes/.ocr-cache/<slug>.json` (committed; deterministic; small).
- Key on `img_sha`: if the image bytes are unchanged, reuse the cached transcript —
  **no call**. If bytes changed (even with the same filename), re-OCR. This also
  fixes the §3 "swapped image, same name" gap for the OCR layer.
- **Note:** synthesis still won't re-run if only an image changed and the `.md` text
  didn't — closed by decision 3 (fold image digest into `classify()`).

## 8. Failure modes
| Case | Handling |
|---|---|
| Missing image file | Leave embed as-is; log; continue |
| Image mid-sync / unreadable | Treat as failure: leave embed, count `failed`, do NOT cache; retried next run |
| Image > ~18 MB | Skip with `skipped_too_large`; leave embed (File-API path is a v2 option) |
| Gemini 429 / 5xx | Reuse client's existing 3× backoff; on exhaustion → per-image failure, note still synthesizes with remaining transcripts |
| `--ocr` set, no key | Hard error before any work |
| OCR returns `[no legible text]` | Cache it (avoid re-calling); don't splice a block |

## 9. Tests (`tests/test_ocr.py`, extend `test_ingest_notes.py`)
- Embed regex: matches `![[a.jpg]]`, spaces, mixed case, `![](x.png)`; ignores `[[a.md]]`, non-image.
- `resolve_embed`: sibling hit; missing → None; path-traversal target (`![[../secret]]`) rejected.
- `enrich_body`: keeps embed line, inserts block, leaves unresolved embeds, is idempotent (re-run over already-enriched body doesn't double-insert).
- Cache: unchanged `img_sha` → 0 calls (fake client asserts call count); changed bytes → 1 call.
- End-to-end via a **fake OCR client** (no network), mirroring the existing fake-client test style.
- `--ocr` off → byte-identical behaviour to today (regression guard).

## 10. Decisions (RESOLVED 2026-07-20)
1. **OCR cache location** → **sibling `notes/.ocr-cache/<slug>.json`, committed.** Re-runs cost 0 calls; survives CI checkouts; keeps `.notes-state.json` small.
2. **Splice format** → **keep embed + add transcription block.** Obsidian still renders the photo; non-destructive to the capture.
3. **Change detection** → **fold image hashes into `classify()` NOW.** A changed image (even same filename) re-triggers synthesis. Closes the §3/§7 gap in v1 rather than deferring.
4. **Scope** → **source-notes path only.** Article/clip path stays text-only.
5. **Model** → **`gemini-2.5-flash`.** Reliability sweet spot for photographed pages; 10K RPD free.

### Impact of decision 3 on `classify()`
`classify()` currently compares `content_sha` (body text). Extend the comparison to a
combined digest = `sha256(content_sha + sorted(img_sha for each referenced image))`.
Stored per-slug in state. Prefer lazy hashing: only hash images when text SHA matches
but we must decide changed-vs-unchanged. This is the one place decision 3 adds real
code beyond the OCR module.

## 10b. Fable adversarial findings — resolutions (2026-07-20)

**B1 (BLOCKER) — `max_tokens` vs `max_completion_tokens`.** `_uses_legacy_max_tokens`
returns True only for `glm-`/`z.ai`, so a Gemini base_url would send
`max_completion_tokens`, which Gemini's OpenAI-compat layer *silently ignores* → no
output ceiling, truncation-retry becomes dead code.
**Resolution:** extend `_uses_legacy_max_tokens` to also return True for the Gemini
compat host (`generativelanguage.googleapis.com`), so OCR calls send `max_tokens`.
Verify with one live call at build time before trusting the ceiling. Set an explicit,
low `max_tokens` for OCR (transcripts are short).

**B2 (BLOCKER) — OCR spend not folded into the cost cap.** OCR runs before
`run_note_ingest`; its `cost_usd` was never added to `spent` or checked against
`cost_cap_usd` — the one guardrail the whole codebase relies on (CLAUDE.md Mode-C #2).
**Resolution:** `transcribe_image` returns `cost_usd`; the loop adds it to `spent` and
checks the cap **before each image call**, aborting identically to the synthesis path.
Summary reports both tokens and `ocr_cost_usd`.

**B3 (BLOCKER) — `classify()` change breaks migration + runs when OCR is off.**
A new combined digest won't match any stored `content_sha` → first run reclassifies
ALL existing sources as "changed" and re-synthesizes the whole corpus; and if
`classify()` itself changes shape, plain `ingest-notes` (no `--ocr`) starts hashing
every image on every run, violating the cheap-skip promise.
**Resolution:** (a) `classify()` keeps the exact `content_sha`-only comparison when OCR
is off — unchanged default behaviour, byte-for-byte. (b) When OCR is on, comparison is
`content_sha AND img_digest`, but a stored entry **missing** `img_shas` is treated as a
match on the image dimension (migration-safe: never "changed" solely because the old
state predates the field). (c) Image hashing is lazy: only when `content_sha` already
matches (text unchanged) do we hash images to decide changed-vs-unchanged.

**M1 — `record()` must always persist `img_shas`.** Even when the verdict came from a
text-SHA difference (images not hashed for the verdict), `record()` computes and stores
current `img_shas` so the *next* run has a baseline. Separate "hash for verdict" from
"hash for persistence"; the latter always runs on a successful synthesis.

**M2 — image integrity before OCR + before caching.** A readable-but-truncated JPEG
(stalled iCloud placeholder) could be OCR'd to plausible garbage and cached as valid.
**Resolution:** before sending, validate with `PIL.Image.open(p).verify()` (or SOI/EOI
marker check if we avoid a Pillow dep). Fail → count `failed`, leave embed, **do not
cache**. Retried next run.

**M3 — path traversal in `resolve_embed`.** `parent / target` does not sanitize `..`;
`![[../../Desktop/x.jpg]]` would resolve outside `Sources/` and get sent to Google.
**Resolution:** `resolved = (capture.path.parent / target).resolve()`; reject unless
`resolved.is_relative_to(capture.path.parent.resolve())`. Test must place a real file
outside the sandbox and assert rejection (not merely absence).

**M4 — autosync (every 300s) races a long `--ocr` run.** Two-way autosync commits +
rebases + pushes `pkm-vault` every 5 min; a multi-image OCR run exceeds that.
**Resolution:** (a) write order is **cache file first, then state file**, each written
atomically (temp + `os.replace`); partial state on reload must be tolerable (a slug with
a cached transcript but no state entry just re-verifies). (b) Rollout: pause the
`com.rohit.pkm-autosync` LaunchAgent for the duration of the first manual `--ocr` run
(`launchctl unload` → run → `launchctl load`).

**M5 — token estimate ~4× low; free-tier limits unverified.** Real images are
4032×3024 → 6×4 = 24 tiles × 258 ≈ **~6,200 tokens/image** (verified via `sips`); 7
images ≈ ~43K input tokens, not ~10K. Published free-tier RPD is no longer a fixed
table (AI Studio per-project quota).
**Resolution:** (a) **downscale to ~1536px long edge before base64** (Pillow) — cuts to
~4 tiles/image (~1K tokens) with no legibility loss on book text, slashing tokens +
latency. (b) Check this account's live quota in AI Studio before treating $0/headroom as
fact; §6 headroom claims are provisional until then.

**Mnr1 — disable thinking.** `gemini-2.5-flash` may run an internal reasoning pass;
verbatim transcription doesn't need it. Set `reasoning_effort`/`extra_body.thinking_config`
to minimal to avoid wasted tokens.

**Mnr2 — prove the source file is never mutated.** Add a test asserting the source
`.md` bytes + mtime are unchanged after an `--ocr` run (enriched body is in-memory only).

**Mnr3 — `.env.example` + secret scope.** Add `GEMINI_API_KEY` to `.env.example`.
Confirmed: no `GEMINI` reference in repo today, and `.github/workflows/*` never call
`ingest-notes` → Actions never needs the key. §11 must pin this invariant: `--ocr`
stays local-only, never migrates into a workflow trigger.

## 11. Rollout
1. ✅ Spec written, §10 decisions resolved, Fable adversarial pass done (§10b).
2. **Pre-build check (needs operator):** confirm this account's live Gemini quota in AI
   Studio (M5); one live `gemini-2.5-flash` call to confirm `max_tokens` is honored via
   the compat layer (B1). Confirm Pillow dependency acceptable ($0, pure-Python wheel).
3. Implement on a branch; tests green; `--ocr` defaults **off** (opt-in).
4. **Pause autosync** (`launchctl unload com.rohit.pkm-autosync`), manual run on
   `Influence.md`, eyeball the "Liking" section has real content, then reload the agent (M4).
5. `DECISIONS.md` entry; update `CLAUDE.md` (drop `--ocr` from "deferred"); update memory note.
6. Wire `--ocr` into the local autosync/Makefile only after a clean manual run —
   **local-only, never into a GitHub Actions workflow** (Mnr3).

## 12. Golden acceptance rules (before any rollout commit)

1. The source-note file is byte- and mtime-identical after OCR; enrichment is
   in memory only.
2. Every original image embed remains in the synthesized input; OCR appends a
   marked transcription block and never replaces the image.
3. Re-running unchanged images produces no Gemini calls and identical enriched
   Markdown. A changed referenced image reprocesses its source; an unrelated
   image does not.
4. Missing, fresh, corrupt, oversized, and traversal-path images fail closed:
   no upload or cache entry, and synthesis remains usable.
5. Running without `--ocr` preserves the former source-notes behavior exactly.
6. OCR is local-only, honors the shared cost cap, and the Gemini key never enters
   a workflow, repository, or command output.
7. Manually compare a photographed-page transcript against its source image
   before enabling OCR in autosync; it must be transcription, not interpretation.
