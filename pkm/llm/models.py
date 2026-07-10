"""Canonical LLM model identifiers.

Single-call note synthesis runs on GLM52, configured via
Settings.synthesis_model (SYNTHESIS_MODEL). OpenAI model ids are retained for
model comparison and fallback runs.
"""

MINI = "gpt-5.4-mini-2026-03-17"

GLM52 = "glm-5.2"

# Single-call note synthesis (the redesigned pipeline) runs on the full model for
# editorial quality when using the OpenAI fallback.
GPT54 = "gpt-5.4"

# OpenAI fallback model (2026-07-09). gpt-5.5 standard sync pricing is 2x
# gpt-5.4, but OpenAI Batch API fallback runs it at 50% off.
GPT55 = "gpt-5.5"
