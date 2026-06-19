"""
SummarizerAgent — extracts a structured summary (thesis, key claims, caveats) from source text.

Returns a validated SummarizerOutput pydantic instance.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from pkm.agents.base import BaseAgent
from pkm.config import settings
from pkm.schemas.agent_io import SummarizerOutput


class SummarizerAgent(BaseAgent):
    """
    Agent that produces a SummarizerOutput from raw source text.

    Calls the OpenAI API using the summarize.v1.md prompt template and returns
    a validated SummarizerOutput containing thesis, key_claims, caveats, and
    summary_confidence.
    """

    role: ClassVar[str] = "summarizer_agent"
    model: ClassVar[str] = settings.llm_model
    prompt_template: ClassVar[str] = "summarize.v1.md"
    prompt_version: ClassVar[str] = "v1"
    input_schema: ClassVar[type | None] = None
    output_schema: ClassVar[type[BaseModel]] = SummarizerOutput
    memory_tier: ClassVar[str] = "working"
