"""Canonical LLM model identifiers.

Single-call note synthesis runs on the full model (GPT54), configured via
Settings.synthesis_model (PKM_SYNTHESIS_MODEL). MINI is retained for the model
comparison script (scripts/compare_models.py) and its pricing entry.
"""

MINI = "gpt-5.4-mini-2026-03-17"

# Single-call note synthesis (the redesigned pipeline) runs on the full model for
# editorial quality. Snapshot still to confirm; "gpt-5.4" tracks the latest 5.4.
GPT54 = "gpt-5.4"