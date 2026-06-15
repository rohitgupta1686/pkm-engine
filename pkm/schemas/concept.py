from pydantic import BaseModel


class ConceptRecord(BaseModel):
    id: str
    name: str
    definition: str | None = None
    domain: str | None = None
    wiki_path: str
    created_at: str
    updated_at: str
