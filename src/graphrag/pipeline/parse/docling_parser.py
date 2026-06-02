"""Docling-based table parser with page batching."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from loguru import logger

from graphrag.config.settings import load_settings


class PageBatcher:
    """Split a sorted list of page numbers into overlapping batches."""

    def __init__(self, batch_size: int = 12, overlap: int = 2):
        self.batch_size = batch_size
        self.overlap = overlap

    def batch(self, pages: list[int]) -> list[tuple[int, int]]:
        """Yield (start_page, end_page) tuples with overlap."""
        if not pages:
            return []
        sorted_pages = sorted(pages)
        batches: list[tuple[int, int]] = []
        i = 0
        while i < len(sorted_pages):
            start_page = sorted_pages[i]
            batch_end = start_page + self.batch_size - 1
            end_idx = i
            while end_idx < len(sorted_pages) and sorted_pages[end_idx] <= batch_end:
                end_idx += 1
            end_page = sorted_pages[end_idx - 1]
            batches.append((start_page, end_page))
            overlap_start = end_page - self.overlap
            while i < len(sorted_pages) and sorted_pages[i] <= overlap_start:
                i += 1
        return batches


class DoclingParser:
    """Async wrapper around Docling's DocumentConverter with page batching."""

    def __init__(self):
        settings = load_settings()
        self.batch_size = settings.pipeline.docling_batch_size
        self.overlap = settings.pipeline.docling_overlap_pages
        self._batcher = PageBatcher(self.batch_size, self.overlap)
        self._executor = ThreadPoolExecutor(max_workers=2)

    def _make_converter(self):
        """Create a GPU-accelerated DocumentConverter."""
        from docling.document_converter import (
            DocumentConverter,
            FormatOption,
            InputFormat,
        )
        from docling.datamodel.pipeline_options import (
            AcceleratorDevice,
            AcceleratorOptions,
            PdfPipelineOptions,
        )
        from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
        from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

        acc_opts = AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CUDA)
        pipeline_opts = PdfPipelineOptions()
        pipeline_opts.accelerator_options = acc_opts
        pipeline_opts.do_table_structure = True
        pipeline_opts.do_ocr = False
        fmt_opts = FormatOption(
            backend=DoclingParseDocumentBackend,
            pipeline_cls=StandardPdfPipeline,
            pipeline_options=pipeline_opts,
        )
        return DocumentConverter(format_options={InputFormat.PDF: fmt_opts})

    async def parse_pages(
        self, filepath: str, page_range: tuple[int, int]
    ) -> Optional[str]:
        """Parse a page range asynchronously. Returns HTML or None on failure."""
        loop = asyncio.get_event_loop()
        try:
            html = await loop.run_in_executor(
                self._executor,
                self._parse_sync,
                filepath,
                page_range,
            )
            return html
        except Exception as e:
            logger.error(
                f"Docling parse failed for {filepath} pages {page_range}: {e}"
            )
            return None

    def _parse_sync(self, filepath: str, page_range: tuple[int, int]) -> str:
        """Synchronous Docling conversion. Runs in executor thread."""
        converter = self._make_converter()
        start, end = page_range
        pages_str = f"{start}-{end}" if start != end else str(start)
        uri = f"{filepath}#pages={pages_str}"
        result = converter.convert(uri)
        return result.document.export_to_html()

    async def parse_batches(
        self, filepath: str, page_ranges: list[tuple[int, int]]
    ) -> dict[int, str]:
        """Parse multiple page ranges in parallel."""
        tasks = [self.parse_pages(filepath, pr) for pr in page_ranges]
        results = await asyncio.gather(*tasks)
        output: dict[int, str] = {}
        for pr, html in zip(page_ranges, results):
            if html:
                output[pr[0]] = html
        return output