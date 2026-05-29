"""Document data models."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    company: Optional[str] = None
    industry: Optional[str] = None
    doc_type: Optional[str] = None
    year: Optional[int] = None
    upload_time: datetime = Field(default_factory=datetime.now)


class PageRange(BaseModel):
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def pages(self) -> range:
        return range(self.start, self.end + 1)


class Document(BaseModel):
    doc_id: str
    filename: str
    source_path: str
    total_pages: int
    metadata: Optional[DocumentMetadata] = None
    created_at: datetime = Field(default_factory=datetime.now)


class ParsedDocument(BaseModel):
    doc_id: str
    filename: str
    source_path: str
    total_pages: int
    html_content: str
    metadata: Optional[DocumentMetadata] = None
    images: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)