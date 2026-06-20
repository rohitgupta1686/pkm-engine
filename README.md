# pkm-engine — AI-assisted Personal Knowledge Management pipeline

Clip → synthesized wiki page, $0 infrastructure, zero local daemon.

## Setup

```bash
pip install -e .
cp .env.example .env
# Edit .env and fill in your API keys
```

## Local dev

Leave `TURSO_URL` blank in `.env` to use a local `pkm.db` SQLite file (offline development mode).

## Running tests

```bash
pytest tests/
```

## Capture / Clipper Setup

Clipping is one click from any browser page. The browser bookmarklet POSTs to a
Cloudflare Worker (`worker-clip.js`), which commits an immutable `raw/*.md` file to
`pkm-vault` and fires a `repository_dispatch(event_type:"ingest")` to `pkm-engine` so
the Phase-4 ingest pipeline picks it up. Everything runs at the Cloudflare + GitHub
edge — the Mac is never in the path (clipping works while it is asleep or offline).

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

   **The PKM Cloud Architecture doc §11 mentions only the `pkm-vault` scope.** That
   scope alone is insufficient: firing `repository_dispatch` against `pkm-engine`
   requires `contents:write` on `pkm-engine`, so a vault-only PAT would **403 the
   dispatch** silently. Scope the PAT to **both** repos. See `DECISIONS.md` [T2-05-02].
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
    .then(function(j){alert("clip: " + (j.ok ? ("ok -> " + j.path + (j.deduped ? " (deduped)") : "") ) : "failed");})
    .catch(function(e){alert("clip failed: " + e);});
})();
```

### Response and idempotency

The Worker returns `{ ok: true, path, deduped }`. Re-clipping the same source is a
no-op for the commit step (`deduped: true`, `raw/` is immutable — the Worker does a
GET-then-PUT and skips the PUT when the path already exists), but the Worker **still
fires `repository_dispatch(event_type:"ingest")`** so you have a manual re-trigger
path from the clipper. The downstream pipeline dedups via the `sha256(raw_text)`
cache (ORCH-07 → 0 LLM calls, 0 new rows). See `DECISIONS.md` [T2-05-03].

### Mac-independent

Clipping works while the Mac is asleep or offline: the Worker runs at the
Cloudflare edge and the ingest pipeline runs as a GitHub Action — no local daemon,
no menu-bar agent, no cron on the Mac (project hard constraints).
