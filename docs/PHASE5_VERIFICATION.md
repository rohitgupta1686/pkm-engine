# Phase 5 — Live Capture-Worker Verification (Plan 05-03)

**Date:** 2026-06-20
**Operator:** rohitgupta1686
**Worker:** `pkm-clip` → `https://pkm-clip.rohitgupta-iitr.workers.dev`
**Result:** ✅ All five Phase-5 success criteria + MVP-01 + MVP-02 PASS.
**Pre-fix blocker found & fixed:** the first live ingest run failed on a
claim→chunk FK constraint; root-caused, fixed, and re-verified live (see
"Bugs found and fixed during live verification" below).

This document records evidence captured from the deployed Cloudflare Worker,
GitHub Contents API, R2, real GitHub Actions runs, and the private
`pkm-vault` repo. **No secret values appear below** — `PKM_KEY`/`GH_PAT` are
referenced as env vars only; the evidence records URLs, SHAs, status codes,
byte counts, and run IDs.

---

## Precondition gate

`cd pkm-engine && npx wrangler whoami` + `npx wrangler secret list`:

| Binding | Status |
|---|---|
| Cloudflare auth (whoami) | ✅ logged in (account scopes present) |
| `PKM_KEY` secret | ✅ set (rotated immediately before this verification — see Security) |
| `GH_PAT` secret | ✅ set |
| R2 bucket `pkm-raw-blobs` | ✅ bound (`env.RAW_BUCKET`) |
| Worker deploy | ✅ `npx wrangler deploy` → Version `fb180c2a-529b-425d-b5a1-8fe24fe1d24f` |

Vault access confirmed: `rohitgupta1686/pkm-vault` (private) reachable via
`gh api`. Baseline vault HEAD before verification: `ff2a3fde9e6b`.

---

## Criterion 1 — raw/ appears within ~5s ✅

Command (authenticated; `PKM_KEY` read from env, never inlined):

```bash
WORKER_URL="https://pkm-clip.rohitgupta-iitr.workers.dev"
curl -sS -X POST "$WORKER_URL/clip" -H "Content-Type: application/json" \
  -H "X-PKM-Key: $(cat ~/.pkm_key)" -d @/tmp/phase5_clip_payload.json
```

Payload: `{"url":"https://example.com/phase5-live-test-2026","type":"Article",`
`"title":"Phase 5 Live Test - Operating Leverage","text":"<~2.6KB article body>"}`.

Response (POST→response wall time: **2s**):

```json
{"ok":true,"path":"raw/example-com__phase-5-live-test-operating-leverage__c5214231715722136899dcaa40942f4a.md","deduped":false}
```

raw/ file confirmed present in `pkm-vault` via Contents API:

```json
{"path":"raw/example-com__phase-5-live-test-operating-leverage__c5214231715722136899dcaa40942f4a.md","size":3340,"sha":"c481ec7b8dad"}
```

Vault HEAD advanced `ff2a3fd` → `e8e225c` (new `clip:` commit for this path).

**PASS** — Worker wrote raw/ and the file was confirmed in the vault within 2s
of the POST. (The chained ingest run for this clip failed pre-fix — see the
bugs section; Criterion-4 is re-verified with a fresh clip after the fix.)

---

## Criterion 2 — >200K offloads to R2, full text preserved in raw/ ✅

Payload: 200,001 chars of repeated filler (`type:"Article"`,
`url:"https://example.com/phase5-r2-offload-test"`). POST response:

```json
{"ok":true,"path":"raw/example-com__phase-5-r2-offload-test__b5089b41881d370d6e130d42c699567.md","deduped":false}
```

**raw/ file present + front matter carries `r2key`** (decoded from the vault
Contents API base64):

```
---
title: Phase 5 R2 Offload Test
type: Article
url: "https://example.com/phase5-r2-offload-test"
date_saved: 2026-06-20T15:59:57.188Z
r2key: blobs/83015a4a-4359-4e95-b810-42461c436a98.txt
---
This is filler content for the Phase 5 R2 offload verification. ...
```

raw/ file size: 200,206 bytes (front matter + 200,001-char body).

