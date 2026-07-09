# pkm-engine — AI-assisted Personal Knowledge Management

Clip an article → one readable Markdown note. **One OpenAI GPT-5.4 call per source**,
**$0 infrastructure, no database, no local daemon.** Ingestion runs in GitHub
Actions over a git checkout of the vault; the vault is plain Markdown you read in
Obsidian. Your Mac is never in the path.

## How it works

```
browser bookmarklet ──POST──▶ Cloudflare Worker (worker-clip.js)
                                  │  commits raw/<hash>.md to pkm-vault
                                  │  fires repository_dispatch(ingest)
                                  ▼
                       GitHub Actions (ingest.yml)
                                  │  pkm batch-ingest --new-only
                                  │  one GPT-5.4 call per new raw capture
                                  ▼
                       commits notes/<slug>.md back to pkm-vault
                                  ▼
                       you read/edit the vault in Obsidian
```

The whole "engine" is the system prompt in `pkm/prompts/synthesis.v3.md`. No claim
atomization, no concepts, no embeddings, no graph — the note Markdown is the artifact.

## Setup

Requires **Python 3.12** (3.14 lacks wheels for some deps).

```bash
pip install -e .
cp .env.example .env
# Edit .env: OPENAI_API_KEY and VAULT_PATH (path to your pkm-vault checkout)
```

## Usage

```bash
pkm ingest --raw path/to/raw/capture.md     # one capture → one note
pkm batch-ingest --new-only                  # all raw/*.md → notes/ (skips existing)
# `synthesize` / `batch-synthesize` are aliases.
```

`PKM_SYNTHESIS_MODEL` defaults to `gpt-5.4`. `--new-only` skips captures whose note
already exists (idempotency = the note file). `batch-ingest` aborts before exceeding
`PKM_RUN_COST_CAP_USD` (~$0.03/note, so the default $0.50 covers a sizable batch).

## Running tests

```bash
pytest          # on a Python 3.12 venv
```

## Book/podcast source-notes (Mac-run)

Everything else in this repo runs in GitHub Actions; `pkm ingest-notes` is the one
deliberately-manual, Mac-run exception. Why: its source folder is an Obsidian
vault synced via **iCloud**, which is not reachable from a GitHub Actions runner,
and the mid-sync safety guard (skip files modified within the last 60s) only
works when reading iCloud directly on the machine that's syncing it. Low
frequency (books/podcasts, not daily clips) makes a manual command fine.

1. `pip install -e .` the `pkm-engine` package on the Mac (once).
2. Set a Mac-local `.env` (gitignored — never committed):
   ```
   OPENAI_API_KEY=...
   PKM_SOURCES_DIR=~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Sources
   VAULT_PATH=/path/to/your/local/pkm-vault/checkout
   ```
3. `git pull` the vault checkout, then:
   ```bash
   pkm ingest-notes
   ```
4. Commit + push `notes/` **and** the updated `notes/.notes-state.json` (the
   delta-state sidecar — without it every source re-synthesizes next run).

See `DECISIONS.md` for the "Switching provider to GLM-5.2" runbook (the future
swap once the current OpenAI credit runs out).

## Capture / Clipper Setup

Clipping is one click from any browser page. The browser bookmarklet POSTs to a
Cloudflare Worker (`worker-clip.js`), which commits an immutable `raw/*.md` file to
`pkm-vault` and fires a `repository_dispatch(event_type:"ingest")` to `pkm-engine` so
the ingest workflow picks it up. Everything runs at the Cloudflare + GitHub edge —
the Mac is never in the path (clipping works while it is asleep or offline).

### Worker deploy (operator steps)

1. Create a Cloudflare account and note your `CF_ACCOUNT_ID`.
2. Create the R2 bucket that mirrors large clips:
   ```bash
   wrangler r2 bucket create pkm-raw-blobs
   ```
3. Create a **fine-grained GitHub PAT** scoped to `contents: read & write` on **BOTH**
   repositories:
   - `rohitgupta1686/pkm-vault` (the Worker commits `raw/*.md` here via the Contents API)
   - `rohitgupta1686/pkm-engine` (the Worker fires `repository_dispatch` here)

   GitHub → Settings → Developer settings → Fine-grained personal access tokens →
   "Only select repositories" → pick **both** `pkm-vault` and `pkm-engine` →
   Permissions → Repository permissions → Contents: **Read and write**.

   Firing `repository_dispatch` against `pkm-engine` requires `contents:write` on
   `pkm-engine`, so a vault-only PAT would **403 the dispatch** silently. Scope the
   PAT to **both** repos. See `DECISIONS.md` [T2-05-02].
4. Set the two Worker secrets (secrets are NEVER in `wrangler.toml` or committed —
   only placeholders live there):
   ```bash
   # PKM_KEY = the X-PKM-Key shared secret the bookmarklet sends. Generate a strong one:
   openssl rand -hex 32        # paste the output as the value when prompted
   wrangler secret put PKM_KEY

   # GH_PAT = the fine-grained PAT from step 3 (contents:write on both repos)
   wrangler secret put GH_PAT
   ```
5. Deploy:
   ```bash
   wrangler deploy
   ```
   Note the deployed Worker URL (e.g. `https://pkm-clip.<your-subdomain>.workers.dev`).

### Bookmarklet

Drag this to your bookmarks bar, then edit it and replace `WORKER_URL` and
`SHARED_KEY` with your deployed values. The bookmarklet runs in the page origin; the
Worker uses CORS `Access-Control-Allow-Origin: *` plus the `X-PKM-Key` shared secret
(no credentials/cookies), so the shared secret is the **only** gate — keep it private.

```javascript
javascript:(function(){
  var WORKER_URL = "https://pkm-clip.YOUR-SUBDOMAIN.workers.dev";
  var SHARED_KEY = "REPLACE_WITH_YOUR_PKM_KEY";
  var selection = window.getSelection().toString();
  var text = selection || document.body.innerText;
  var payload = {
    url: window.location.href,
    type: "Article",
    text: text,
    title: document.title
  };
  fetch(WORKER_URL + "/clip", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-PKM-Key": SHARED_KEY
    },
    body: JSON.stringify(payload)
  }).then(function(r){return r.json();})
    .then(function(j){alert("clip: " + (j.ok ? ("ok -> " + j.path) : "failed"));})
    .catch(function(e){alert("clip failed: " + e);});
})();
```

### Response and idempotency

The Worker returns `{ ok: true, path, deduped }`. Re-clipping the same source is a
no-op for the commit step (`deduped: true`, `raw/` is immutable — the Worker does a
GET-then-PUT and skips the PUT when the path already exists), but the Worker **still
fires `repository_dispatch(event_type:"ingest")`** so you have a manual re-trigger
path. Downstream, `batch-ingest --new-only` skips any capture whose `notes/<slug>.md`
already exists, so a re-trigger costs 0 LLM calls.

### Mac-independent

Clipping and ingestion both run off-machine: the Worker at the Cloudflare edge, the
ingest as a GitHub Action — no local daemon, no menu-bar agent, no cron on the Mac
(project hard constraints).
