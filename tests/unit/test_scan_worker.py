"""Tests for scan worker."""
from unittest.mock import AsyncMock, patch
import pytest
from graphrag.pipeline.scan.worker import ScanWorker
from graphrag.models.document import PageRange


@pytest.mark.asyncio
async def test_scan_worker_initialization():
    worker = ScanWorker()
    assert worker.queue_name == "scan_task"
    assert worker.output_queue_name == "parse_task"


@pytest.mark.asyncio
async def test_scan_worker_process():
    worker = ScanWorker()
    task = {
        "document": {
            "doc_id": "test-001",
            "filename": "report.pdf",
            "source_path": "/tmp/report.pdf",
            "total_pages": 10,
        },
        "priority": 0,
    }
    with patch.object(worker, '_do_scan', new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = {
            "total_pages": 10,
            "table_pages": [3, 4, 5],
            "tableless_html_pages": {0: "<html>...</html>", 1: "<html>...</html>"},
            "table_page_ranges": [PageRange(start=3, end=5)],
            "context_page_ranges": [PageRange(start=2, end=2), PageRange(start=6, end=6)],
        }
        result = await worker.process(task)
        assert result["stage"] == "scan_complete"
        assert result["parse_task"]["document"]["doc_id"] == "test-001"