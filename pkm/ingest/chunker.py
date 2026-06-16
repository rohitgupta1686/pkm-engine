"""
Deterministic text chunking for the PKM ingest pipeline.

Produces TextUnit chunks suitable for provenance-span tracking. Char ranges
are contiguous and cover the entire input (no gaps, no overlap). Same input
always produces the same chunk list.

Approximation: ~4 chars per token, so a 1200-token budget → 4800 char budget.
Prefers to break on paragraph boundaries (\\n\\n), then sentence boundaries,
within a ±20% tolerance window of the char budget.
"""

from __future__ import annotations


def chunk_text(text: str, target_tokens: int = 1200) -> list[dict]:
    """Split text into deterministic chunks.

    Args:
        text:          The full input text.
        target_tokens: Approximate token budget per chunk (default 1200).

    Returns:
        List of dicts with keys:
            ordinal    (int)  — 0-based chunk index
            char_start (int)  — inclusive start offset in original text
            char_end   (int)  — exclusive end offset in original text
            text       (str)  — text[char_start:char_end]
            token_count(int)  — approximation: len(slice) // 4
    """
    if not text:
        return [{
            "ordinal": 0,
            "char_start": 0,
            "char_end": 0,
            "text": "",
            "token_count": 0,
        }]

    char_budget = target_tokens * 4  # ~4 chars per token
    lower_bound = int(char_budget * 0.8)
    upper_bound = int(char_budget * 1.2)

    chunks: list[dict] = []
    start = 0
    total = len(text)

    while start < total:
        remaining = total - start
        # If remaining fits within the upper bound, take it all
        if remaining <= upper_bound:
            end = total
        else:
            # Ideal end = start + char_budget
            ideal_end = start + char_budget
            end = _find_break(text, start, ideal_end, lower_bound, upper_bound, total)

        slice_text = text[start:end]
        chunks.append({
            "ordinal": len(chunks),
            "char_start": start,
            "char_end": end,
            "text": slice_text,
            "token_count": len(slice_text) // 4,
        })
        start = end

    return chunks


def _find_break(
    text: str,
    start: int,
    ideal_end: int,
    lower_bound: int,
    upper_bound: int,
    total: int,
) -> int:
    """Find the best break point near ideal_end.

    Search window: [start + lower_bound, start + upper_bound].
    Priority: paragraph boundary (\\n\\n) > sentence boundary (. ! ?) > hard cut.
    Scans backward from ideal_end looking for a good break.
    """
    window_start = start + lower_bound
    window_end = min(start + upper_bound, total)

    if ideal_end > total:
        return total

    # Clamp ideal_end to window
    search_from = min(ideal_end, window_end)

    # Pass 1: paragraph boundary — scan backward from search_from
    pos = search_from
    while pos > window_start:
        if text[pos - 2:pos] == "\n\n":
            return pos
        pos -= 1

    # Pass 2: sentence boundary — scan backward from search_from
    pos = search_from
    while pos > window_start:
        if text[pos - 1] in ".!?":
            return pos
        pos -= 1

    # Pass 3: word boundary — scan backward
    pos = search_from
    while pos > window_start:
        if text[pos - 1] == " ":
            return pos
        pos -= 1

    # Fallback: hard cut at ideal_end (clamped)
    return min(ideal_end, total)
