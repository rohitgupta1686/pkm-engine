from pydantic import BaseModel


class ClaimRecord(BaseModel):
    id: str
    source_id: str
    chunk_id: str | None = None
    statement: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    claim_type: str | None = None
    confidence: float = 0.5
    status: str = "candidate"
    valid_from: str | None = None
    valid_to: str | None = None
    created_at: str
