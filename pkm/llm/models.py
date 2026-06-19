"""Canonical LLM model identifiers.

The cloud ingest pipeline runs on a single model: gpt-5.4-mini. Settings.llm_model
defaults to MINI; agents reference settings.llm_model so the model is
environment-configurable (cloud = real OpenAI via OPENAI_API_KEY; local dev can
point the OpenAI SDK at an OpenAI-compatible endpoint such as CLIProxyAPI by
setting OPENAI_BASE_URL + PKM_LLM_MODEL to a claude-* id).
"""

MINI = "gpt-5.4-mini-2026-03-17"