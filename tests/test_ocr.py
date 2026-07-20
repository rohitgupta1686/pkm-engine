"""Tests for the local, opt-in source-note OCR pre-pass."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PIL import Image

from pkm.ingest.ocr import enrich_body, referenced_images, resolve_embed
from pkm.pipeline.ingest_source_notes import run_source_notes_ingest


class FakeOCRClient:
    def __init__(self, *, text: str = "Visible page text."):
        self.calls: list[dict] = []
        self.text = text

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return {"result": self.text, "tokens_in": 11, "tokens_out": 7, "cost_usd": 0.001}


class FakeSynthesisClient:
    def __init__(self):
        self.calls: list[dict] = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "result": "---\ntitle: x\ntype: book\nreviewed: false\n---\n\n# x\n\nbody\n",
            "tokens_in": 20, "tokens_out": 10, "cost_usd": 0.01, "cached": False,
        }


def _image(folder: Path, name: str = "page 1.jpg", color="white") -> Path:
    path = folder / name
    Image.new("RGB", (200, 100), color=color).save(path, "JPEG")
    old = time.time() - 3600
    os.utime(path, (old, old))
    return path


def test_resolve_embed_allows_sibling_and_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        capture = root / "note.md"
        capture.write_text("body")
        image = _image(root)
        assert resolve_embed(capture, "page 1.jpg") == image.resolve()
        outside = root.parent / "outside.jpg"
        Image.new("RGB", (1, 1)).save(outside)
        try:
            assert resolve_embed(capture, "../outside.jpg") is None
        finally:
            outside.unlink(missing_ok=True)


def test_referenced_images_only_returns_image_embeds():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        capture = root / "note.md"
        capture.write_text("body")
        _image(root)
        found = referenced_images(capture, "![[page 1.jpg]]\n[[other.md]]\n![](missing.png)")
        assert list(found) == ["page 1.jpg"]


def test_enrich_body_preserves_embed_and_uses_cache():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        capture = root / "note.md"
        capture.write_text("![[page 1.jpg]]\n")
        _image(root)
        client = FakeOCRClient()
        cache = root / ".ocr-cache" / "note.json"
        enriched, stats = enrich_body(capture.read_text(), capture, client, "gemini-3-flash-preview", cache)
        assert "![[page 1.jpg]]" in enriched
        assert "<!-- ocr:page 1.jpg -->" in enriched
        assert "> (transcribed) Visible page text." in enriched
        assert stats["images_transcribed"] == 1
        assert len(client.calls) == 1
        assert client.calls[0]["max_tokens"] == 4096

        enriched_again, cached = enrich_body(capture.read_text(), capture, client, "gemini-3-flash-preview", cache)
        assert enriched_again == enriched
        assert cached["cached"] == 1
        assert len(client.calls) == 1


def test_enrich_body_does_not_double_insert_existing_block():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        capture = root / "note.md"
        original = "![[page 1.jpg]]\n<!-- ocr:page 1.jpg -->\n> (transcribed) done\n<!-- /ocr -->\n"
        capture.write_text(original)
        _image(root)
        enriched, stats = enrich_body(original, capture, FakeOCRClient(), "gemini-3-flash-preview", root / "cache.json")
        assert enriched == original
        assert stats["images_transcribed"] == 0


def test_ocr_ingest_never_mutates_source_and_reacts_to_image_change():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sources, vault = root / "sources", root / "vault"
        sources.mkdir()
        capture = sources / "book.md"
        source_text = "---\ntitle: Book\n---\n![[page 1.jpg]]\n"
        capture.write_text(source_text)
        old = time.time() - 3600
        os.utime(capture, (old, old))
        image = _image(sources)
        before = (capture.read_bytes(), capture.stat().st_mtime_ns)
        synthesis, ocr = FakeSynthesisClient(), FakeOCRClient()

        first = run_source_notes_ingest(
            synthesis, sources, vault, "gemini-3-flash-preview", ocr_client=ocr,
            ocr_model="gemini-3-flash-preview", ocr_enabled=True,
        )
        assert first["synthesized"] == 1
        assert first["ocr"]["images_transcribed"] == 1
        assert (capture.read_bytes(), capture.stat().st_mtime_ns) == before

        # The same image is a no-op; an unrelated file is not considered.
        _image(sources, "unrelated.jpg", color="blue")
        second = run_source_notes_ingest(
            synthesis, sources, vault, "gemini-3-flash-preview", ocr_client=ocr,
            ocr_model="gemini-3-flash-preview", ocr_enabled=True,
        )
        assert second["unchanged"] == 1
        assert len(ocr.calls) == 1

        _image(sources, "page 1.jpg", color="black")
        third = run_source_notes_ingest(
            synthesis, sources, vault, "gemini-3-flash-preview", ocr_client=ocr,
            ocr_model="gemini-3-flash-preview", ocr_enabled=True,
        )
        assert third["synthesized"] == 1
        assert third["results"][0]["change"] == "changed"
        assert len(ocr.calls) == 2


def test_force_ocr_establishes_baseline_for_one_legacy_source():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sources, vault = root / "sources", root / "vault"
        sources.mkdir()
        capture = sources / "book.md"
        capture.write_text("---\ntitle: Book\n---\n![[page 1.jpg]]\n")
        old = time.time() - 3600
        os.utime(capture, (old, old))
        _image(sources)
        synthesis, ocr = FakeSynthesisClient(), FakeOCRClient()
        # First ingest establishes legacy state without OCR.
        run_source_notes_ingest(synthesis, sources, vault, "glm-5.2")
        # The targeted force option establishes the OCR/image-hash baseline.
        result = run_source_notes_ingest(
            synthesis, sources, vault, "glm-5.2", ocr_client=ocr,
            ocr_model="gemini-3-flash-preview", ocr_enabled=True,
            source_paths=[capture], force_ocr=True,
        )
        assert result["synthesized"] == 1
        assert result["ocr"]["images_transcribed"] == 1
