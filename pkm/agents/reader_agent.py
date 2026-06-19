"""
ReaderAgent — normalizes raw captured Markdown bytes to clean Markdown with YAML front matter.

Uses the configured model (gpt-5.4-mini by default) for stateless text normalization.
No pydantic output schema — returns cleaned Markdown text directly.
"""

from __future__ import annotations

from typing import ClassVar

from pkm.agents.base import BaseAgent
from pkm.config import settings


class ReaderAgent(BaseAgent):
    """
    Concrete BaseAgent that normalizes raw captured text into clean Markdown.

    Input:  Raw Markdown bytes (string), possibly with HTML artifacts, broken
            encoding, or missing/incomplete YAML front matter.
    Output: Clean Markdown string with valid YAML front matter containing known
            metadata fields (id, type, title, author, url, date_published,
            date_saved, content_hash, tags). Body content preserved verbatim.

    Because output_schema = None, BaseAgent.run() returns a plain string.
    """

    role: ClassVar[str] = "reader_agent"
    model: ClassVar[str] = settings.llm_model
    prompt_template: ClassVar[str] = "reader.v1.md"
    prompt_version: ClassVar[str] = "v1"
    input_schema: ClassVar[type | None] = None
    output_schema: ClassVar[type | None] = None
    memory_tier: ClassVar[str] = "stateless"
