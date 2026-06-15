# Build Brief for Claude Code — AI-Assisted PKM System
**Hand this file to Claude Code as the operating brief.** The two authoritative specs live alongside it:
- `PKM_Technical_Specification.md` — the system design (ontology, schema, agents, notes, naming, metadata, MVP plan).
- `PKM_Cloud_Architecture.md` — the cloud-native, near-zero-cost data/processing layer.

Where they conflict, the cloud doc wins for infrastructure; the technical spec wins for everything else. Both already encode the lead-architect decisions (AD-1…AD-8) — **honor them; do not re-litigate.**

---

## 1. Mission

Build the **cloud MVP**: clipping a source anywhere produces a synthesized, linked, provenance-cited Markdown wiki page, with **zero local daemon**, **$0 infrastructure**, and Claude tokens as the only (capped) cost. Vault stays a plain-Markdown Git repo that runs locally if every cloud service vanishes.

Build only the **MVP scope** (4 node types, 3 templates, no Neo4j, no Vectorize-required path beyond V1 stub). Stop at the MVP version gate and surface for review before V1.

---

## 2. How to work (operating principles)

1. **Phase by phase.** Complete a phase's Definition of Done before starting the next. Do not skip ahead.
2. **Idempotency is sacred.** The content-hash LLM cache (AD-3) and write-once `raw/` (AD-6) are gates, not nice-to-haves. The idempotency test must pass before the pipeline is considered working.
3. **Keep large text out of Turso** (row-read trap). Turso holds metadata + edges + cache only; full text lives in Git/R2.
4. **Never commit secrets.** Use `.env.example`, GitHub Actions Secrets, and Worker Secrets. Vault repo is private.
5. **Reuse, don't rewrite.** The Python pipeline is identical to the local spec; only the DB connection and the orchestration layer change.
6. **Log every reversible decision** in `DECISIONS.md` (one line + rationale). Do not surface these — they're for async review.
7. **Append a short note to `PROGRESS.md`** at each phase boundary (what shipped, acceptance status, cost actuals if known).
8. **Commit in logical units** with clear messages. Tests live with the code.
9. **Default to autonomy.** Surface to strategic review *only* per Section 5. When in doubt on a reversible matter, pick the spec-aligned default, log it, and continue.

---

## 3. Prerequisites the user provides ONCE, upfront (collect these before Phase 1)

List these back to the user as a single checklist so they're not interrupted mid-build:

- [ ] GitHub account; create **private** repo `pkm-vault` and **public** repo `pkm-engine` (engine is public → unlimited free Actions minutes; it holds no secrets — all secrets live in GitHub Actions Secrets / Worker Secrets). **User has ratified public engine; not an open question.**
- [ ] `ANTHROPIC_API_KEY` + a **monthly spend cap** set in the Anthropic console.
- [ ] Turso account; `turso db create pkm`; capture `TURSO_URL` + `TURSO_TOKEN`.
- [ ] Cloudflare account; `CF_ACCOUNT_ID` + an API token scoped to **Workers AI + Vectorize + Workers** only.
- [ ] GitHub Actions **spending limit set to $0** (fail-closed, no surprise bill).
- [ ] (Optional) second git remote for nightly vault backup.

If any are missing when needed, **block on that one item only** (a prerequisite handoff, not a strategic review).

### 3.1 Repo topology (settled — public engine + private vault)
Because `pkm-engine` is public (unlimited free Actions minutes) and `pkm-vault` is private, the ingest workflow lives in **`pkm-engine`** and operates on the vault remotely. Consequences Claude Code must implement:
- **Trigger:** `repository_dispatch` (fired by the capture Worker) is the primary trigger, **not** `push: paths: raw/**` — `raw/` lives in the *other* repo. Keep the nightly `schedule` cron as catch-up.
- **Checkout + commit-back:** the workflow checks out `pkm-vault` and commits `wiki/`+`log.md` back using a **fine-grained PAT scoped to `contents:write` on `pkm-vault` only**, stored as the `VAULT_PAT` secret in `pkm-engine` (the default `GITHUB_TOKEN` cannot write to a different repo). Add `VAULT_PAT` to the prerequisites checklist above. The capture Worker may reuse the same PAT.
- This supersedes the single-repo `ingest.yml` sketch in `PKM_Cloud_Architecture.md` §5 (which assumed the workflow lived in the vault repo). Same pipeline; only checkout/auth changes.

---

## 4. Phased plan with Definitions of Done

> Each phase ends with: run the acceptance checks → update `PROGRESS.md` → continue automatically unless a Section-5 trigger fired.

**Phase 1 — Data layer + idempotency**
Build: repo scaffold; `schema.sql` on Turso (libSQL connection); pydantic models; `llm/client.py` + hash cache; `registry.py` (CRUD, recursive-CTE traversal, raw-immutability trigger).
DoD: `test_idempotency.py` green (re-ingest = 0 LLM calls, 0 new rows); raw-immutability trigger fires on update; schema migrates on startup.

**Phase 2 — Core agents**
Build: `BaseAgent` + Reader, Summarizer, Concept Extractor, KG Agent; prompt files; structured output; model routing in `settings.yaml` (mechanical → free model, synthesis → Claude).
DoD: each agent passes a golden-fixture test; claims are atomic; every claim has a `source_span` or `null`+lowered confidence.

**Phase 3 — Pipeline + vault writer + CLI**
Build: `pipeline/ingest.py` (sequential coordinator); `wiki_writer.py` (idempotent upsert of source + concept pages, syncs DB↔front-matter↔wikilinks); `index.md`/`log.md`; 3 templates; `pkm ingest --new-only`.
DoD: `test_ingest_e2e.py` green — fixture article → source page + ≥1 concept page + claim rows (`status=pending_review`); re-run is a no-op.

