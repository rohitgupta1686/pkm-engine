from pydantic import BaseModel


class ChunkRecord(BaseModel):
    id: str
    source_id: str
    ordinal: int
    char_start: int | None = None
    char_end: int | None = None
    token_count: int | None = None
    text: str
