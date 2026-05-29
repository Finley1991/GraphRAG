"""Query-related data models."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    METRIC = "metric"
    CODE = "code"
    SEMANTIC = "semantic"
    MIXED = "mixed"


class Query(BaseModel):
    query_text: str
    top_k: int = 10
    intent: Optional[IntentType] = None
    company: Optional[str] = None
    year: Optional[int] = None
    metadata: Optional[dict] = None


class QueryRequest(BaseModel):
    query: str
    top_k: int = 10


class MetricQueryRequest(BaseModel):
    query: str
    company: str
    year: Optional[int] = None


class RetrievalResult(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    score_es: float = 0.0
    score_milvus: float = 0.0
    score_rrf: float = 0.0
    rank: int = 0
    metadata: Optional[dict] = None


class AnswerResult(BaseModel):
    query: Query
    answer: str
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=dict)
    latency_ms: float = 0.0