"""
Confidence update utilities for the PKM knowledge graph (AD-6).
"""


def noisy_or(s_old: float, s_new: float) -> float:
    """
    Noisy-OR confidence update (AD-6): s' = 1 - (1 - s_old) * (1 - s_new)

    Combines two independent evidence signals into a single confidence score.
    The result is always >= max(s_old, s_new).

    Examples:
        noisy_or(0.5, 0.5) == 0.75
        noisy_or(0.0, 0.8) == 0.8
        noisy_or(1.0, 0.5) == 1.0
    """
    return 1.0 - (1.0 - s_old) * (1.0 - s_new)
