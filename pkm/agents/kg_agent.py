"""
KGAgent — Knowledge Graph extraction agent (fourth PKM pipeline agent).

Extracts entities (GraphNode) and relationships (GraphRelationship) from
pre-processed claim text, returning a validated KGAgentOutput instance.
"""

from pkm.agents.base import BaseAgent
from pkm.llm.models import SONNET
from pkm.schemas.agent_io import KGAgentOutput


class KGAgent(BaseAgent):
    """
    Knowledge Graph agent: entity and relationship extraction from claims.

    Uses er_extraction.v1.md prompt to identify named entities and the
    relationships between them, returning a KGAgentOutput pydantic model.
    """

    role = "kg_agent"
    model = SONNET
    prompt_template = "er_extraction.v1.md"
    prompt_version = "v1"
    input_schema = None
    output_schema = KGAgentOutput
    memory_tier = "working"