**R2 blob exists and is the right size** (`wrangler r2 object get … --remote`):

```text
Downloading "blobs/83015a4a-4359-4e95-b810-42461c436a98.txt" from "pkm-raw-blobs".
Download complete.
200001 /tmp/r2_blob.txt      # wc -c
```

**Q1 invariant — raw/ body holds the FULL text, not a pointer** (T2-05-01):
decoded the vault file, stripped front matter, measured body:

```text
raw/ body char length: 200001
Q1 full-text-present: PASS
first 40 chars: 'This is filler content for the Phase 5 R'
```

**PASS** — >200K text was mirrored to R2 (`r2key` recorded in front matter),
the R2 object is exactly 200,001 bytes, and the raw/ body still contains the
full 200,001-char text (not a pointer/replacement string).

---

## Criterion 3 — 401 on missing AND wrong key ✅

```bash
# missing key
curl -sS -o /dev/null -w "%{http_code}" -X POST "$WORKER_URL/clip" \
  -H "Content-Type: application/json" -d '{}'
# -> 401

# wrong key
curl -sS -o /dev/null -w "%{http_code}" -X POST "$WORKER_URL/clip" \
  -H "Content-Type: application/json" -H "X-PKM-Key: deadbeef" -d '{}'
# -> 401

# OPTIONS preflight (CORS)
curl -sS -o /dev/null -w "%{http_code}" -X OPTIONS "$WORKER_URL/clip" \
  -H "Origin: https://example.com" -H "Access-Control-Request-Method: POST"
# -> 204
```

| Case | Status |
|---|---|
| No `X-PKM-Key` header | **401** |
| Wrong key (`deadbeef`) | **401** |
| OPTIONS preflight (CORS) | **204** |

**PASS** — the shared-secret gate is enforced at the edge; unauthenticated and
wrong-key POSTs are rejected with 401.

---

## Criterion 4 — chained Actions run completes with wiki pages ✅

