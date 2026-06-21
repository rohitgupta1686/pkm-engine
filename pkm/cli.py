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
