"""Per-token pricing for the OpenAI models used by the pipeline.

Ground truth from DECISIONS.md [T1-02] (locked 2026-06-19): gpt-5.4-mini
standard sync pricing, per 1M tokens. OpenAI prompt caching is automatic for
prompts >1024 tokens, so cached prompt tokens are billed at the cached rate.

compute_cost is pure and unit-tested directly. An unknown model raises KeyError
deliberately — the pipeline must never silently record cost_usd=0.0 (that was
the client.py:220 bug this module replaces).
"""

# Per 1M tokens.
PRICING: dict[str, dict[str, float]] = {
    "gpt-5.4-mini-2026-03-17": {
        "input": 0.75,   # non-cached prompt tokens
        "cached": 0.075,  # cached prompt tokens (90% off)
        "output": 4.50,   # completion tokens
    },
    # gpt-5.4 (the single-call synthesis model) — confirmed standard sync pricing,
    # per 1M tokens (2026-06-23). Cached input is 90% off, same structure as mini.
    "gpt-5.4": {
        "input": 2.50,   # non-cached prompt tokens
        "cached": 0.25,  # cached prompt tokens (90% off)
        "output": 15.00,  # completion tokens
    },
}


def compute_cost(
    model: str,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
) -> float:
    """Return USD cost for one LLM call.

    Args:
        model:            model id; must exist in PRICING (else KeyError).
        prompt_tokens:    total prompt tokens (OpenAI usage.prompt_tokens).
        cached_tokens:    cached portion of prompt tokens
                          (usage.prompt_tokens_details.cached_tokens; 0 if absent).
        completion_tokens: completion tokens (OpenAI usage.completion_tokens).

    Raises:
        KeyError: if model is not in PRICING — fail loud, never return 0.0.
    """
    p = PRICING[model]  # KeyError on unknown model — intentional
    non_cached = max(prompt_tokens - cached_tokens, 0)
    return (
        non_cached * p["input"] / 1_000_000
        + cached_tokens * p["cached"] / 1_000_000
        + completion_tokens * p["output"] / 1_000_000
    )