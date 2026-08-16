# KICKOFF — paste this into Claude Code as the first message

> Have all four project docs present in the repo before sending this:
> `PKM_Build_Plan_for_Claude_Code.md`, `PKM_TECHNICAL_SPECIFICATION.md`,
> `PKM_Cloud_Architecture.md`, and the research synthesis blueprint.

---

You are implementing the AI-Assisted PKM system. Four authoritative documents are in this repo — read all four before doing anything:

- **PKM_Build_Plan_for_Claude_Code.md** → your operating brief: how to work, the 8 phases, and the escalation rules. THIS GOVERNS PROCESS.
- **PKM_TECHNICAL_SPECIFICATION.md** → system design: ontology, DB schema, agents, note schema, naming, metadata, MVP plan.
- **PKM_Cloud_Architecture.md** → cloud-native, $0-infrastructure data/processing layer.
- **AI-Assisted_Personal_Knowledge_Management__Research_Synthesis_and_Build_Blueprint.md** → background/rationale only; context, not instructions. Do not re-derive it.

**Conflict rule:** cloud doc wins for infrastructure; technical spec wins for everything else; build plan wins for process. Honor decisions AD-1…AD-8 and the MVP scope (4 node types, 3 templates, no Neo4j, no full vector path). Do not re-litigate settled decisions.

**Settled decisions (do not ask about these):**
- `pkm-engine` repo is **public** (unlimited free Actions minutes; no secrets in it). `pkm-vault` is **private**.
- The ingest workflow therefore lives in `pkm-engine`, is triggered by `repository_dispatch` (+ nightly cron), and checks out / commits back to `pkm-vault` using a fine-grained `VAULT_PAT` (contents:write on the vault only). See Build Plan §3.1.

## STEP 1 — Plan first. Read the four docs, then DO NOT write code yet. Reply with:
- **(a)** A project plan: the 8 phases from the build plan, each with the concrete files/tasks you'll create and its Definition of Done.
- **(b)** The one-time prerequisites checklist I must complete (GitHub repos; `ANTHROPIC_API_KEY` + spend cap; Turso DB + `TURSO_URL`/`TURSO_TOKEN`; Cloudflare `CF_ACCOUNT_ID` + scoped token; `VAULT_PAT`; GitHub Actions spending limit = $0), flagging which prerequisite blocks which phase.
- **(c)** Any Tier-2 question that must be answered before Phase 1 (expect zero).

Then stop and wait for me to confirm prerequisites are in place.

## STEP 2 — Execute phase by phase, only after I confirm prerequisites.
For each phase: build to its DoD, run the acceptance checks, append one line to `PROGRESS.md`, log reversible choices in `DECISIONS.md`, commit in logical units, and continue to the next phase automatically.

## OPERATING CONTRACT (condensed from the build plan)
- **Default to autonomy.** Surface back to me ONLY for Mode C / Tier-2 triggers: the $0 goal breaks; Claude cost would exceed my cap; the spec is architecturally infeasible as written; an irreversible/migration-expensive decision the docs don't settle; anything that widens a secret scope / makes the vault public / sends vault data to an unnamed third party; or genuine scope expansion. **Batch Tier-1 items and proceed on defaults; never stop for them.**
- **Hard constraints:** $0 infrastructure; ZERO local daemon (nothing runs continuously on my Mac); idempotent re-ingest via content-hash cache; `raw/` is write-once; keep large text OUT of Turso; never commit secrets.
- **Stop at the MVP gate (Phase 8)** and surface an MVP review. Do NOT start V1 on your own.

**Begin with STEP 1 now.**
