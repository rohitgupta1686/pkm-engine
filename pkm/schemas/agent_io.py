from typing import Literal

from pydantic import BaseModel, Field


class KeyClaim(BaseModel):
    statement: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    claim_type: Literal["fact", "opinion", "prediction", "definition", "causal", "statistic"]
    chunk_id: str
    confidence: float = Field(ge=0, le=1)


class SummarizerOutput(BaseModel):
    thesis: str
    key_claims: list[KeyClaim]
    caveats: list[str]
    summary_confidence: float = Field(ge=0, le=1)


class GraphNode(BaseModel):
    id: str
    label: str
    name: str
    # Named `attributes` (not `properties`) to avoid colliding with the JSON
    # Schema "properties" keyword: OpenAI strict mode rejects a field named
    # "properties" ("Extra required key 'properties' supplied"). See 04-03.
    attributes: dict[str, str] = {}
    confidence: float = Field(ge=0, le=1)
    provenance: list[str]


class GraphRelationship(BaseModel):
    src: str
    dst: str
    type: str
    description: str
    strength: int = Field(ge=1, le=10)
    confidence: float = Field(ge=0, le=1)
    provenance: list[str]


class KGAgentOutput(BaseModel):
    nodes: list[GraphNode]
    relationships: list[GraphRelationship]


class ConceptMatch(BaseModel):
    concept_name: str
    claim_indices: list[int]  # indices into the claims list
    confidence: float = Field(ge=0, le=1)


class ConceptExtractorOutput(BaseModel):
    claims: list[KeyClaim]
    concept_matches: list[ConceptMatch]
