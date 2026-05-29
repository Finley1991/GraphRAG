"""Chunk data models for sections and tables."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from graphrag.models.document import PageRange


class ChunkType(str, Enum):
    SECTION = "section"
    TABLE = "table"


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    page_range: PageRange
    chunk_type: ChunkType
    content_html: str
    content_text: str = ""
    token_count: int = 0
    embedding: Optional[list[float]] = None
    simhash: Optional[int] = None
    metadata: Optional[dict] = None


class SectionChunk(Chunk):
    chunk_type: ChunkType = ChunkType.SECTION
    heading: str = ""
    heading_level: int = 0

    def __str__(self) -> str:
        return f"[{self.heading}] {self.content_text[:100]}"


class TableChunk(Chunk):
    chunk_type: ChunkType = ChunkType.TABLE
    caption: str = ""
    table_index: int = 0

    def __str__(self) -> str:
        return f"[Table {self.table_index}: {self.caption}] {self.content_text[:100]}"