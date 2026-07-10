#!/usr/bin/env python3
"""Compare two models on the single-call synthesis prompt, head to head.

Runs the SAME captures through each model with the SAME prompt and existing-slug
list, then writes paired notes plus a cost/latency report so you can decide
which model's quality/cost tradeoff is best for the note style.

Generation needs real API access, so run this where OPENAI_API_KEY is set (it
can use OPENAI_BASE_URL too, e.g. Z.AI or a local proxy). Judging can then happen
anywhere — eyeball the paired notes in Obsidian, or have Claude Code read them
and score blind.

Usage:
    pip install -e .
    export OPENAI_API_KEY=sk-...
    export VAULT_PATH=/abs/path/to/pkm-vault

    # default: a representative sample of substantial captures, both models
    python3 scripts/compare_models.py

    # explicit captures + models + blind output for unbiased judging
    python3 scripts/compare_models.py \
        --raw "$VAULT_PATH/raw/economist-com__anthropic-...md" \
        --raw "$VAULT_PATH/raw/the-ken-com__...md" \
        --models glm-5.2 gpt-5.4 \
        --blind

Outputs (under --out, default <vault>/_model_compare/):
    <model>/<slug>.md         one note per (model, capture)
    blind/<slug>__A.md, __B.md (with --blind) + KEY.json mapping A/B → model
    COMPARISON.md             tokens, cost, latency table + judging rubric
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Run from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pkm.config import Settings  # noqa: E402
from pkm.llm.client import LLMClient  # noqa: E402
from pkm.llm.pricing import PRICING, compute_cost  # noqa: E402
from pkm.pipeline.synthesize import synthesize_note  # noqa: E402
from pkm.store.notes import list_note_slugs, slug_for_raw  # noqa: E402

# NOTE: we deliberately do NOT import pkm.store.registry — it pulls in
# libsql-experimental (a Rust extension with no wheel on bleeding-edge Pythons).
# The eval only needs the LLM client's agent_runs cache table, which the stdlib
# sqlite3 module serves fine. This keeps the comparison runnable without libsql.

DEFAULT_MODELS = ["glm-5.2", "gpt-5.4"]

# Minimal agent_runs schema — the exact columns BaseLLMClient._write_run / _check_cache
# read and write. (Mirrors migrations/sqlite/004; no other tables are touched here.)
_AGENT_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id           TEXT PRIMARY KEY,
    agent        TEXT,
    source_id    TEXT,
    input_hash   TEXT,
    model        TEXT,
    tokens_in    INTEGER,
    tokens_out   INTEGER,
    cost_usd     REAL,
    status       TEXT,
    error        TEXT,
    started_at   TEXT,
    finished_at  TEXT,
    output_json  TEXT
);
"""


def _make_eval_conn() -> sqlite3.Connection:
    """A throwaway stdlib-sqlite3 connection with just the agent_runs cache table.

    Fresh per run (temp file) so every model call is a live measurement and the
    production cache is never touched. Avoids the libsql native dependency.
    """
    db = Path(tempfile.mkdtemp(prefix="pkm-eval-")) / "eval.db"
    conn = sqlite3.connect(str(db))
    conn.execute(_AGENT_RUNS_DDL)
    conn.commit()
    return conn

# Substantial captures only (the body-less paywall stubs aren't worth comparing).
DEFAULT_SAMPLE_SUBSTRINGS = [
    "anthropic-s-astonishing",
    "america-s-carmakers",
    "tata-adani-couldn-t-crack-super-apps",
    "the-jio-ipo-explained",
]


def _min_body_chars(text: str) -> int:
    """Chars after the front matter — used to skip body-less captures."""
    parts = text.split("---", 2)
    return len(parts[2].strip()) if len(parts) == 3 else len(text.strip())


def _resolve_raw_files(args, vault: Path) -> list[Path]:
    if args.raw:
        return [Path(r) for r in args.raw]
    raws = sorted((vault / "raw").glob("**/*.md"))
    if args.all:
        return [r for r in raws if _min_body_chars(r.read_text(encoding="utf-8")) > 500]
    # default: the representative sample, matched by substring
    picked = [r for r in raws if any(s in r.name for s in DEFAULT_SAMPLE_SUBSTRINGS)]
    return picked or [r for r in raws if _min_body_chars(r.read_text(encoding="utf-8")) > 500][:4]


def _blind_order(slug: str, models: list[str]) -> list[str]:
    """Deterministic but slug-dependent A/B order, so it isn't always model0=A."""
    return list(reversed(models)) if (sum(map(ord, slug)) % 2) else list(models)