**Phase 4 — GitHub Actions orchestration**
Build: `.github/workflows/ingest.yml` (repository_dispatch + push-to-`raw/` + nightly cron; commit-back; `concurrency` serialization; 10-min timeout); secrets wired.
DoD: pushing a file to `raw/` triggers a run that writes wiki pages + Turso rows and commits back; re-push is a no-op; runs serialize.

**Phase 5 — Capture Worker**
Build: `worker-clip.js` (accepts `{url,type,text}`, offloads big blobs to R2, commits `raw/*.md`, fires `repository_dispatch`); shared-secret header; bookmarklet/clipper config.
DoD: clipping an article lands an immutable `raw/` file and triggers Phase-4 processing end-to-end; Mac can be asleep after the click.

**Phase 6 — Embeddings + vector + Query Worker**
Build: `embed.py` (Workers AI bge); vector upsert during ingest (Vectorize **or** Turso vectors — Tier-1 choice, default Vectorize); `worker-query.js` (embed → vector top-k → Turso fetch → Claude synthesis → answer + `raw/` citations).
DoD: `curl "$WORKER/query?q=..."` returns an answer citing `raw/` spans; no local server involved.

**Phase 7 — Scheduled jobs + guardrails**
Build: nightly lint + dashboard crons; `dashboard.md` (output counts, cost, orphan/contradiction queues); 80%-Actions-minutes alert; second-remote backup.
DoD: dashboard regenerates nightly; lint writes failures to `log.md`; spend caps confirmed at $0; backup push works.

**Phase 8 — Hardening + MVP DoD**
DoD (the MVP gate): clipping a source → synthesized, linked, cited wiki page; **zero local daemon**; **$0 infra**; idempotent re-ingest; raw/ immutable; query works at the edge; full test suite green; cost actuals recorded. → **Surface MVP review (Section 5).**

---

## 5. When to surface back to strategic review (this chat)

Goal: **few interactions.** Most work proceeds autonomously. There are exactly three surfacing modes; default to the cheapest that applies.

### Mode A — DECIDE & LOG (no surfacing). This is the default.
Reversible, in-scope, spec-aligned choices: libraries, file layout, prompt wording, test structure, naming within conventions, retries/backoff, refactors, anything cheap to change later. **Pick the spec-aligned option, log one line in `DECISIONS.md`, proceed.** Do not ask.

### Mode B — PROPOSE, PROCEED, RATIFY LATER (batched, non-blocking)
For **Tier-1** items: notable-but-reversible. Choose a sensible default, **keep building**, and list them for ratification at the *next* version gate (Mode C). Do **not** stop. Tier-1 triggers:
- An open choice the docs explicitly left to the user (e.g., **Vectorize vs Turso vectors**; **engine repo public vs private**; model-routing aggressiveness).
- A reversible deviation from the spec you made and want ratified.
- A quality concern worth a strategic look but not blocking (e.g., extraction quality weak on one source class).

### Mode C — STOP & SURFACE IMMEDIATELY (rare — only when truly necessary)
For **Tier-2** items: irreversible, cost-breaking, scope-changing, or trust-sensitive. **Halt that workstream and post a brief.** Tier-2 triggers — surface if **any** is true:
1. **The $0 goal breaks.** A free-tier limit/pricing assumption in the docs is now false in a way that would incur recurring infra cost (Cloudflare / GitHub / Turso changed terms; design no longer fits free tiers).
2. **Claude cost would exceed the user's cap** for normal operation even after caching + free-model routing.
3. **Spec is infeasible as written and the fix changes the architecture** (not a local code workaround) — e.g., raw-immutability, the edge/graph model, or the idempotency cache can't work on the chosen service.
4. **Irreversible / migration-expensive decision the docs don't already settle** — schema/ID/ontology change beyond what's specified, or a change that would force reprocessing all of `raw/`.
5. **Trust / blast-radius** — any action that would widen a secret scope, make the vault public, or send vault content to a third party not named in the docs.
6. **Can't meet a phase's DoD without adding a component not in the spec** (genuine scope expansion).

### Planned version gates (the main expected interactions)
At each version boundary — **MVP done**, then before **V1 → V2 → V3** — surface a concise review (Mode C format) containing the Mode-B batch. Expect ~**one strategic interaction per version (≈4 total across the whole roadmap)**, plus rare Tier-2 stops. Do **not** create per-task or per-phase chat interactions.

### Surfacing brief template (keep it tight — no logs dumps)
```
## [MVP review | Tier-2 stop] — <one-line subject>
What shipped: <2–3 sentences, link PROGRESS.md>
Cost actuals: infra $X (target $0), Claude $Y/mo (cap $Z)
Decision(s) needed:
  1. <question> — recommended default: <X>; what I'll do if no reply: <proceed with X>
Tier-1 batch (FYI, already proceeding on defaults): <bullets>
Blocking? <yes: workstream halted | no: continuing on default>
```
Whenever possible, **state the recommended default and proceed on it if no reply**, so even a surfaced item rarely blocks progress.

---

## 6. Done = the MVP gate in Phase 8, reviewed via Mode C.
After ratification, await the user's go-ahead before starting V1 (Chroma/Vectorize-full, the 12 templates, nightly lint upgrades, the output dashboard, claim-promotion rule). Do not begin V1 autonomously — version progression is a human judgment call (spec promotion gates).
