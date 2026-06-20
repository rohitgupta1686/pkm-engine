# Phase 4 — Live Dispatch Verification (Plan 04-03)

**Date:** 2026-06-20
**Operator:** rohitgupta1686 (gh active account switched from `rohitgupta-mnm`, which lacks
secrets + private-vault access, to `rohitgupta1686`)
**Result:** ✅ All five Phase-4 live success criteria PASS.

This document records evidence captured from real GitHub Actions runs and the
private `pkm-vault` repo. No secret values appear below.

---

## Precondition gate

`gh secret list --repo rohitgupta1686/pkm-engine` (run under `rohitgupta1686` account):

| Secret | Set |
|---|---|
| OPENAI_API_KEY | 2026-06-19T16:40:57Z |
| TURSO_URL | 2026-06-19T16:41:18Z |
| TURSO_TOKEN | 2026-06-19T16:57:14Z |
| VAULT_PAT | 2026-06-19T16:42:00Z |

`OPENAI_BASE_URL` is intentionally NOT set (cloud run uses the direct OpenAI
endpoint via the `config.py` default; see "Fixes" #1). Vault access confirmed:
`rohitgupta1686/pkm-vault` (private) reachable via `gh api`.

A seeded un-ingested raw fixture was already present in the vault from a prior
session: `raw/2026-06-19T1630Z__example__operating-leverage__9709e6.md`
(commit `9962c89`, "test(seed): add raw/ fixture for 04-03 live dispatch verification").
Baseline vault HEAD before verification: `9962c89718aab5e4472c78b88ff975509197725c`.

---

## ORCH-01 — dispatch triggers a successful run under 10 minutes ✅

Command: `gh api repos/rohitgupta1686/pkm-engine/dispatches -f event_type=ingest`

| Field | Value |
|---|---|
| Run ID | 27862701808 |
| URL | https://github.com/rohitgupta1686/pkm-engine/actions/runs/27862701808 |
| Trigger | repository_dispatch (event_type=ingest) |
| Conclusion | success |
| Elapsed | ~28s (started 06:19:44Z, updated 06:20:14Z) |
| Budget (ORCH-06 / criterion 5) | 28s ≪ 10:00 ✓ |

All steps green: Checkout engine, Checkout vault (VAULT_PAT), Set up Python 3.11,
Install engine, Run batch ingest, Commit synthesized wiki.

## ORCH-04 — pkm-bot commit lands in pkm-vault with wiki changes ✅

After run 27862701808, the vault gained a new commit:

| Field | Value |
|---|---|
| Vault HEAD (new) | `1d7c6f33b5b2f94c9c8a2a67f1c87a1fcca3c9fe` |
| Author | pkm-bot |
| Message | `synthesize: 2026-06-20T06:20:10Z` |
| Files changed | `log.md` (modified); `wiki/sources/operating-leverage-and-business-scalability.md` (added) |

Confirm: `gh api repos/rohitgupta1686/pkm-vault/commits` → latest commit author
`pkm-bot`, message starts `synthesize:`, and `wiki/` files changed. ✓

## ORCH-07 — re-dispatch produces no new commit (idempotent no-op) ✅

Re-fired the identical dispatch. The raw file's content_hash is now recorded in
Turso, so `pkm batch-ingest --new-only` produced nothing new and the commit-back
step short-circuited.

| Field | Value |
|---|---|
| Re-run ID | 27862732584 |
| URL | https://github.com/rohitgupta1686/pkm-engine/actions/runs/27862732584 |
| Conclusion | success |
| Vault HEAD before | `1d7c6f33b5b2f94c9c8a2a67f1c87a1fcca3c9fe` |
| Vault HEAD after | `1d7c6f33b5b2f94c9c8a2a67f1c87a1fcca3c9fe` (unchanged) |
| Commit-back log | `git diff --cached --quiet` → no commit; `git push` → `Everything up-to-date` |

End-to-end idempotency confirmed: HEAD SHA unchanged. ✓

## ORCH-05 — concurrent dispatches queue, neither cancelled ✅

Fired two dispatches back-to-back. The workflow's `concurrency: {group: ingest,
cancel-in-progress: false}` serialized them.

| Run ID | Initial status | Final conclusion | URL |
|---|---|---|---|
| 27862753167 | in_progress (first) | success | https://github.com/rohitgupta1686/pkm-engine/actions/runs/27862753167 |
| 27862753443 | pending (queued) | success | https://github.com/rohitgupta1686/pkm-engine/actions/runs/27862753443 |

The second run was `pending` (queued/waiting) while the first ran, then executed
after the first completed. Neither run was `cancelled`. ✓

---

## Fixes applied during live verification

The first dispatch attempts surfaced five previously-untested OpenAI-backend
issues in the 04-04 OpenAI swap. Each was reproduced locally, fixed, committed,
and pushed to `pkm-engine` main (88-test suite green throughout):

1. **`8eb05e9` — empty `OPENAI_BASE_URL` broke the SDK.** The workflow passed
   `OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL }}`; the secret is intentionally
   unset for the cloud run, GitHub resolves an absent secret to `""`, and
   pydantic-settings overrode the config default with `""` →
   `openai.OpenAI(base_url="")` → `APIConnectionError("Connection error.")`.
   Reproduced locally. Fix: removed `OPENAI_BASE_URL` from the workflow env
   (base_url override is for local CLIProxyAPI dev only).

2. **`d5ef900` — `max_tokens` unsupported on gpt-5.x.** `LLMClient._call_api` sent
   `max_tokens=4096`; gpt-5.4-mini rejects it (`400 unsupported_parameter`,
   "Use 'max_completion_tokens' instead"). Fix: use `max_completion_tokens`
   (the unified param OpenAI accepts across current chat models).

3. **`fa04b32` — strict schema carried unsupported constructs.**
   (a) `GraphNode.properties` was `dict = {}` → pydantic emits
   `{"additionalProperties": true}`, which OpenAI strict rejects. Typed to
   `dict[str, str]` first, then (see #5) to an array of key/value objects.
   (b) `_strictify` did not strip unsupported strict-mode keywords; `Field(ge=,le=)`
   emit `minimum`/`maximum`, which OpenAI strict does not support (its own SDK
   strips them). Added `_UNSUPPORTED_STRICT_KEYS` stripping.

4. **`bef375a` — `$ref`/`$defs` not isolated by OpenAI strict.** After #3,
   OpenAI reported GraphNode's `required` as "extra required keys" at the root
   context — it was treating `$defs/GraphNode` required as if it belonged to
   the root. Fix: `_inline_refs()` resolves every `$ref` to its `$defs` entry
   in place and drops `$defs`, yielding a self-contained nested schema (no
   `$ref` resolution needed). Cycle-guarded.

5. **`23df36c` — typed maps unsupported; use array of {key,value}.** After
   inlining, OpenAI dropped the `attributes` property (a typed map
   `additionalProperties:{type:string}`) but kept it in `required`, reporting
   "Extra required key 'attributes'." OpenAI strict does not support typed-map /
   free-form objects; the documented strict-compatible representation of a
   string→string map is an array of closed key/value objects. `GraphNode.attributes`
   is now `list[GraphAttribute]` where `GraphAttribute = {key: str, value: str}`.
   Field named `attributes` (not `properties`) to avoid JSON-Schema keyword noise.
   (`193c89e` performed the `properties`→`attributes` rename; `23df36c` completed
   the array-of-kv representation.) Prompt + test helper updated accordingly.

These are reversible Type-2 fixes to make the locked OpenAI backend (T1-02)
actually work end-to-end; no architectural change to the design.

---

## Success-criteria summary

| # | Criterion (ROADMAP Phase 4) | Result |
|---|---|---|
| 1 | Dispatch triggers a run that writes wiki pages to pkm-vault | ✅ (run 27862701808) |
| 2 | pkm-bot commit appears in pkm-vault | ✅ (commit `1d7c6f3`, author pkm-bot) |
| 3 | Re-dispatch = no new commit | ✅ (HEAD unchanged `1d7c6f3`) |
| 4 | Concurrent dispatches queue (second waits, not cancelled) | ✅ (runs 27862753167 / 27862753443, both success) |
| 5 | Run completes < 10 minutes | ✅ (~28s) |

All five Phase-4 live success criteria observed and recorded.