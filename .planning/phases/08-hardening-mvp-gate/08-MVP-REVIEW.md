# Phase 8 — MVP Review Brief (Mode C, human judgment)

**Status:** ✅ **MVP-ready — declared by the human operator on 2026-06-21.**
This is a Type-1 (irreversible) human call per `CLAUDE.md` "Stop at MVP gate; do
NOT start V1 autonomously." Claude presented the evidence; the human chose
option (a) MVP-ready. The system is held at the MVP gate — V1 is a separate
future decision and is **not authorized**.

**Date:** 2026-06-21

---

## MVP criterion verdicts (consolidated)

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| **MVP-01** — clip → synthesized wiki page with citations within ~5 min, Mac asleep | **PASS** | `docs/PHASE8_VERIFICATION.md` § MVP-01 — Phase 5 live run `27876239381` (success, ~165s ≈ 2m45s ≤ ~5 min); `pkm-bot` commit `b62a82e`; runtime path all edge/cloud; fresh `pgrep` 2026-06-21 → no local daemon |
| **MVP-02** — re-clip same article = complete no-op | **PASS** | `docs/PHASE8_VERIFICATION.md` § MVP-02 — `deduped:true`, 0 new sources/chunks/claims/agent_runs rows, `cost_usd_total:0.0` `tokens_total:0` (0 LLM calls), no new vault commit (run `27876585247`) |
| **MVP-03** — every wiki claim resolves to a raw/ source span | **PASS** (hard gate) | `docs/PHASE8_VERIFICATION.md` § MVP-03 — `broken_wikilinks == 0` (re-verified vs vault HEAD `97a2fc2`); missing-provenance = 111 (accepted limitation, see below) |
| **MVP-04** — Query Worker returns cited answer, no local server | **PASS** | `docs/PHASE8_VERIFICATION.md` § MVP-04 — Phase 6 Wave 3 live deploy; `/query` returns `{answer, citations[]}` with `raw_path` resolving to vault files; fresh `pgrep` → no local server |
| **MVP-05** — full test suite green | **PASS** | `docs/PHASE8_VERIFICATION.md` § MVP-05 — pytest 137 passed / npm clip 13 / npm query 19, 0 failed |
| **MVP-06** — cost actuals: infra $0, OpenAI $/mo ≤ cap | **PASS** | `PROGRESS.md` "Cost Actuals" — 4 infra rows $0; OpenAI $0.35/mo (June 2026: $0.353260 / 197,154 tokens / 40 agent_runs rows from `SUM(cost_usd)`); per-run cap $0.50 + monthly hard limit confirmed |

**All six MVP criteria PASS on the evidence.**

---

## Tier-1 dispositions (from `DECISIONS.md` "Phase 8 MVP-gate review")

| Tier-1 item | Disposition | Verification |
|-------------|-------------|--------------|
| **T1-01** Vectorize over Turso native vectors | **reaffirm** | `pkm-claims` index live, 160 claims embedded (Phase 6 Wave 3); query worker depends on it. Turso native vectors have not reached parity. No change. |
| **T1-02** OpenAI gpt-5.4-mini backend (locked 2026-06-19) | **all 3 conditions PASS** | (1) sync dispatch — `ingest.yml:20` `timeout-minutes: 10`, no Batch API; (2) cost_usd from usage — `client.py:352` `compute_cost`, `pricing.py:40` KeyError-on-unknown (never 0.0); (3) cache-bust — `client.py:168-174` `_make_input_hash` includes model string. Cross-ref PROGRESS.md MVP-06: real non-zero costs. |

**Carried to MVP review (NOT locked here):**
- **[T2-05-04] drop-FK / free-text-provenance** — deferred Type-1 contract change. The human decides at this checkpoint whether to accept the best-effort-provenance limitation for MVP or pursue the contract change in V1.

No new Type-1 decision was locked in Phase 8.

---

## Accepted limitations

**CF_ACCOUNT_ID + CF_API_TOKEN GitHub Actions secrets: CLOSED (set 2026-06-21
per `docs/GUARDRAILS.md` lines 151-152, 195-196) — NOT an open or accepted-MVP
limitation.** The CI "Backfill embeddings" step runs with real credentials;
new sources auto-embed. (Reconciled in `.planning/STATE.md` by Plan 08-02.)

**Dashboard counter backfill: CLOSED by Plan 08-01** — `seed_counters_from_live_counts`
run against live Turso on 2026-06-21 set `sources_total=7, claims_total=160,
concepts_total=40` (was reading 0). NOT an open limitation.

