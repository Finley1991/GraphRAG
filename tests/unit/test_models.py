"""Tests for data models."""
from datetime import datetime
from graphrag.models.document import Document, PageRange, DocumentMetadata
from graphrag.models.chunk import Chunk, ChunkType, SectionChunk, TableChunk
from graphrag.models.tasks import ScanTask, ParseTask, IndexTask
from graphrag.models.query import Query, RetrievalResult, IntentType, AnswerResult


def test_document_creation():
    doc = Document(
        doc_id="test-001",
        filename="report.pdf",
        source_path="/tmp/report.pdf",
        total_pages=10,
    )
    assert doc.doc_id == "test-001"
    assert doc.total_pages == 10
    assert doc.metadata is None


def test_document_with_metadata():
    doc = Document(
        doc_id="test-002",
        filename="2023_annual.pdf",
        source_path="/tmp/2023_annual.pdf",
        total_pages=100,
        metadata=DocumentMetadata(
            company="ABC Corp",
            industry="Finance",
            doc_type="annual_report",
            year=2023,
        ),
    )
    assert doc.metadata.company == "ABC Corp"
    assert doc.metadata.doc_type == "annual_report"


def test_page_range():
    pr = PageRange(start=3, end=5)
    assert pr.start == 3
    assert pr.end == 5
    assert pr.length == 3
    assert list(pr.pages) == [3, 4, 5]


def test_section_chunk():
    chunk = SectionChunk(
        chunk_id="sec-001",
        doc_id="test-001",
        page_range=PageRange(start=1, end=3),
        heading="Introduction",
        heading_level=1,
        content_html="<p>This is introduction</p>",
        token_count=50,
    )
    assert chunk.chunk_type == ChunkType.SECTION
    assert chunk.heading_level == 1
    assert "Introduction" in str(chunk)


def test_table_chunk():
    chunk = TableChunk(
        chunk_id="tbl-001",
        doc_id="test-001",
        page_range=PageRange(start=5, end=6),
        caption="Revenue Table",
        content_html="<table><tr><td>Revenue</td></tr></table>",
        token_count=30,
    )
    assert chunk.chunk_type == ChunkType.TABLE
    assert chunk.caption == "Revenue Table"


def test_scan_task_serialization():
    doc = Document(doc_id="t1", filename="a.pdf", source_path="/a.pdf", total_pages=5)
    task = ScanTask(document=doc, priority=1)
    data = task.model_dump()
    assert data["priority"] == 1
    assert data["document"]["doc_id"] == "t1"


def test_query_model():
    q = Query(
        query_text="What is the revenue of ABC Corp in 2023?",
        top_k=10,
        intent=IntentType.METRIC,
        company="ABC Corp",
    )
    assert q.intent == IntentType.METRIC
    assert q.company == "ABC Corp"


def test_retrieval_result():
    rr = RetrievalResult(
        chunk_id="sec-001",
        doc_id="test-001",
        content="some text",
        score_es=0.85,
        score_milvus=0.72,
        score_rrf=0.78,
        rank=1,
    )
    assert rr.score_rrf == 0.78
    assert rr.rank == 1


def test_answer_result():
    q = Query(query_text="test", top_k=5)
    ar = AnswerResult(
        query=q,
        answer="This is the answer.",
        retrieval_results=[RetrievalResult(
            chunk_id="c1", doc_id="d1", content="ctx", score_es=0.9, score_milvus=0.8, score_rrf=0.85, rank=1
        )],
        token_usage={"prompt": 100, "completion": 50, "total": 150},
        latency_ms=1200,
    )
    assert ar.answer == "This is the answer."
    assert ar.latency_ms == 1200