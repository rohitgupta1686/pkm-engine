"""Cloudflare Workers AI embedding + Vectorize upsert.

Called from pkm/pipeline/ingest.py (Step 6.5) after the main transaction commits.
Idempotent: claims that already have an embeddings_meta row are skipped.
Best-effort: the embed step never raises — failures are logged and counted so the
caller's wiki pages are never rolled back due to a CF API outage.

No-op guard: if cf_account_id or cf_api_token is empty, returns immediately with
zeros. This keeps all existing tests and local dev workflows working without
Cloudflare credentials.

API references:
  Workers AI: POST /accounts/{id}/ai/run/@cf/baai/bge-base-en-v1.5
              Body: {"text": "..."}
              Response: {"result": {"data": [[f, ...]], "shape": [1, 768]}, ...}

  Vectorize:  POST /accounts/{id}/vectorize/v2/indexes/{index}/upsert
              Content-Type: application/x-ndjson
              Body: {"id":"...", "values":[...], "metadata":{...}}\n  (one per line)
              Response: {"result": {"count": N}, "success": true, ...}
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CF_BASE = "https://api.cloudflare.com/client/v4/accounts"
_EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
_EMBED_DIM = 768
_EMBED_TIMEOUT = 30  # seconds per HTTP call


def _cf_embed(text: str, cf_account_id: str, cf_api_token: str) -> list[float]:
    """Call Workers AI REST API to get a 768-dim embedding for a single text string."""
    url = f"{_CF_BASE}/{cf_account_id}/ai/run/{_EMBED_MODEL}"
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_EMBED_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return data["result"]["data"][0]


def _cf_vectorize_upsert(
    vectors: list[dict],
    cf_account_id: str,
    cf_api_token: str,
    index_name: str,
) -> int:
    """Batch upsert vectors to Cloudflare Vectorize via NDJSON. Returns count upserted."""
    if not vectors:
        return 0
    url = f"{_CF_BASE}/{cf_account_id}/vectorize/v2/indexes/{index_name}/upsert"
    ndjson = "\n".join(json.dumps(v) for v in vectors).encode()
    req = urllib.request.Request(
        url,
        data=ndjson,
        headers={
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "application/x-ndjson",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_EMBED_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return data.get("result", {}).get("count", len(vectors))


def embed_claims(
    conn,
    claims: list[dict],
    source_id: str,
    raw_path: str,
    cf_account_id: str,
    cf_api_token: str,
    index_name: str = "pkm-claims",
) -> dict:
    """Embed a list of claims and upsert to Cloudflare Vectorize.

    Args:
        conn:           libsql connection (used to read/write embeddings_meta).
        claims:         List of dicts with at minimum keys "id" and "statement".
        source_id:      Source that produced these claims (stored in vector metadata).
        raw_path:       Vault-relative raw file path (stored in vector metadata for citations).
        cf_account_id:  Cloudflare account ID.
        cf_api_token:   CF API token with Workers AI:Read + Vectorize:Edit scopes.
        index_name:     Vectorize index name (default "pkm-claims").

    Returns:
        dict with keys:
            embedded  (int) — claims successfully embedded and upserted this call
            skipped   (int) — claims that already had an embeddings_meta row
            failed    (int) — claims whose embed or upsert call raised an error
    """
    if not cf_account_id or not cf_api_token:
        logger.debug("embed_claims: CF creds not set — skipping (no-op)")
        return {"embedded": 0, "skipped": 0, "failed": 0}

    if not claims:
        return {"embedded": 0, "skipped": 0, "failed": 0}

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Check which claims already have embeddings (idempotency).
    already: set[str] = set()
    for claim in claims:
        row = conn.execute(
            "SELECT object_id FROM embeddings_meta WHERE object_id = ?",
            (claim["id"],),
        ).fetchone()
        if row:
            already.add(claim["id"])

    to_embed = [c for c in claims if c["id"] not in already]
    skipped = len(already)
    failed = 0
    vectors_to_upsert: list[dict] = []

    # Embed each claim individually. Per-claim failures are non-fatal.
    for claim in to_embed:
        try:
            values = _cf_embed(claim["statement"], cf_account_id, cf_api_token)
            vectors_to_upsert.append({
                "id": claim["id"],
                "values": values,
                "metadata": {
                    "source_id": source_id,
                    "raw_path": raw_path,
                },
            })
        except Exception as exc:
            logger.warning(
                "embed_claims: failed to embed claim %s: %s", claim["id"], exc
            )
            failed += 1

    # Batch upsert to Vectorize. If this fails, all pending vectors are counted as failed.
    if vectors_to_upsert:
        try:
            _cf_vectorize_upsert(vectors_to_upsert, cf_account_id, cf_api_token, index_name)
        except Exception as exc:
            logger.warning("embed_claims: Vectorize upsert failed: %s", exc)
            failed += len(vectors_to_upsert)
            vectors_to_upsert = []

    # Write embeddings_meta rows only for claims that made it into Vectorize.
    embedded = 0
    for vec in vectors_to_upsert:
        conn.execute(
            "INSERT OR REPLACE INTO embeddings_meta "
            "(object_id, object_kind, collection, model, dim, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (vec["id"], "claim", index_name, _EMBED_MODEL, _EMBED_DIM, now_str),
        )
        embedded += 1

    if embedded > 0:
        conn.commit()

    logger.debug(
        "embed_claims: embedded=%d skipped=%d failed=%d source=%s",
        embedded, skipped, failed, source_id,
    )
    return {"embedded": embedded, "skipped": skipped, "failed": failed}
