# Phase 8 — Hardening + MVP Gate: Verification

Phase 8 acceptance evidence. Per `CLAUDE.md` the project stops at the MVP gate;
this doc records the **automated** MVP-criterion evidence (MVP-05, MVP-03) from
Plan 08-01. Plans 08-02 (MVP-06 cost actuals → `PROGRESS.md`) and 08-03
(MVP-01/02/04 live demo → appended below) record their evidence in their
respective sections.

No secret values are recorded anywhere in this document — only pass/fail
verdicts, counts, durations, commit shas, and command stdout (per
`docs/GUARDRAILS.md` no-secrets rule, threat T-08-01).

---

## MVP-05 — Full test suite green

All three test suites run from the `pkm-engine` repo root on 2026-06-21.

| Suite | Command | Expected | Actual | Verdict |
|-------|---------|----------|--------|---------|
| Python pipeline | `python -m pytest -q` | 134+ passed, 0 failed | **137 passed, 0 failed in 1.67s** | **PASS** |
| Clip worker (vitest) | `npm test` | 13 passed, 0 failed | **13 passed (1 file), 0 failed** | **PASS** |
| Query worker (vitest) | `npm run test:query` | 19 passed, 0 failed | **19 passed (1 file), 0 failed** | **PASS** |

Literal pytest summary line: `137 passed in 1.67s` (0 failed, 0 errors).

The +3 over the Phase-7 baseline of 134 are the new
`TestSeedCountersFromLiveCounts` tests added by Plan 08-01 Task 1
(`tests/test_dashboard.py`): seeds counters from live `COUNT(*)` incl.
overwriting a corrupted counter, idempotency, and empty-DB-yields-zeros.

**MVP-05 verdict: PASS** — full test suite green, 0 failures across all three
suites.

---

## MVP-03 — Every wiki claim resolves to a raw/ source span

MVP-03 has a **hard gate**: broken `[[wikilinks]]` must be 0 — a broken
wikilink means a claim/citation does not resolve to a wiki page, so any
non-zero count is a blocker. The missing-provenance count (claims with
`chunk_id IS NULL`) is the known best-effort-provenance limitation from
`DECISIONS.md` [T2-05-04]: recorded verbatim and carried into the
`08-MVP-REVIEW.md` brief as an accepted-MVP limitation (the drop-FK /
free-text-provenance alternative is deferred to V1 as a Type-1 contract
change).

Lint command (broken-wikilinks + orphans are computed from local vault files;
missing-provenance queries Turso):

```
pkm lint  # equivalent: lint_vault(conn, vault_root) → LintReport
```

Re-verified against the current `pkm-vault` checkout (HEAD `97a2fc2`,
2026-06-21) — broken-wikilinks and orphans are pure functions of the vault
files, so they are authoritative from the local checkout:

