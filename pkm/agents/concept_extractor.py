"""
ConceptExtractor — extracts structured claims and concept matches from source text.

Returns a validated ConceptExtractorOutput pydantic instance.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from pkm.agents.base import BaseAgent
from pkm.llm.models import SONNET
from pkm.schemas.agent_io import ConceptExtractorOutput


class ConceptExtractor(BaseAgent):
    """
    Agent that produces a ConceptExtractorOutput from raw source text.

    Calls the Anthropic API using the extract_claims.v1.md prompt template and returns
    a validated ConceptExtractorOutput containing claims and concept_matches.
    """

    role: ClassVar[str] = "concept_extractor"
    model: ClassVar[str] = SONNET
    prompt_template: ClassVar[str] = "extract_claims.v1.md"
    prompt_version: ClassVar[str] = "v1"
    input_schema: ClassVar[type | None] = None
    output_schema: ClassVar[type[BaseModel]] = ConceptExtractorOutput
    memory_tier: ClassVar[str] = "working"
