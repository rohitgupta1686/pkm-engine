"""Gemini (Google AI Studio) implementation of the LLM client.

Native Gemini REST transport over httpx. Cache / agent_runs / retry
orchestration is inherited from BaseLLMClient — this module only implements the
provider seam plus the Gemini-specific behaviors the user asked for:

  - list the available Gemini *Flash* models at startup (logged), and
  - try them in DECREASING version order (3.5 → 3.1 → 3 → 2.5 …), falling back
    to the next model when a higher one fails to return usable output. Full
    `flash` models are preferred; `flash-lite` is used only as a last resort.

Free tier → `_cost` returns 0.0. Rate-limit (429) / 5xx are retried with
exponential backoff; a model that still fails drops to the next in the chain.
"""
import logging
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel

from pkm.llm.base_client import BaseLLMClient, Generation
from pkm.llm.client import _inline_refs  # shared $ref/$defs flattener

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Sentinel logical model id meaning "list Flash models and fall back by version".
# Used as the cache-key model so the concrete model the fallback picks does not
# bust the cache mid-corpus (the concrete model is recorded in agent_runs.model).
GEMINI_AUTO = "gemini-flash-auto"

_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
# JSON Schema keywords Gemini's responseSchema subset does not accept.
_UNSUPPORTED_GEMINI_KEYS = ("$schema", "title", "default", "examples", "additionalProperties")


def _to_gemini_schema(schema: dict) -> dict:
    """Transform a pydantic ``model_json_schema()`` into Gemini's responseSchema.

    Gemini accepts a JSON-Schema subset (type/properties/required/items/enum/
    anyOf/nullable/min*/max*). We inline ``$ref``/``$defs`` (deeply nested but
    self-contained — Gemini does not resolve our local refs) and strip the few
    keywords it rejects. pydantic's nullable ``anyOf:[{...},{type:null}]`` and
    enums pass through unchanged.
    """
    out = _inline_refs(schema)
    _strip_gemini_unsupported(out)
    return out


def _strip_gemini_unsupported(node: Any) -> None:
    if isinstance(node, dict):
        for bad in _UNSUPPORTED_GEMINI_KEYS:
            node.pop(bad, None)
        for value in node.values():
            _strip_gemini_unsupported(value)
    elif isinstance(node, list):
        for item in node:
            _strip_gemini_unsupported(item)


def _parse_flash_version(model_id: str) -> float | None:
    """Extract the numeric version from a Gemini Flash id, else None.

    'gemini-3.5-flash' -> 3.5, 'gemini-3-flash-preview' -> 3.0,
    'gemini-2.5-flash-lite' -> 2.5. Non-flash ids return None.
    """
    m = re.search(r"gemini-(\d+(?:\.\d+)?)-flash", model_id)
    return float(m.group(1)) if m else None


# Non-text Flash variants that also advertise generateContent but cannot do the
# pipeline's text synthesis (image generation, TTS, audio, vision, live/streaming).
_NON_TEXT_MARKERS = ("image", "tts", "audio", "vision", "embedding", "live")


def order_flash_models(model_ids: list[str]) -> list[str]:
    """Return the *text* Flash models ordered best-first for the fallback chain.

    Drops non-flash ids and non-text variants (image/tts/audio/…). Sort key:
    full-flash before flash-lite; then version descending; then stable before
    preview.
    """
    flash = [
        (mid, v)
        for mid in model_ids
        if not any(marker in mid for marker in _NON_TEXT_MARKERS)
        and (v := _parse_flash_version(mid)) is not None
    ]

    def key(item: tuple[str, float]) -> tuple[int, float, int]:
        mid, version = item
        is_lite = 1 if "flash-lite" in mid else 0
        is_preview = 1 if "preview" in mid else 0
        return (is_lite, -version, is_preview)

    return [mid for mid, _ in sorted(flash, key=key)]