def main() -> None:
    ap = argparse.ArgumentParser(description="Head-to-head model comparison for note synthesis.")
    ap.add_argument("--vault", default=None, help="Vault root (default: VAULT_PATH).")
    ap.add_argument("--raw", action="append", help="Explicit raw capture path (repeatable).")
    ap.add_argument("--all", action="store_true", help="Use all non-stub captures, not the sample.")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, help="Model ids to compare.")
    ap.add_argument("--out", default=None, help="Output dir (default: <vault>/_model_compare).")
    ap.add_argument("--blind", action="store_true", help="Also emit A/B blind files + KEY.json.")
    args = ap.parse_args()

    settings = Settings()
    if not settings.openai_api_key:
        sys.exit("ERROR: OPENAI_API_KEY not set.")
    vault = Path(args.vault or settings.vault_path)
    if not vault or not vault.exists():
        sys.exit("ERROR: vault not found (set --vault or VAULT_PATH).")

    for m in args.models:
        if m not in PRICING:
            sys.exit(f"ERROR: no pricing for {m!r} — add it to pkm/llm/pricing.py first.")

    out = Path(args.out) if args.out else vault / "_model_compare"
    out.mkdir(parents=True, exist_ok=True)

    raw_files = _resolve_raw_files(args, vault)
    if not raw_files:
        sys.exit("ERROR: no captures resolved.")

    # Fresh stdlib-sqlite3 eval DB (no libsql) — every call is a live measurement.
    conn = _make_eval_conn()
    client = LLMClient(conn, settings.openai_api_key, settings.openai_base_url)

    # Same linkable-slug list for both models, for a fair "Connects to" comparison.
    existing = list_note_slugs(vault)

    rows = []
    for raw_file in raw_files:
        raw_text = raw_file.read_text(encoding="utf-8")
        slug = slug_for_raw(raw_text)
        linkable = [s for s in existing if s != slug]
        per_model_text = {}
        for model in args.models:
            t0 = time.monotonic()
            res = synthesize_note(
                client, raw_text=raw_text, existing_titles=linkable,
                source_id=f"{slug}__{model}", model=model,
            )
            dt = time.monotonic() - t0
            note = res.get("result") or ""
            tin = res.get("tokens_in", 0)
            tout = res.get("tokens_out", 0)
            cost = compute_cost(model, tin, 0, tout)  # cached=0 → upper bound
            per_model_text[model] = note

            mdir = out / model.replace("/", "_")
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / f"{slug}.md").write_text(note.rstrip("\n") + "\n", encoding="utf-8")

            rows.append({
                "slug": slug, "model": model, "tokens_in": tin, "tokens_out": tout,
                "cost_usd": round(cost, 5), "latency_s": round(dt, 2),
                "note_chars": len(note),
            })
            print(f"  {model:28s} {slug:45s} {tout:>5}tok  ${cost:.4f}  {dt:.1f}s")

        if args.blind:
            bdir = out / "blind"
            bdir.mkdir(parents=True, exist_ok=True)
            order = _blind_order(slug, args.models)
            key = {}
            for label, model in zip("AB", order):
                (bdir / f"{slug}__{label}.md").write_text(
                    per_model_text[model].rstrip("\n") + "\n", encoding="utf-8")
                key[f"{slug}__{label}"] = model
            keypath = bdir / "KEY.json"
            existing_key = json.loads(keypath.read_text()) if keypath.exists() else {}
            existing_key.update(key)
            keypath.write_text(json.dumps(existing_key, indent=2))

    _write_report(out, rows, args.models)
    print(f"\nWrote paired notes + COMPARISON.md under {out}")
    if args.blind:
        print("Blind A/B set in blind/ (mapping in blind/KEY.json — don't peek until after judging).")


def _write_report(out: Path, rows: list[dict], models: list[str]) -> None:
    lines = ["# Model comparison — single-call synthesis\n"]
    lines.append("| Capture | Model | out tok | cost (USD)* | latency | chars |")
    lines.append("|---|---|--:|--:|--:|--:|")
    for r in rows:
        lines.append(
            f"| {r['slug']} | {r['model']} | {r['tokens_out']} | "
            f"${r['cost_usd']:.4f} | {r['latency_s']}s | {r['note_chars']} |"
        )
    lines.append("\n## Totals per model\n")
    lines.append("| Model | notes | total cost* | avg cost/note | avg latency |")
    lines.append("|---|--:|--:|--:|--:|")
    for m in models:
        mr = [r for r in rows if r["model"] == m]
        if not mr:
            continue
        tc = sum(r["cost_usd"] for r in mr)
        al = sum(r["latency_s"] for r in mr) / len(mr)
        lines.append(f"| {m} | {len(mr)} | ${tc:.4f} | ${tc/len(mr):.4f} | {al:.1f}s |")
    lines.append("\n*cost is an upper bound — computed with cached_tokens=0 (no prompt-cache discount).\n")
    lines.append(_RUBRIC)
    (out / "COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")


_RUBRIC = """\
## How to judge (blind)

Open the paired notes (or the `blind/` A/B set) side by side in Obsidian, or ask
Claude Code to read them and score blind. Rate each note 1–5 on:

1. **Faithfulness** — specifics (names, numbers, dates, mechanisms) correct; nothing fabricated.
2. **Scannability** — thesis + TL;DR + short bold-led beats; no paragraph over 2 sentences.
3. **Visual quality** — the ONE visual is apt and valid (Mermaid renders, bars same-unit), or correctly omitted.
4. **Wildcard** — earned, well-framed, varied (not always "Zoom out"); skipped when unwarranted.
5. **Links** — `Connects to` uses only real slugs, genuine connections, no self-link.

## The decision

Full model costs ~10x the mini per note. It's worth it ONLY if its quality lead is
large and consistent on 1–2 (faithfulness, scannability) — the dimensions that make
the note re-readable instead of the original. If the mini is within ~0.5 pts on those,
pick the mini: at ~$0.0065/note it buys ~10x more notes inside the $5–10/mo budget.
"""


if __name__ == "__main__":
    main()
