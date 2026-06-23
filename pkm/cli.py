"""
pkm CLI entry point.

Entry point: pkm.cli:app (see pyproject.toml [project.scripts]).

The redesigned pipeline is a SINGLE OpenAI GPT-5.4 call per source → one readable
Markdown note in <vault>/notes/. No Turso, no agents, no embeddings, no database:
ingestion is meant to run in CI (GitHub Actions) over a git checkout of the vault,
so nothing runs on a local machine.

Usage:
    pkm --help
    pkm ingest --raw <path> [--new-only]            # one capture → one note
    pkm batch-ingest [--vault <path>] [--new-only]   # all raw/*.md → notes/
    (synthesize / batch-synthesize are aliases.)

Security:
    - --raw / --vault paths come from env/CLI, not untrusted web input.
    - Settings (including OPENAI_API_KEY) are never printed; only the result dict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="pkm",
        description="AI-assisted Personal Knowledge Management — single-call note synthesis.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="subcommand")

    # -- ingest: one capture → one note ---------------------------------------
    ingest_parser = subparsers.add_parser(
        "ingest",
        aliases=["synthesize"],
        help="Synthesize ONE raw capture into ONE Markdown note (single LLM call).",
        description=(
            "One OpenAI GPT-5.4 call turns a raw capture into a readable note in "
            "<vault>/notes/. No agents, no claim/concept/graph extraction, no "
            "embeddings, no database. (Alias: `synthesize`.)"
        ),
    )
    ingest_parser.add_argument(
        "--raw", metavar="PATH", required=True,
        help="Path to the raw Markdown capture file to ingest.",
    )
    ingest_parser.add_argument(
        "--new-only", action="store_true", default=False,
        help="Skip if the target note already exists in <vault>/notes/.",
    )

    # -- batch-ingest: all raw/*.md → notes/ ----------------------------------
    batch_parser = subparsers.add_parser(
        "batch-ingest",
        aliases=["batch-synthesize"],
        help="Synthesize all raw/*.md captures into notes (single call each).",
        description=(
            "Scan raw/**/*.md in the vault and synthesize each into <vault>/notes/ "
            "via one LLM call per source. Idempotent with --new-only; aborts if the "
            "in-memory spend would exceed PKM_RUN_COST_CAP_USD. (Alias: `batch-synthesize`.)"
        ),
    )
    batch_parser.add_argument(
        "--vault", metavar="PATH", default=None,
        help="Path to the vault root directory. Defaults to VAULT_PATH from settings.",
    )
    batch_parser.add_argument(
        "--new-only", action="store_true", default=False,
        help="Skip captures whose note already exists in <vault>/notes/.",
    )

    return parser


def app() -> None:
    """PKM CLI entry point. Called by the `pkm` console script."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.subcommand in ("ingest", "synthesize"):
        _cmd_synthesize(args)
    elif args.subcommand in ("batch-ingest", "batch-synthesize"):
        _cmd_batch_synthesize(args)
    else:
        parser.print_help()
        sys.exit(0 if args.subcommand is None else 1)


def _build_synthesis_client(settings):
    """Build the DB-free OpenAI client for note synthesis (the locked provider).

    The single-call path always uses OpenAI GPT-5.4 and runs without a database
    (conn=None → no agent_runs cache). Idempotency is the note file's existence;
    spend is tracked in-memory via each call's returned cost_usd.
    """
    from pkm.llm.client import LLMClient

    return LLMClient(None, settings.openai_api_key, settings.openai_base_url)


def _cmd_synthesize(args: argparse.Namespace) -> None:
    """Execute ingest / synthesize (single capture → single note)."""
    from pkm.config import Settings
    from pkm.pipeline.ingest_note import run_note_ingest

    settings = Settings()
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    if not settings.vault_path:
        print("ERROR: VAULT_PATH is not set.", file=sys.stderr)
        sys.exit(1)

    raw_file = Path(args.raw)
    if not raw_file.exists():
        print(f"ERROR: Raw file not found: {args.raw}", file=sys.stderr)
        sys.exit(1)

    client = _build_synthesis_client(settings)
    result = run_note_ingest(
        client,
        vault_root=Path(settings.vault_path),
        raw_text=raw_file.read_text(encoding="utf-8"),
        raw_path=str(args.raw),
        model=settings.synthesis_model,
        notes_dirname=settings.notes_dirname,
        new_only=args.new_only,
    )
    print(json.dumps(result, indent=2))


def _cmd_batch_synthesize(args: argparse.Namespace) -> None:
    """Execute batch-ingest / batch-synthesize (all raw/*.md → notes/).

    DB-free: spend is accumulated from each call's cost_usd and the batch aborts
    before exceeding settings.run_cost_cap_usd (the T1-02 guardrail, now enforced
    in-memory rather than via the Turso agent_runs ledger).
    """
    from pkm.config import Settings
    from pkm.pipeline.ingest_note import run_note_ingest

    settings = Settings()
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    vault_root = args.vault or settings.vault_path
    if not vault_root:
        print("ERROR: VAULT_PATH is not set (use --vault or set VAULT_PATH).", file=sys.stderr)
        sys.exit(1)

    vault_root = Path(vault_root)
    raw_files = sorted((vault_root / "raw").glob("**/*.md"))

    client = _build_synthesis_client(settings)

    results, failed, spent, aborted = [], 0, 0.0, False
    for raw_file in raw_files:
        if spent >= settings.run_cost_cap_usd:
            aborted = True
            break
        try:
            r = run_note_ingest(
                client,
                vault_root=vault_root,
                raw_text=raw_file.read_text(encoding="utf-8"),
                raw_path=str(raw_file),
                model=settings.synthesis_model,
                notes_dirname=settings.notes_dirname,
                new_only=args.new_only,
            )
            spent += r.get("cost_usd", 0.0)
            results.append(r)
        except Exception as exc:  # noqa: BLE001 — isolate per-file failures
            failed += 1
            results.append({"raw_path": str(raw_file), "status": "error", "error": str(exc)})

    summary = {
        "total": len(raw_files),
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "skipped_empty": sum(1 for r in results if r.get("status") == "skipped_empty"),
        "failed": failed,
        "cost_usd": round(spent, 5),
        "cost_capped": aborted,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    if failed > 0:
        sys.exit(1)