class GeminiClient(BaseLLMClient):
    """Gemini-backed LLM client (free tier). See module docstring."""

    def __init__(self, conn, api_key: str, model: str = GEMINI_AUTO) -> None:
        super().__init__(conn)
        if not api_key:
            raise ValueError(
                "GeminiClient requires an API key. Create one at "
                "https://aistudio.google.com/apikey and set GEMINI_API_KEY."
            )
        self._api_key = api_key
        self._configured_model = model
        self._http = httpx.Client(timeout=_HTTP_TIMEOUT)
        self._ordered_cache: list[str] | None = None

    # -- model discovery ---------------------------------------------------
    def list_models(self) -> list[str]:
        """List available Gemini Flash models, ordered best-first (cached)."""
        if self._ordered_cache is not None:
            return self._ordered_cache

        names: list[str] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 200}
            if page_token:
                params["pageToken"] = page_token
            resp = self._http.get(
                f"{GEMINI_API_BASE}/models",
                params=params,
                headers={"x-goog-api-key": self._api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("models", []):
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" not in methods:
                    continue
                name = m.get("name", "")
                bare = name.split("/", 1)[-1]  # "models/gemini-3.5-flash" -> id
                if "flash" in bare:
                    names.append(bare)
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        self._ordered_cache = order_flash_models(names)
        return self._ordered_cache

    def _candidate_models(self, model: str) -> list[str]:
        """Resolve the model arg into an ordered fallback chain."""
        if model == GEMINI_AUTO:
            ordered = self.list_models()
            if not ordered:
                raise RuntimeError(
                    "No Gemini Flash models with generateContent are available "
                    "for this API key."
                )
            return ordered
        return [model]

    # -- request/response translation -------------------------------------
    @staticmethod
    def _to_gemini_contents(messages: list[dict]) -> tuple[list[dict], dict | None]:
        """Translate OpenAI messages -> (contents, systemInstruction)."""
        contents: list[dict] = []
        system_parts: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            text = msg.get("content") or ""
            if role == "system":
                system_parts.append({"text": text})
            else:
                gem_role = "model" if role == "assistant" else "user"
                contents.append({"role": gem_role, "parts": [{"text": text}]})
        system_instruction = {"parts": system_parts} if system_parts else None
        return contents, system_instruction

    def _post_generate(self, model: str, body: dict) -> dict:
        """POST :generateContent with backoff on 429/5xx. Returns parsed JSON."""
        url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
        for attempt in range(3):
            resp = self._http.post(
                url, json=body, headers={"x-goog-api-key": self._api_key}
            )
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                logger.warning(
                    "Gemini %s returned %d; backing off (attempt %d)",
                    model, resp.status_code, attempt + 1,
                )
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        # Unreachable: last attempt either returns or raise_for_status raises.
        raise RuntimeError("Gemini request exhausted retries")  # pragma: no cover

    @staticmethod
    def _parse_response(data: dict, model: str) -> Generation:
        """Normalize a generateContent response into a Generation."""
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini {model}: response had no candidates")
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        raw_finish = cand.get("finishReason", "STOP")
        finish = "length" if raw_finish == "MAX_TOKENS" else (
            "stop" if raw_finish == "STOP" else str(raw_finish).lower()
        )
        if not text and finish not in ("stop", "length"):
            # SAFETY / RECITATION / etc. with no text — treat as a failure so the
            # caller can fall back to the next model.
            raise RuntimeError(f"Gemini {model}: no text (finishReason={raw_finish})")
        usage = data.get("usageMetadata") or {}
        return Generation(
            text=text,
            finish_reason=finish,
            tokens_in=int(usage.get("promptTokenCount", 0) or 0),
            tokens_out=int(usage.get("candidatesTokenCount", 0) or 0),
            cached_tokens=0,
            model=model,
        )

    # -- provider seam -----------------------------------------------------
    def _cost(self, model: str, tokens_in: int, cached_tokens: int, tokens_out: int) -> float:
        return 0.0  # Google AI Studio free tier

    def _generate(
        self,
        model: str,
        messages: list[dict],
        output_schema: type[BaseModel] | None,
        max_tokens: int,
    ) -> Generation:
        contents, system_instruction = self._to_gemini_contents(messages)
        gen_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if output_schema is not None:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseSchema"] = _to_gemini_schema(output_schema.model_json_schema())

        body: dict[str, Any] = {"contents": contents, "generationConfig": gen_config}
        if system_instruction:
            body["systemInstruction"] = system_instruction

        last_exc: Exception | None = None
        for candidate in self._candidate_models(model):
            try:
                data = self._post_generate(candidate, body)
                return self._parse_response(data, candidate)
            except httpx.HTTPStatusError as exc:
                # A schema the model rejects (400) → retry once without the schema
                # and let pydantic validation + repair-retry handle correctness.
                if exc.response.status_code == 400 and output_schema is not None:
                    logger.warning(
                        "Gemini %s rejected responseSchema (400); retrying without it",
                        candidate,
                    )
                    try:
                        no_schema = {
                            "contents": contents,
                            "generationConfig": {
                                "maxOutputTokens": max_tokens,
                                "responseMimeType": "application/json",
                            },
                        }
                        if system_instruction:
                            no_schema["systemInstruction"] = system_instruction
                        data = self._post_generate(candidate, no_schema)
                        return self._parse_response(data, candidate)
                    except Exception as inner:  # noqa: BLE001 — fall through to next model
                        last_exc = inner
                        logger.warning("Gemini %s failed without schema: %s", candidate, inner)
                        continue
                last_exc = exc
                logger.warning("Gemini %s failed (%s); trying next model", candidate, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — fall back to the next model
                last_exc = exc
                logger.warning("Gemini %s failed (%s); trying next model", candidate, exc)
                continue

        raise RuntimeError(f"All Gemini Flash models failed. Last error: {last_exc}") from last_exc
