"""PyMuPDF-based page scanner: detect tables, classify pages, extract HTML."""
from typing import Optional
import fitz
from loguru import logger
from graphrag.models.document import PageRange
from graphrag.config.settings import load_settings


class TableDetector:
    def has_table(self, page: fitz.Page) -> bool:
        tables = page.find_tables()
        return len(tables) > 0


class PageClassifier:
    def __init__(self):
        self._detector = TableDetector()

    def classify(self, page: fitz.Page) -> str:
        if self._detector.has_table(page):
            return "table"
        return "text"

    def scan_page(self, page: fitz.Page) -> tuple[str, Optional[str]]:
        page_type = self.classify(page)
        html = None
        if page_type == "text":
            html = page.get_text("html")
        return page_type, html


class PDFScanner:
    def __init__(self):
        settings = load_settings()
        self._classifier = PageClassifier()
        self._context_before = settings.pipeline.context_pages_before
        self._context_after = settings.pipeline.context_pages_after

    def scan(self, filepath: str) -> dict:
        doc = fitz.open(filepath)
        total_pages = len(doc)
        table_pages: set[int] = set()
        tableless_html: dict[int, str] = {}

        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            page_type, html = self._classifier.scan_page(page)
            if page_type == "table":
                table_pages.add(page_num)
            elif html:
                tableless_html[page_num] = html

        doc.close()

        table_ranges = self._find_continuous_ranges(table_pages)
        context_ranges = self._compute_context_ranges(table_pages, total_pages)
        context_range_list = self._find_continuous_ranges(context_ranges)

        return {
            "total_pages": total_pages,
            "table_pages": sorted(table_pages),
            "tableless_html_pages": tableless_html,
            "table_page_ranges": table_ranges,
            "context_page_ranges": context_range_list,
        }

    def scan_page_safe(self, filepath: str, page_num: int) -> Optional[str]:
        try:
            doc = fitz.open(filepath)
            page = doc.load_page(page_num)
            html = page.get_text("html")
            doc.close()
            return html
        except Exception as e:
            logger.error(f"Failed to scan page {page_num} of {filepath}: {e}")
            return None

    def _find_continuous_ranges(self, pages: set[int]) -> list[PageRange]:
        if not pages:
            return []
        sorted_pages = sorted(pages)
        ranges: list[PageRange] = []
        start = sorted_pages[0]
        end = sorted_pages[0]

        for p in sorted_pages[1:]:
            if p == end + 1:
                end = p
            else:
                ranges.append(PageRange(start=start, end=end))
                start = p
                end = p
        ranges.append(PageRange(start=start, end=end))
        return ranges

    def _compute_context_ranges(self, table_pages: set[int], total_pages: int) -> set[int]:
        context_pages: set[int] = set()
        for tp in table_pages:
            for offset in range(1, self._context_before + 1):
                before = tp - offset
                if before >= 0 and before not in table_pages:
                    context_pages.add(before)
            for offset in range(1, self._context_after + 1):
                after = tp + offset
                if after < total_pages and after not in table_pages:
                    context_pages.add(after)
        return context_pages