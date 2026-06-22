"""
ConceptSynthesisAgent — synthesizes a concept wiki page from its linked claims.
Returns a validated ConceptSynthesisOutput pydantic instance.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from pkm.agents.base import BaseAgent
from pkm.config import settings
from pkm.schemas.agent_io import ConceptSynthesisOutput


class ConceptSynthesisAgent(BaseAgent):
    role: ClassVar[str] = "concept_synthesis_agent"
    model: ClassVar[str] = settings.active_model
    prompt_template: ClassVar[str] = "concept_synthesis.v1.md"
    prompt_version: ClassVar[str] = "v1"
    input_schema: ClassVar[type | None] = None
    output_schema: ClassVar[type[BaseModel]] = ConceptSynthesisOutput
    memory_tier: ClassVar[str] = "working"
