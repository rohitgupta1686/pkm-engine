from pydantic import BaseModel


class EntityRecord(BaseModel):
    id: str
    type: str
    name: str
    properties: dict = {}
    wiki_path: str | None = None
    created_at: str
    updated_at: str
