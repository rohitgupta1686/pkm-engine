"""Single-call note synthesis — the redesigned PKM engine.

ONE LLM call per source produces ONE readable Markdown note. This replaces the
legacy 4-agent chain (Reader → Summarizer → ConceptExtractor → KGAgent) plus the
per-concept synthesis loop, claim atomization, and Vectorize embeddings. There is
no Turso write on this path, no SPO triples, no concept pages.

The whole "engine" is the system prompt in pkm/prompts/synthesis.v3.md. We reuse
the provider-agnostic ``BaseLLMClient.call`` (SHA-256 cache, agent_runs row, cost
tracking, truncation retry) with ``output_schema=None`` so it returns the raw
Markdown note text rather than a validated pydantic model.
"""
from __future__ import annotations

from pathlib import Path

# Cache-key identity for this call in agent_runs. Bump the version when the prompt
# changes materially so prior cached notes are not reused.
SYNTH_AGENT_NAME = "note_synthesizer"
SYNTH_PROMPT_TEMPLATE = "synthesis.v3.md"
SYNTH_PROMPT_VERSION = "v3"

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / SYNTH_PROMPT_TEMPLATE


def load_synthesis_prompt() -> str:
    """Return the synthesis system prompt text (the entire engine)."""
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Synthesis prompt not found: {_PROMPT_PATH}. "
            f"Expected pkm/prompts/{SYNTH_PROMPT_TEMPLATE}."
        )
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_message(
    raw_text: str,
    existing_titles: list[str],
    recent_frames: list[str] | None = None,
) -> str:
    """Compose the user turn: raw capture + linkable slugs + recent wildcard frames.

    The slug list is what the prompt's "Connects to" section may link to — the
    model is instructed to choose ONLY from these and never invent a slug.

    ``recent_frames`` are the wildcard frames used by the most recent notes. A
    stateless call can't see its siblings, so we feed them in and ask the model to
    avoid repeating them — the only way to keep wildcard frames varied across the
    corpus (the prompt's "frames should look varied" rule is otherwise unenforceable).
    """
    if existing_titles:
        titles_block = "\n".join(f"- {t}" for t in sorted(existing_titles))
    else:
        titles_block = "(none yet — this is the first note)"

    msg = (
        f"{raw_text}\n\n"
        "---\n"
        "EXISTING NOTE SLUGS (for the \"Connects to\" section — link ONLY to these, "
        "never invent one, never link this note's own slug):\n"
        f"{titles_block}\n"
    )
    if recent_frames:
        frames_block = "\n".join(f"- {f}" for f in recent_frames)
        msg += (
            "\n---\n"
            "WILDCARD FRAMES USED BY RECENT NOTES (avoid repeating these to keep the "
            "vault varied — prefer a different frame, or skip the wildcard, unless one "
            "of these is unmistakably the only fit for this piece):\n"
            f"{frames_block}\n"
        )
    return msg


def synthesize_note(
    llm_client,
    raw_text: str,
    existing_titles: list[str] | None = None,
    source_id: str | None = None,
    model: str | None = None,
    recent_frames: list[str] | None = None,
) -> dict:
    """Turn one raw capture into one Markdown note via a single LLM call.

    Args:
        llm_client: a BaseLLMClient (OpenAI on the production path).
        raw_text:   the raw captured Markdown (front matter + body).
        existing_titles: slugs of existing notes, for cross-linking.
        source_id:  optional id recorded on the agent_runs row for provenance.
        model:      model id to call; defaults to the client's caller passing
                    settings.synthesis_model. Required — no implicit default here.
        recent_frames: wildcard frames used by recent notes, to avoid repeating.

    Returns:
        The dict from ``llm_client.call`` — ``result`` holds the note Markdown
        (a str, since output_schema is None), plus ``cached`` / token counts.
    """
    if not model:
        raise ValueError("synthesize_note: a model id is required (settings.synthesis_model).")

    prompt = load_synthesis_prompt()
    user_message = _build_user_message(raw_text, existing_titles or [], recent_frames or [])

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message},
    ]

    return llm_client.call(
        agent_name=SYNTH_AGENT_NAME,
        model=model,
        prompt_version=SYNTH_PROMPT_VERSION,
        messages=messages,
        # input_text is the cache-key payload — must include BOTH the raw capture
        # and the linkable slug list so changing either busts the cache correctly.
        input_text=user_message,
        source_id=source_id,
        output_schema=None,  # freeform Markdown, not a validated schema
    )
