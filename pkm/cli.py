"""
pkm CLI entry point.

Entry point: pkm.cli:app (see pyproject.toml [project.scripts]).
app() is a zero-argument callable so the console_scripts entry point works.

Usage:
    pkm --help
    pkm ingest --help
    pkm ingest --new-only --raw <path>
    pkm batch-ingest --help
    pkm batch-ingest --new-only [--vault <path>]

Security (T-03-07, T-03-09, T-04-01):
    - --raw / --vault paths come from env/CLI, not untrusted web input.
    - Settings (including OPENAI_API_KEY) are never printed to stdout/stderr.
    - Only the result dict (ids, paths, counts) is printed as JSON.
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
        description="AI-assisted Personal Knowledge Management pipeline.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="subcommand")

    # -- ingest subcommand ----------------------------------------------------
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest a raw capture through the full PKM pipeline.",
        description=(
            "Run a raw Markdown file through Reader → Summarizer → "
            "ConceptExtractor → KGAgent → vault writer."
        ),
    )
    ingest_parser.add_argument(
        "--new-only",
        action="store_true",
        default=False,
        help=(
            "Skip sources that have already been fully processed "
            "(idempotent re-run protection). Recommended for normal use."
        ),
    )
    ingest_parser.add_argument(
        "--raw",
        metavar="PATH",
        required=True,
        help="Path to the raw Markdown capture file to ingest.",
    )

    # -- batch-ingest subcommand -----------------------------------------------
    batch_parser = subparsers.add_parser(
        "batch-ingest",
        help="Ingest all new raw/*.md files in a vault checkout.",
        description=(
            "Scan raw/**/*.md in the vault and ingest each file through the "
            "full pipeline. Re-running over an unchanged vault is a no-op "
            "(ORCH-07 idempotency)."
        ),
    )
    batch_parser.add_argument(
        "--new-only",
        action="store_true",
        default=False,
        help=(
            "Skip sources that have already been fully processed "
            "(idempotent re-run protection). Recommended for normal use."
        ),
    )
    batch_parser.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Path to the vault root directory. Defaults to VAULT_PATH from settings.",
    )

    # -- lint subcommand (Phase 7 / GUARD-01) ---------------------------------
    lint_parser = subparsers.add_parser(
        "lint",
        help="Lint the vault: broken wikilinks, orphans, missing provenance.",
        description=(
            "Run the nightly lint checks against the vault and append the result "
            "to log.md. Exits 1 if the vault is dirty (so the workflow step surfaces it)."
        ),
    )
    lint_parser.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Path to the vault root directory. Defaults to VAULT_PATH from settings.",
    )
    lint_parser.add_argument(
        "--no-log",
        action="store_true",
        default=False,
        help="Do not append the lint result to vault/log.md.",
    )

    # -- dashboard subcommand (Phase 7 / GUARD-02) ----------------------------
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Regenerate vault/dashboard.md from counter rows + lint counts.",
        description=(
            "Render dashboard.md with sources/claims/concepts/insights-accepted/"
            "actions-minutes/orphan-stale counts and write it to the vault."
        ),
    )
    dashboard_parser.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Path to the vault root directory. Defaults to VAULT_PATH from settings.",
    )
    dashboard_parser.add_argument(
        "--actions-minutes",
        type=int,
        default=None,
        help="Actions minutes used this month (rendered as N/A if omitted).",
    )

    # -- backfill-embeds subcommand (Phase 7 / GUARD-02) ----------------------
    backfill_parser = subparsers.add_parser(
        "backfill-embeds",
        help="Embed claims lacking a Vectorize embedding (idempotent).",
        description=(
            "Embed every claim without an embeddings_meta row into Cloudflare "
            "Vectorize. No-op without CF creds. Exits 1 if any claim fails to embed."
        ),
    )
    backfill_parser.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Path to the vault root directory. Defaults to VAULT_PATH from settings.",
    )
    backfill_parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of claims to embed per batch (default 100).",
    )

    return parser


def app() -> None:
    """PKM CLI entry point. Called by the `pkm` console script."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "ingest":
        _cmd_ingest(args)
    elif args.subcommand == "batch-ingest":
        _cmd_batch_ingest(args)
    elif args.subcommand == "lint":
        _cmd_lint(args)
    elif args.subcommand == "dashboard":
        _cmd_dashboard(args)
    elif args.subcommand == "backfill-embeds":
        _cmd_backfill_embeds(args)
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_ingest(args: argparse.Namespace) -> None:
    """Execute the ingest subcommand."""
    # Late imports: keep startup fast for --help; only load heavy deps when actually ingesting.
    from pkm.config import Settings
    from pkm.llm.client import LLMClient
    from pkm.pipeline.ingest import run_ingest
    from pkm.store.registry import connect

    # Load settings (from .env or environment variables)
    settings = Settings()

    # Validate required settings
    if not settings.openai_api_key:
        print(
            "ERROR: OPENAI_API_KEY is not set. "
            "Add it to your .env file or set the environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.vault_path:
        print(
            "ERROR: VAULT_PATH is not set. "
            "Add it to your .env file or set the VAULT_PATH environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Read the raw file
    raw_path_str = args.raw
    raw_file = Path(raw_path_str)
    if not raw_file.exists():
        print(f"ERROR: Raw file not found: {raw_path_str}", file=sys.stderr)
        sys.exit(1)

    raw_text = raw_file.read_text(encoding="utf-8")
    vault_root = Path(settings.vault_path)

    # Set up DB and LLM client
    conn = connect(settings)
    llm_client = LLMClient(conn, settings.openai_api_key, settings.openai_base_url)

    # Run the pipeline (CF creds optional: empty string = skip embed step)
    result = run_ingest(
        conn=conn,
        llm_client=llm_client,
        vault_root=vault_root,
        raw_text=raw_text,
        raw_path=raw_path_str,
        new_only=args.new_only,
        cf_account_id=settings.cf_account_id,
        cf_api_token=settings.cf_api_token,
    )

    # Print result as JSON (T-03-09: never echo Settings or api_key)
    print(json.dumps(result, indent=2))


def _cmd_batch_ingest(args: argparse.Namespace) -> None:
    """Execute the batch-ingest subcommand."""
    # Late imports: keep startup fast for --help; only load heavy deps when actually ingesting.
    from pkm.batch import batch_ingest
    from pkm.config import Settings
    from pkm.llm.client import LLMClient
    from pkm.store.registry import connect

    # Load settings (from .env or environment variables)
    settings = Settings()

    # Validate required settings (T-04-01: never print Settings or api_key)
    if not settings.openai_api_key:
        print(
            "ERROR: OPENAI_API_KEY is not set. "
            "Add it to your .env file or set the environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve vault root: CLI flag > settings
    vault_root = args.vault or settings.vault_path
    if not vault_root:
        print(
            "ERROR: VAULT_PATH is not set. "
            "Add it to your .env file, set the VAULT_PATH environment variable, "
            "or pass --vault PATH on the command line.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Set up DB and LLM client
    conn = connect(settings)
    llm_client = LLMClient(conn, settings.openai_api_key, settings.openai_base_url)

    # Run batch ingest (per-run cost/token cap from settings — T1-02 guardrail)
    result = batch_ingest(
        conn=conn,
        llm_client=llm_client,
        vault_root=Path(vault_root),
        new_only=args.new_only,
        run_cost_cap_usd=settings.run_cost_cap_usd,
        run_token_cap=settings.run_token_cap,
        cf_account_id=settings.cf_account_id,
        cf_api_token=settings.cf_api_token,
    )

    # Print result as JSON (T-03-09: never echo Settings or api_key)
    print(json.dumps(result, indent=2))

    # Exit non-zero if any file failed (so the workflow step surfaces failures)
    if result["failed"] > 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 7 subcommands: lint, dashboard, backfill-embeds
# ---------------------------------------------------------------------------


def _resolve_vault_root(args: argparse.Namespace, settings) -> str:
    """Return the vault root from the CLI flag or settings, or error out."""
    vault_root = args.vault or settings.vault_path
    if not vault_root:
        print(
            "ERROR: VAULT_PATH is not set. "
            "Add it to your .env file, set the VAULT_PATH environment variable, "
            "or pass --vault PATH on the command line.",
            file=sys.stderr,
        )
        sys.exit(1)
    return vault_root


def _cmd_lint(args: argparse.Namespace) -> None:
    """Execute the lint subcommand (GUARD-01)."""
    from pkm.config import Settings
    from pkm.lint import lint_vault
    from pkm.store.registry import connect

    settings = Settings()
    vault_root = _resolve_vault_root(args, settings)
    conn = connect(settings)

    report = lint_vault(conn, Path(vault_root), write_log=not args.no_log)

    # T-03-09: print only counts/flags — never Settings or api_key.
    print(json.dumps({
        "broken_wikilinks": len(report.broken_wikilinks),
        "orphans": len(report.orphans),
        "missing_provenance": len(report.missing_provenance),
        "is_clean": report.is_clean,
    }))

    # Exit 1 on a dirty vault so the workflow step surfaces it.
    if not report.is_clean:
        sys.exit(1)


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Execute the dashboard subcommand (GUARD-02)."""
    from pkm.config import Settings
    from pkm.dashboard import write_dashboard
    from pkm.store.registry import connect

    settings = Settings()
    vault_root = _resolve_vault_root(args, settings)
    conn = connect(settings)

    path = write_dashboard(conn, Path(vault_root), actions_minutes=args.actions_minutes)
    print(json.dumps({"dashboard": path}))


def _cmd_backfill_embeds(args: argparse.Namespace) -> None:
    """Execute the backfill-embeds subcommand (closes the Phase 6 embed gap)."""
    from pkm.config import Settings
    from pkm.retrieval.embed import backfill_embeds
    from pkm.store.registry import connect

    settings = Settings()
    # backfill_embeds reads claims + sources from the DB; it does not touch the
    # vault, so --vault is accepted but not required here.
    conn = connect(settings)

    result = backfill_embeds(
        conn,
        settings.cf_account_id,
        settings.cf_api_token,
        batch_size=args.batch_size,
    )
    print(json.dumps(result))

    # Mirror batch-ingest: exit non-zero if any claim failed to embed.
    if result["failed"] > 0:
        sys.exit(1)
