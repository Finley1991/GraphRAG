"""Pipeline task message models."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from graphrag.models.document import Document, ParsedDocument, PageRange


class ScanTask(BaseModel):
    document: Document
    priority: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


class ScanResult(BaseModel):
    document: Document
    tableless_html_pages: dict[int, str] = Field(default_factory=dict)
    table_page_ranges: list[PageRange] = Field(default_factory=list)
    context_page_ranges: list[PageRange] = Field(default_factory=list)


class ParseTask(BaseModel):
    document: Document
    table_page_ranges: list[PageRange] = Field(default_factory=list)
    context_page_ranges: list[PageRange] = Field(default_factory=list)
    tableless_html_pages: dict[int, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class IndexTask(BaseModel):
    document: ParsedDocument
    created_at: datetime = Field(default_factory=datetime.now)


class PipelineEvent(BaseModel):
    doc_id: str
    stage: str
    status: str
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)