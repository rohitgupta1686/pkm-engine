"""Select and construct the active LLM client from settings.

One seam so the pipeline/CLI stay provider-agnostic: flip
``settings.llm_provider`` ("gemini" | "openai") to swap calling modules. On the
Gemini path this also logs the discovered Flash models (best-first), satisfying
the "print the list of available models" requirement.
"""
import logging

from pkm.config import Settings

logger = logging.getLogger(__name__)


def build_llm_client(conn, settings: Settings):
    """Return an LLM client (BaseLLMClient subclass) for the configured provider."""
    provider = (settings.llm_provider or "openai").lower()

    if provider == "gemini":
        from pkm.llm.gemini_client import GeminiClient

        client = GeminiClient(conn, settings.gemini_api_key, settings.gemini_model)
        try:
            models = client.list_models()
            logger.info(
                "LLM provider=gemini — %d Flash model(s) available, fallback order: %s",
                len(models), " → ".join(models) or "(none)",
            )
            print(  # surfaced in CI logs / CLI for operator visibility
                "Gemini Flash models (fallback order): " + (" → ".join(models) or "(none)")
            )
        except Exception as exc:  # noqa: BLE001 — listing is diagnostic, not fatal here
            logger.warning("Could not list Gemini models at startup: %s", exc)
        return client

    if provider == "openai":
        from pkm.llm.client import LLMClient

        logger.info("LLM provider=openai — model=%s", settings.llm_model)
        return LLMClient(conn, settings.openai_api_key, settings.openai_base_url)

    raise ValueError(f"Unknown llm_provider: {settings.llm_provider!r} (use 'gemini' or 'openai')")
