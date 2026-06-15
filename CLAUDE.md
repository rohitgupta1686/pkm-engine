# AI-Assisted PKM System — Project Instructions

## Project

Building a cloud-native PKM system: clip → synthesized wiki page, $0 infrastructure, zero local daemon.

**Repos:**
- `pkm-engine` — public GitHub repo (all code: Python pipeline, Cloudflare Workers, GitHub Actions workflows)
- `pkm-vault` — private GitHub repo (Markdown vault: raw/, wiki/, SCHEMA.md, index.md, log.md)

**Current planning:** `.planning/` in this directory.

## Authoritative Documents

Read all four before making architectural decisions (conflict resolution: cloud doc > tech spec > process; build plan governs process):

1. `PKM_Build_Plan_for_Claude_Code.md` — 8 phases, operating modes, DoDs, surfacing rules
2. `PKM_TECHNICAL_SPECIFICATION.md` — ontology, DB schema, agents, note schema, naming, pydantic models
3. `PKM Cloud Architecture.md` — cloud-native layer: Turso, GitHub Actions, Cloudflare Workers/Vectorize/R2
4. `compass_artifact_wf-b56e1318-b024-4ef7-8802-a532e01c712d_text_markdown.md` — background/rationale

## Hard Constraints

- **$0 infrastructure** — all services stay on free tiers; no paid plan ever
- **Zero local daemon** — nothing runs continuously on Mac; no menu-bar agents, no cron on Mac
- **raw/ is immutable** — write-once; DB trigger enforces; re-ingest is always idempotent
- **No secrets committed** — use `.env.example`, GitHub Actions Secrets, Worker Secrets
- **Large text out of Turso** — Turso holds metadata + edges + cache; text lives in Git/R2
- **Stop at MVP gate** — do NOT start V1 autonomously after Phase 8

## Operating Mode: YOLO

Default to autonomy. Surface back (Mode C) ONLY for:
1. $0 goal breaks (infra would incur recurring cost)
2. Claude cost would exceed spend cap for normal operation
3. Spec is architecturally infeasible as written
4. Irreversible/migration-expensive decision the docs don't settle
5. Trust/blast-radius: widening secret scope, making vault public, unnamed third party
6. Can't meet phase DoD without spec-unspecified scope expansion

Log reversible choices in `DECISIONS.md` (Mode A). Tier-1 choices: proceed on default, list for MVP review (Mode B).

## GSD Workflow

**Planning files:** `.planning/`
- `PROJECT.md` — project context
- `REQUIREMENTS.md` — 44 v1 requirements with REQ-IDs
- `ROADMAP.md` — 8 phases with success criteria
- `STATE.md` — current phase and status

**Next step:** `/gsd:plan-phase 1` to create PLAN.md for Phase 1.

## Phase 1 Scope (current)

Building in `pkm-engine` repo:
- `pyproject.toml`, `.env.example`, repo scaffold
- `pkm/config.py`, `pkm/store/registry.py` (libSQL connection)
- `migrations/sqlite/001_init.sql` + `002_graph_tables.sql`
- `pkm/schemas/` (pydantic models)
- `pkm/llm/client.py` + `pkm/llm/models.py`
- `tests/test_idempotency.py` + fixtures

DoD: idempotency test green, raw-immutability trigger fires, schema auto-migrates.
