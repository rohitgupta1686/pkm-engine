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