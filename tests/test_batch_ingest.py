"""Unit tests for the Batch-API article-ingest path.

Dependency-light by design: a FakeBatchClient stands in for the OpenAI client's
Batch methods (build_batch_request / submit_batch / poll_batch / collect_batch),
so these run without the SDK or any network. Runnable under pytest or directly:
    python3 tests/test_batch_ingest.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

# Allow `python3 tests/test_batch_ingest.py` from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pkm.config import Settings  # noqa: E402
from pkm.llm.models import GLM52, GPT55  # noqa: E402
from pkm.llm.pricing import compute_cost  # noqa: E402
from pkm.pipeline.batch_ingest import prepare_requests, run_batch_ingest  # noqa: E402
from pkm.store.notes import list_note_slugs  # noqa: E402

MODEL = GPT55


def _raw(title: str, body: str) -> str:
    return (
        "---\n"
        f'title: "{title}"\n'
        "type: Article\n"
        'url: "https://example.com/x"\n'
        "date_saved: 2026-07-09T09:00:00.000Z\n"
        "---\n"
        f"{body}\n"
    )


BODY = (
    "This is a substantial article body well over the MIN_BODY_CHARS guard so it is "
    "worth synthesizing. It goes on at length about its subject with plenty of "
    "detail for a synthesizer to work from, covering context and consequences."
)
RAW_A = _raw("Alpha article about batching", BODY)
RAW_B = _raw("Beta article about pricing", BODY)
# Body-less stub (front matter only) — below MIN_BODY_CHARS, must be skipped.
RAW_STUB = _raw("Paywalled stub", "")

NOTE_MD = "---\ntitle: x\nreviewed: false\n---\n\n# x\n\n> [!abstract] Thesis\n> A note.\n"


class FakeBatchClient:
    """Fake of LLMClient's Batch API seam.

    Records the requests it was handed and, on collect, returns a canned note for
    each — unless configured to fail the whole batch (``status``) or error specific
    custom_ids (``errors``).
    """

    def __init__(self, *, status="completed", errors=None, result=NOTE_MD):
        self.submitted: list[dict] = []
        self._status = status
        self._errors = set(errors or [])
        self._result = result
        self.poll_calls = 0

    def build_batch_request(self, custom_id, model, messages, max_tokens=32768, output_schema=None):
        return {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {"model": model, "max_completion_tokens": max_tokens, "messages": messages},
        }

    def submit_batch(self, requests):
        self.submitted = list(requests)
        return "batch-fake-123"

    def poll_batch(self, batch_id, interval, timeout):
        self.poll_calls += 1
        return SimpleNamespace(
            id=batch_id, status=self._status,
            output_file_id="out-file", error_file_id=None,
        )

    def collect_batch(self, batch):
        out = {}
        for r in self.submitted:
            cid = r["custom_id"]
            if cid in self._errors:
                out[cid] = {"error": "finish_reason=length"}
            else:
                out[cid] = {
                    "text": self._result, "tokens_in": 1234,
                    "tokens_out": 567, "cached_tokens": 0,
                }
        return out


def _write_raw(vault: Path, name: str, text: str) -> Path:
    raw_dir = vault / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    p = raw_dir / name
    p.write_text(text, encoding="utf-8")
    return p


# --- prepare_requests -------------------------------------------------------

def test_prepare_skips_empty_and_existing_and_builds_requests():
    client = FakeBatchClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        a = _write_raw(vault, "a.md", RAW_A)
        b = _write_raw(vault, "b.md", RAW_B)
        stub = _write_raw(vault, "stub.md", RAW_STUB)
        # Pre-existing note for A → skipped under new_only.
        (vault / "notes").mkdir()
        (vault / "notes" / "alpha-article-about-batching.md").write_text("old\n")

        requests, meta, prelim = prepare_requests(
            client, vault, [a, b, stub], MODEL, new_only=True, cost_cap=1.0,
        )

        # Only B produces a request; A skipped (exists), stub skipped_empty.
        assert len(requests) == 1
        assert requests[0]["custom_id"] == "0"
        assert meta["0"]["slug"] == "beta-article-about-pricing"
        statuses = sorted(r["status"] for r in prelim)
        assert statuses == ["skipped", "skipped_empty"]


def test_prepare_cost_cap_defers_remaining_sources():
    client = FakeBatchClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        a = _write_raw(vault, "a.md", RAW_A)
        b = _write_raw(vault, "b.md", RAW_B)

        # Tiny cap: the first source is always admitted, the second is deferred.
        requests, meta, prelim = prepare_requests(
            client, vault, [a, b], MODEL, new_only=False, cost_cap=0.0001,
        )

        assert len(requests) == 1
        deferred = [r for r in prelim if r["status"] == "deferred"]
        assert len(deferred) == 1


# --- run_batch_ingest -------------------------------------------------------

def test_run_batch_ingest_writes_notes_and_reports_batch_cost():
    client = FakeBatchClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        _write_raw(vault, "a.md", RAW_A)
        _write_raw(vault, "b.md", RAW_B)

        summary = run_batch_ingest(client, vault_root=vault, model=MODEL)

        assert summary["ok"] == 2
        assert summary["failed"] == 0
        assert client.poll_calls == 1
        assert sorted(list_note_slugs(vault)) == [
            "alpha-article-about-batching", "beta-article-about-pricing",
        ]
        # cost_usd is the batch (discounted) rate, not the sync rate.
        expected = 2 * compute_cost(MODEL, 1234, 0, 567, batch=True)
        assert abs(summary["cost_usd"] - round(expected, 5)) < 1e-6


def test_run_batch_ingest_no_requests_makes_no_batch():
    client = FakeBatchClient()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        _write_raw(vault, "stub.md", RAW_STUB)  # only a body-less stub

        summary = run_batch_ingest(client, vault_root=vault, model=MODEL)

        assert summary["ok"] == 0
        assert summary["skipped_empty"] == 1
        assert client.submitted == []      # nothing submitted
        assert client.poll_calls == 0      # never polled


def test_run_batch_ingest_failed_batch_writes_nothing():
    client = FakeBatchClient(status="expired")
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        _write_raw(vault, "a.md", RAW_A)

        summary = run_batch_ingest(client, vault_root=vault, model=MODEL)

        assert summary["ok"] == 0
        assert summary["failed"] == 1
        assert list_note_slugs(vault) == []  # no note written on batch failure


def test_run_batch_ingest_errored_request_is_not_written():
    # The single request errors (e.g. hit the output-token ceiling).
    client = FakeBatchClient(errors={"0"})
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        _write_raw(vault, "a.md", RAW_A)

        summary = run_batch_ingest(client, vault_root=vault, model=MODEL)

        assert summary["ok"] == 0
        assert summary["failed"] == 1
        assert summary["results"][0]["status"] == "error"
        assert list_note_slugs(vault) == []


# --- pricing + config -------------------------------------------------------

def test_compute_cost_gpt55_batch_is_half_of_sync():
    sync = compute_cost("gpt-5.5", 1_000_000, 0, 1_000_000)
    assert sync == 5.00 + 30.00  # $5 input + $30 output per 1M
    batch = compute_cost("gpt-5.5", 1_000_000, 0, 1_000_000, batch=True)
    assert abs(batch - sync * 0.5) < 1e-9


def test_default_synthesis_model_is_glm52():
    assert Settings().synthesis_model == GLM52


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
