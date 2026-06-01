"""Tests for DoclingTableParser and PageBatcher."""
import asyncio
import pytest
from unittest.mock import patch
from graphrag.pipeline.parse.docling_parser import DoclingParser, PageBatcher


class TestPageBatcher:
    def test_empty_pages(self):
        batcher = PageBatcher(batch_size=12, overlap=2)
        batches = list(batcher.batch([]))
        assert batches == []

    def test_single_batch(self):
        batcher = PageBatcher(batch_size=12, overlap=2)
        pages = list(range(0, 10))
        batches = list(batcher.batch(pages))
        assert len(batches) == 1
        assert batches[0] == (0, 9)

    def test_exact_batch_boundary(self):
        batcher = PageBatcher(batch_size=12, overlap=2)
        pages = list(range(0, 12))
        batches = list(batcher.batch(pages))
        assert len(batches) == 1
        assert batches[0] == (0, 11)

    def test_multiple_batches(self):
        batcher = PageBatcher(batch_size=12, overlap=2)
        pages = list(range(0, 30))
        batches = list(batcher.batch(pages))
        assert len(batches) == 3
        assert batches[0] == (0, 11)
        assert batches[1][0] == 10  # overlap start
        assert batches[2][0] == 20  # overlap start

    def test_overlap_equals_batch_size(self):
        batcher = PageBatcher(batch_size=10, overlap=10)
        pages = list(range(0, 30))
        batches = list(batcher.batch(pages))
        assert len(batches) == 3
        assert batches[0] == (0, 9)
        assert batches[1] == (9, 19)
        assert batches[2] == (19, 29)

    def test_non_contiguous_pages(self):
        batcher = PageBatcher(batch_size=12, overlap=2)
        pages = [0, 1, 5, 6, 10, 11]
        batches = list(batcher.batch(pages))
        assert len(batches) >= 1

    def test_zero_overlap(self):
        batcher = PageBatcher(batch_size=12, overlap=0)
        pages = list(range(0, 36))
        batches = list(batcher.batch(pages))
        assert len(batches) == 3
        assert batches[0] == (0, 11)
        assert batches[1] == (12, 23)


class TestDoclingParser:
    def test_parser_init_defaults(self):
        parser = DoclingParser()
        assert parser.batch_size >= 1
        assert parser.overlap >= 0

    @pytest.mark.asyncio
    async def test_parse_pages_failure_returns_none(self):
        parser = DoclingParser()
        with patch.object(
            asyncio.get_event_loop(), "run_in_executor"
        ) as mock_run:
            mock_run.return_value = asyncio.Future()
            mock_run.return_value.set_exception(Exception("parse error"))
            result = await parser.parse_pages("/nonexistent/file.pdf", (0, 1))
            assert result is None