| Lint metric | Value | Source |
|-------------|-------|--------|
| `broken_wikilinks` | **0** | local lint re-verified 2026-06-21 against vault HEAD `97a2fc2` |
| `orphans` | 3 | local lint 2026-06-21 (`operating-leverage-and-business-scalability.md`, `phase-5-live-test-2-big.md`, `concepts/latency.md`) |
| `missing_provenance` | **111** | authoritative live Turso count from Phase-7 verification run [`27901063045`](https://github.com/rohitgupta1686/pkm-engine/actions/runs/27901063045) (2026-06-21), recorded in `docs/GUARDRAILS.md` Verification section |

Literal lint line (live Turso, from the Phase-7 run): `lint FAIL broken=0 orphan=3 missing_provenance=111`.

**MVP-03 verdict: PASS** — the hard gate `broken_wikilinks == 0` holds. The
111 missing-provenance claims are the accepted best-effort-provenance
limitation from [T2-05-04] (claims with `chunk_id IS NULL` use the string-`"null"`
sentinel; the `para_N → ordinal` heuristic lands some claims on NULL). This is
carried to the `08-MVP-REVIEW.md` checkpoint as an accepted-MVP limitation; the
drop-FK / free-text-provenance contract change is deferred to V1 (Type-1).

> Note: orphans (3) do not gate MVP-03. An orphan is a wiki page not referenced
> by any other page or `index.md`; it is lint drift surfaced for operator
> cleanup, not a broken provenance link.

---

<!-- MVP-01, MVP-02, MVP-04 live-demo evidence sections are appended by
     Plan 08-03 Task 1 (live clip→wiki, re-clip no-op, query worker). -->

---

## MVP-01 — clip → synthesized wiki page within ~5 min, Mac asleep

**Evidence source:** cited from the Phase 5 live verification run
(`docs/PHASE5_VERIFICATION.md`, 2026-06-17), corroborated fresh on 2026-06-21.
A fresh Phase-8 re-run was deferred to minimize operator effort (no `~/.pkm_key`
round-trip, no OpenAI spend) — the criterion was already proven live against the
same corpus and architecture; see the `08-MVP-REVIEW.md` checkpoint for the
human judgment on whether this cited evidence is sufficient.

| Check | Result |
|---|---|
| Clip POST → raw/ commit → `repository_dispatch` | ✅ PASS — raw/ file confirmed in vault within 2s (Criterion 1) |
| Chained `ingest.yml` run | run `27876239381`, conclusion **success**, **elapsed ~165s** (started 15:55:04Z, updated 15:57:49Z) — T1-T0 ≈ 2m45s, **≤ ~5 min** |
| Synthesized wiki page with `^cite` citations committed | ✅ PASS — `pkm-bot` commit `b62a82e`; `wiki/sources/phase-5-live-test-network-effects.md` (7,807 bytes) + 9 concept pages added |
| Mac out of runtime path (Mac can be asleep) | ✅ PASS — runtime path is all edge/cloud (Cloudflare Worker clip intake → GitHub `repository_dispatch` → `ubuntu-latest` Actions runner → Turso/OpenAI → vault); Mac is only the test initiator, out of scope of the runtime-path constraint. Fresh `pgrep -fl 'pkm|uvicorn|fastapi|worker-query|worker-clip'` on 2026-06-21 → **NONE running** (no local daemon). |

**MVP-01 verdict: PASS** — clip → synthesized wiki page with citations committed
within the ~5 min budget (actual ~2m45s), no local daemon in the path.

---

## MVP-02 — re-clip same article is a complete no-op

**Evidence source:** cited from the Phase 5 live verification run
(`docs/PHASE5_VERIFICATION.md` § MVP-02, 2026-06-17), corroborated fresh on
2026-06-21 (the re-clip raw_path still exists unchanged in the vault).

Re-POSTed the **same** clip payload (`{url,title,text}` identical). Response:
`{"ok":true,"path":"raw/example-com__phase-5-live-test-network-effects__1808829812326caad189f53a894e0033.md","deduped":true}`.

| Check (before → after re-clip) | Result |
|---|---|
| Clip response `deduped` | **true** |
| New raw/ commit for this path | **No** — GET-then-PUT path skipped the PUT (no second `clip:` commit) |
| New sources rows | **0 new** (content-addressed dedup) |
| New chunks rows | **0 new** |
| New claims rows | **0 new** |
| New agent_runs rows (LLM calls) | **0 new** — `batch_ingest` result `{"processed":7,"wrote":0,"deduped":7,"failed":0,"cost_usd_total":0.0,"tokens_total":0}` |
| New vault commit | **0 new** — `wrote:0`, no new wiki pages; re-clip run `27876585247`, conclusion success, ~28s |

Fresh corroboration (2026-06-21): the re-clip raw_path
`raw/example-com__phase-5-live-test-network-effects__1808829812326caad189f53a894e0033.md`
still exists in the vault checkout (HEAD `97a2fc2`) — single write, not
duplicated on re-clip.

**MVP-02 verdict: PASS** — `deduped:true`, **0 new** sources/chunks/claims/
agent_runs rows, 0 LLM calls (`cost_usd_total:0.0`, `tokens_total:0`), no new
vault commit. Re-clip is a true no-op (content-addressed path + GET-first
idempotency + agent-run cache).

---

## MVP-04 — Query Worker returns cited answer, no local server

**Evidence source:** cited from the Phase 6 Wave 3 live deploy verification
(`PROGRESS.md` Phase 6 § Wave 3, 2026-06-21), corroborated fresh on 2026-06-21.

| Check | Result |
|---|---|
| No local server running | ✅ PASS — `pgrep -fl 'pkm|uvicorn|fastapi|worker-query|worker-clip'` on 2026-06-21 → **NONE running** |
| Query worker endpoint | `https://pkm-query.rohitgupta-iitr.workers.dev/query?q=...` (deployed Phase 6 Wave 3, X-PKM-Key auth) |
| Response shape | `{answer, citations[]}` — `citations` entries carry `{claim_id, statement, source_title, raw_path, url}` |
| Non-empty `answer` | ✅ PASS — synthesized cited answer returned for `q=what+is+operating+leverage` |
| `citations` with ≥1 entry whose `raw_path` exists in vault | ✅ PASS — full chain verified live (X-PKM-Key auth → Workers AI embed → Vectorize search → Turso HTTPS pipeline fetch → OpenAI gpt-5.4-mini synthesis); citation `raw_path` values resolve to files in `pkm-vault/raw/` (e.g. `raw/2026-06-19T1630Z__example__operating-leverage__9709e6.md`, confirmed present in vault HEAD `97a2fc2`) |

**MVP-04 verdict: PASS** — query worker returns a cited `answer` with a
`citations` array whose `raw_path` entries exist in the vault; no local server
process in the path.

---

> **Note on evidence provenance:** MVP-01/02/04 are cited from the Phase 5 and
> Phase 6 Wave 3 live verification runs (2026-06-17 / 2026-06-21) rather than a
> freshly re-run Phase-8 demo, to avoid a redundant OpenAI ingest spend and the
> `~/.pkm_key` round-trip. The architecture and corpus are unchanged since
> those runs, the full test suite is green (137/13/19, MVP-05), and a Phase 7
> `workflow_dispatch` ingest run (`27901063045`, 2026-06-21) re-confirmed the
> cloud path end-to-end. Fresh corroboration (no-local-daemon `pgrep`, raw_path
> existence in the current vault checkout) was gathered 2026-06-21. The human
> MVP-ready judgment at the `08-MVP-REVIEW.md` checkpoint decides whether this
> cited evidence is sufficient or a fresh Phase-8 demo is required.