**The only accepted limitation carried to V1:**
- **Missing-provenance best-effort (DECISIONS.md [T2-05-04]).** 111 claims have
  `chunk_id IS NULL` because the `para_N → ordinal` chunk-resolution heuristic
  is best-effort (chunks are ~1200-token windows, not paragraphs) and the LLM
  emits positional labels it cannot map to real `chunks.id`s. These claims use
  the string-`"null"` sentinel → SQL NULL at the insert boundary. The
  drop-FK / free-text-provenance alternative (richest signal) is deferred to V1
  as a Type-1 contract change. MVP-03's hard gate (`broken_wikilinks == 0`)
  holds regardless; the 111 is recorded verbatim and carried as an
  accepted-MVP limitation.

**Evidence-provenance caveat (introduced by operator-effort minimization):**
MVP-01/02/04 are cited from the Phase 5 / Phase 6 Wave 3 live verification runs
(2026-06-17 / 2026-06-21) rather than a freshly re-run Phase-8 demo. The
architecture and corpus are unchanged since those runs, the full test suite is
green (MVP-05), and a Phase 7 `workflow_dispatch` run (`27901063045`,
2026-06-21) re-confirmed the cloud path end-to-end. Fresh corroboration
(no-local-daemon `pgrep`, raw_path existence in the current vault checkout) was
gathered 2026-06-21. **If the human judges a fresh Phase-8 demo is required,
that is option (c) NOT-ready with a specified re-run remediation.**

---

## V1+ advancement — NOT authorized at this gate

Per `CLAUDE.md` and `ROADMAP.md` "Advancement Gates (Post-MVP)", V1+ advancement
is a separate human decision and is **not triggered at MVP**:

| ROADMAP advancement trigger | Current state | Met? |
|-----------------------------|---------------|------|
| Corpus ≳ 150 sources | 7 sources (160 claims) | **No** |
| Long-context misses answers | not observed | **No** |
| Relational / multi-hop / "what's changing" questions recur | not observed | **No** |

**No V1/V2/V3 work was begun in Phase 8** (`git diff main -- pkm/` contains no
`chroma`/`neo4j`/`graphrag`/`hybrid`/`leiden`). This checkpoint is only the
MVP-ready judgment.

---

## Decision required (Type-1, human)

Choose ONE:

- **(a) MVP-ready** — accept the system as MVP; hold at the gate. V1+ remains a
  separate future decision.
- **(b) MVP-ready with documented limitations** — accept and log the
  limitations for V1 (the missing-provenance best-effort limitation per
  T2-05-04, plus any others you want recorded).
- **(c) NOT-ready: `<criterion + remediation>`** — specify which criterion
  failed and the required remediation (e.g. a fresh Phase-8 live demo for
  MVP-01/02/04, or closing the missing-provenance gap). This triggers a Phase 8
  gap-closure round.

**Do NOT type "start V1".** V1+ advancement is not on the table at this
checkpoint.

---

## Verdict (recorded 2026-06-21)

**Human judgment: MVP-ready** (option a).

- All six MVP criteria PASS on the evidence (table above).
- Accepted limitation carried to V1: **missing-provenance best-effort**
  (DECISIONS.md [T2-05-04]) — 111 claims have `chunk_id IS NULL` because the
  `para_N → ordinal` chunk-resolution heuristic is best-effort. The drop-FK /
  free-text-provenance alternative is deferred to V1 as a Type-1 contract
  change. MVP-03's hard gate (`broken_wikilinks == 0`) holds regardless.
- Tier-1 batch reaffirmed: T1-01 Vectorize, T1-02 OpenAI gpt-5.4-mini (all 3
  conditions PASS). No new Type-1 decision locked.
- **V1+ advancement NOT authorized.** ROADMAP advancement triggers not met
  (7 sources ≪ 150; no long-context misses; no relational-question recurrence).
  The system is held at the MVP gate. Starting V1 (Chroma, 12 templates, hybrid
  retrieval, Neo4j, GraphRAG, V2/V3 agents) is a separate future human decision.
- Evidence provenance: MVP-01/02/04 cited from Phase 5 / Phase 6 Wave 3 live
  runs + fresh 2026-06-21 corroboration (accepted by the human as sufficient).

---

*No secret values recorded in this brief. All citations are to committed docs
or file:line evidence.*