*(Re-verified with a fresh source after the FK fix — see the bugs section for
why the first clip's ingest failed pre-fix.)*

Fresh clip (`url":"https://example.com/phase5-live-test-2026-clip2"`, topic:
Network Effects, ~2.6KB body). POST response:

```json
{"ok":true,"path":"raw/example-com__phase-5-live-test-network-effects__1808829812326caad189f53a894e0033.md","deduped":false}
```

raw/ commit landed in `pkm-vault`: `280c00015bf3` (rohitgupta1686,
`clip: 1808829812326caad189f53a894e0033.md`).

The Worker fired `repository_dispatch(event_type:"ingest")`; the chained
`ingest.yml` run completed:

| Field | Value |
|---|---|
| Run ID | 27876239381 |
| URL | https://github.com/rohitgupta1686/pkm-engine/actions/runs/27876239381 |
| Trigger | repository_dispatch (event_type=ingest) |
| Conclusion | **success** |
| Elapsed | ~165s (started 15:55:04Z, updated 15:57:49Z) |
| Budget (criterion 5 / 10m cap) | 165s ≪ 10:00 ✓ |

`batch_ingest` result for the run:

```json
{"processed": 6, "wrote": 1, "deduped": 5, "failed": 0, "aborted": false,
 "cost_usd_total": 0.05124375, "tokens_total": 18225}
```

`pkm-bot` wiki synthesis commit landed in `pkm-vault`:

| Field | Value |
|---|---|
| Vault commit | `b62a82e7874587fbd8ce976e8fdaa6e7950ff0b9` |
| Author | pkm-bot |
| Message | `synthesize: 2026-06-20T15:57:46Z` |
| Files added | `log.md`; `wiki/sources/phase-5-live-test-network-effects.md`; `wiki/concepts/network-effects.md`, `direct-network-effects.md`, `indirect-network-effects.md`, `metcalfe-s-law.md`, `winner-take-most-outcomes.md`, `cold-start-problem.md`, `critical-mass.md`, `disintermediation.md`, `network-collapse-risk.md`, `network-effect-coefficient.md` |

Source page confirmed in vault: `wiki/sources/phase-5-live-test-network-effects.md`
(7,807 bytes).

**PASS** — clip → raw/ commit → `repository_dispatch` → `ingest.yml` run
`conclusion=success` → `pkm-bot` synthesized wiki pages committed to `pkm-vault`,
with `failed:0` (FK fix holding). MVP-01 (clip → synthesized wiki page,
Mac not in runtime path) is demonstrated end-to-end.

---

## Criterion 5 — Mac-independent ✅

No step in the runtime path depended on the Mac as a runtime dependency:

- **Clip intake** — Cloudflare Worker (`pkm-clip`) at the edge accepts the POST,
  writes raw/ via the GitHub Contents API, mirrors to R2, and fires
  `repository_dispatch`. All edge/cloud.
- **Dispatch** — GitHub `repository_dispatch` API; no local process.
- **Ingest pipeline** — `ingest.yml` runs on `ubuntu-latest` GitHub-hosted
  runners (Reader → Summarizer → ConceptExtractor → KGAgent, OpenAI backend,
  Turso metadata, vault commit).
- **Storage** — `pkm-vault` (GitHub) + `pkm-raw-blobs` (R2) + Turso.

The Mac was used only as the **test initiator** (the `curl` that drove
verification), which is explicitly out of scope of the runtime-path constraint
(the constraint is about the runtime, not the test initiator). The deployed
system runs with the Mac absent.

**PASS.**

---

## MVP-02 — re-clip is a no-op ✅

Re-POSTed the **same** clip-2 payload (`{url,title,text}` identical to Criterion
4's clip). Response:

```json
{"ok":true,"path":"raw/example-com__phase-5-live-test-network-effects__1808829812326caad189f53a894e0033.md","deduped":true}
```

| Check | Result |
|---|---|
| Response `deduped` | **true** |
| New raw/ commit for this path? | **No** — vault HEAD shows no new `clip: 18088298…` commit; the GET-then-PUT path skipped the PUT (Q3: still dispatched) |
| Re-clip's chained ingest run | run `27876585247`, conclusion **success**, ~28s |

`batch_ingest` result for the re-clip run:

```json
{"processed": 7, "wrote": 0, "deduped": 7, "failed": 0, "aborted": false,
 "cost_usd_total": 0.0, "tokens_total": 0}
```

**PASS** — `deduped:true`, no second raw/ commit, and the second ingest run made
**0 LLM calls / 0 new rows / 0 new wiki** (`wrote:0`, `cost_usd_total:0.0`,
`tokens_total:0`). Re-clip is a true no-op (content-addressed path + GET-first
idempotency + agent-run cache).

---

## Bugs found and fixed during live verification

### B-05-01 — `claims.chunk_id` FK crash on LLM positional labels (FIXED + re-verified)

**Symptom:** the first clip's chained ingest run (`27875614840`) failed with
`FOREIGN KEY constraint failed` in Turso (`failed:1`, `wrote:0`); the wiki page
was never written.

**Root cause (empirically confirmed):** the summarizer/extractor prompts
instruct the LLM to emit positional `chunk_id` labels (`"para_1"`,
`"section_body"`) or the `"null"` sentinel, because the model cannot see the
deterministic `chk_<hash>_NNN` chunk ids. `pkm/pipeline/ingest.py` passed that
raw string straight into `claims.chunk_id`, which has a hard FK to `chunks(id)`
(schema `001_init.sql`, AD-6). Any non-null positional label is not a real
`chunks.id`, so the FK rejects it. Reproduced locally against the schema:

| `claims.chunk_id` value | FK result |
|---|---|
| `"para_1"` (positional — what the LLM emits) | ❌ `FOREIGN KEY constraint failed` |
| `"para_2"` | ❌ rejected |
| real `"chk_…_000"` | ✅ OK |
| `"null"` string | ❌ rejected (prior `80b195f` fix coerces this → `None`) |
| `None` | ✅ OK |

The failure is **nondeterministic** — it only triggers when the LLM emits a
positional label rather than `"null"`, which matches the intermittent
success/failure pattern in the run history. The prior `80b195f` fix only covered
the `"null"` sentinel; positional labels were unhandled, and the
`ordinal_to_chunk_id` map built in `ingest.py` was never applied to claims.

**Fix (commit `5f26b6c`, pkm-engine main):** `run_ingest` now resolves every
claim's `chunk_id` via `_resolve_claim_chunk_id` before insert — a real
`chunks.id` is kept; `para_N` maps to ordinal `N-1`'s chunk id when in range;
everything else (including `"null"`) becomes SQL NULL. Keeps the FK contract and
the existing `test_claim_null_chunk_id_sentinel_satisfies_fk` invariant intact;
no schema migration. Design choice logged as **DECISIONS T2-05-04** (the
alternative — drop the FK and store labels as free-text provenance — is deferred
to MVP review as a Type-1 contract change).

**Tests:** +1 e2e (`TestPositionalChunkIdFK`); full suite **90 passed**.

**Re-verified live:** the fresh clip-2 ingest run (`27876239381`) returned
`failed:0, wrote:1` and produced the wiki pages (see Criterion-4). The 200K R2
clip's ingest run (`27876365376`) also succeeded `failed:0`.

### B-05-02 (known issue, NOT a Phase-5 blocker) — stuck source after a failed ingest

The original clip-1 source (`operating-leverage`) has a raw/ file (3,340 bytes)
but **no wiki page** (404) and will not synthesize under `--new-only`: its first
ingest failed mid-transaction on B-05-01, but `upsert_source` had already
committed the `sources` row (independent `commit=True`) and all four agents had
committed `agent_runs` ("ok") before the claim-write rolled back. On every
subsequent `--new-only` run, `_has_prior_agent_runs` returns true → the source
short-circuits as "deduped" and the now-fixed claim write is never re-attempted
(visible in the re-clip run's `deduped:7`). This is a pipeline-robustness gap
(agents-ran-but-no-wiki sources are permanently stuck under `--new-only`),
**not** a capture-worker issue. Flagged as a follow-up: on a source that has
prior agent runs but no `wiki_path`, `--new-only` should re-attempt synthesis
rather than short-circuit. No action required for Phase 5 DoD.

---

## Security

- `PKM_KEY` was rotated immediately before this verification (a prior transcript
  had exposed the old value). The fresh value was generated with
  `openssl rand -hex 32`, stored only in the Cloudflare Worker secret and a
  chmod-600 file referenced as `$(cat ~/.pkm_key)`; it never appeared in any
  command, terminal output, or this document. The at-rest file is deleted after
  verification.
- `GH_PAT` remains a fine-grained PAT scoped to `contents:write` on exactly
  `pkm-vault` + `pkm-engine` (Q2, T2-05-02).
- No secret values appear in this document — only URLs, SHAs, status codes,
  byte counts, and run IDs (T-05-12 mitigation).

---

## Summary

| Criterion | Result |
|---|---|
| 1 — raw/ appears within ~5s | ✅ PASS (2s) |
| 2 — >200K offloads to R2 + full text in raw/ | ✅ PASS (R2 200,001 B; raw/ body 200,001 chars) |
| 3 — 401 on missing/wrong key | ✅ PASS (401 / 401 / 204) |
| 4 — chained Actions run → wiki pages | ✅ PASS (run 27876239381 success; pkm-bot commit `b62a82e`) |
| 5 — Mac-independent | ✅ PASS (runtime path all edge/cloud) |
| MVP-01 — clip → synthesized wiki, Mac out of path | ✅ PASS (demonstrated by Criterion-4) |
| MVP-02 — re-clip is a no-op | ✅ PASS (deduped:true, 0 LLM calls, 0 new wiki) |

One live bug found (B-05-01, claim→chunk FK), fixed in `5f26b6c`, and
re-verified live. One known issue logged for follow-up (B-05-02, stuck source).

**Task 2 of plan 05-03 is complete.** Awaiting the Task 3 human-verify
checkpoint (review this document; spot-check the 401; confirm raw/ + wiki/
commits in `pkm-vault`; confirm the chained run shows `conclusion=success`).
Per project `CLAUDE.md`, stop at the MVP gate after Phase 5 — do NOT start
Phase 6 / V1 autonomously.