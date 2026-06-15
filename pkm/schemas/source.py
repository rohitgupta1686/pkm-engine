from pydantic import BaseModel


class SourceRecord(BaseModel):
    id: str
    content_hash: str
    type: str
    title: str | None = None
    author: str | None = None
    url: str | None = None
    publisher: str | None = None
    date_published: str | None = None
    date_saved: str
    raw_path: str
    wiki_path: str | None = None
    credibility: float = 0.5
    tags: list[str] = []
    status: str = "captured"
    created_at: str
    updated_at: str
