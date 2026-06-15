from pydantic import BaseModel


class GraphNodeRecord(BaseModel):
    id: str
    label: str
    name: str
    properties: dict = {}
    confidence: float = 0.5
    provenance: list[str] = []
    created_at: str
    updated_at: str


class GraphEdgeRecord(BaseModel):
    id: str
    src: str
    dst: str
    type: str
    description: str | None = None
    strength: int | None = None
    confidence: float = 0.5
    provenance: list[str] = []
    created_at: str
    updated_at: str
