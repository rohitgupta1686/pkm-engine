"""Safe, cached OCR enrichment for local source-note ingestion."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

IMAGE_EMBED_RE = re.compile(
    r"!\[\[(?P<wiki>[^\]]+?\.(?:png|jpe?g|webp|heic|heif))\]\]|!\[[^\]]*\]\((?P<md>[^)]+?\.(?:png|jpe?g|webp|heic|heif))\)",
    re.IGNORECASE,
)
OCR_OPEN = "<!-- ocr:"
MAX_IMAGE_BYTES = 18 * 1024 * 1024
MAX_EDGE = 1536
OCR_MAX_TOKENS = 4096


def resolve_embed(capture_path: Path, target: str) -> Path | None:
    """Resolve a sibling embed without allowing a source note to escape its folder."""
    parent = capture_path.parent.resolve()
    resolved = (parent / target.strip()).resolve()
    try:
        resolved.relative_to(parent)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def referenced_images(capture_path: Path, body: str) -> dict[str, Path]:
    """Return unique, resolved image embeds keyed by their literal embed target."""
    found: dict[str, Path] = {}
    for match in IMAGE_EMBED_RE.finditer(body):
        target = (match.group("wiki") or match.group("md") or "").strip()
        path = resolve_embed(capture_path, target)
        if path is not None:
            found.setdefault(target, path)
    return found


def image_hashes(capture_path: Path, body: str) -> dict[str, str]:
    """Hash referenced readable image bytes; unreadable/missing files are omitted."""
    hashes: dict[str, str] = {}
    for target, path in referenced_images(capture_path, body).items():
        try:
            hashes[target] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            logger.warning("OCR could not read image %s", path)
    return hashes


def _load_cache(cache_path: Path) -> dict:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, cache_path)


def _image_data_uri(path: Path) -> tuple[str, str]:
    """Validate and downscale an image, returning a JPEG data URI and SHA."""
    raw = path.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 18 MB inline safety limit")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            image.thumbnail((MAX_EDGE, MAX_EDGE))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"invalid or incomplete image: {exc}") from exc
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", digest


def enrich_body(
    body: str, capture_path: Path, ocr_client, model: str, cache_path: Path,
    *, remaining_cost_usd: float | None = None,
) -> tuple[str, dict]:
    """Append cached/fresh transcripts after image embeds, without altering source files."""
    cache = _load_cache(cache_path)
    stats = {"images_transcribed": 0, "cached": 0, "failed": 0, "skipped_too_large": 0,
             "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}

    def replace(match: re.Match) -> str:
        line = match.group(0)
        if OCR_OPEN in body[match.end(): match.end() + 20]:
            return line
        target = (match.group("wiki") or match.group("md") or "").strip()
        path = resolve_embed(capture_path, target)
        if path is None:
            stats["failed"] += 1
            return line
        try:
            data_uri, digest = _image_data_uri(path)
        except ValueError as exc:
            if "18 MB" in str(exc):
                stats["skipped_too_large"] += 1
            else:
                stats["failed"] += 1
            logger.warning("OCR skipped %s: %s", path.name, exc)
            return line
        cached = cache.get(target, {})
        text = cached.get("text") if cached.get("img_sha") == digest else None
        if text is not None:
            stats["cached"] += 1
        else:
            if remaining_cost_usd is not None and stats["cost_usd"] >= remaining_cost_usd:
                stats["failed"] += 1
                logger.warning("OCR cost cap reached before %s", path.name)
                return line
            prompt = (Path(__file__).parents[1] / "prompts" / "ocr.v1.md").read_text(encoding="utf-8")
            try:
                result = ocr_client.call(
                    agent_name="ocr", model=model, prompt_version="ocr-v1",
                    messages=[{"role": "system", "content": prompt}, {"role": "user", "content": [{"type": "text", "text": "Transcribe this image."}, {"type": "image_url", "image_url": {"url": data_uri}}]}],
                    input_text=digest, max_tokens=OCR_MAX_TOKENS,
                )
                text = str(result["result"]).strip()
                stats["tokens_in"] += result.get("tokens_in", 0)
                stats["tokens_out"] += result.get("tokens_out", 0)
                stats["cost_usd"] += result.get("cost_usd", 0.0)
                cache[target] = {"img_sha": digest, "text": text,
                                 "text_sha": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}
                _save_cache(cache_path, cache)
                stats["images_transcribed"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("OCR failed for %s: %s", path.name, exc)
                stats["failed"] += 1
                return line
        if text == "[no legible text]":
            return line
        return f"{line}\n<!-- ocr:{target} -->\n> (transcribed) {text.replace(chr(10), chr(10) + '> ')}\n<!-- /ocr -->"

    enriched = IMAGE_EMBED_RE.sub(replace, body)
    stats["cost_usd"] = round(stats["cost_usd"], 5)
    return enriched, stats
