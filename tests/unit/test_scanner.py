"""Tests for PDF page scanner."""
from unittest.mock import MagicMock
from graphrag.pipeline.scan.scanner import PDFScanner, TableDetector, PageClassifier


def test_table_detector_detects_table():
    detector = TableDetector()
    mock_page = MagicMock()
    mock_page.find_tables.return_value = ["table1"]
    assert detector.has_table(mock_page) is True
    mock_page.find_tables.assert_called_once()


def test_table_detector_no_table():
    detector = TableDetector()
    mock_page = MagicMock()
    mock_page.find_tables.return_value = []
    assert detector.has_table(mock_page) is False


def test_page_classifier():
    classifier = PageClassifier()
    mock_table_page = MagicMock()
    mock_table_page.find_tables.return_value = ["table1"]
    mock_no_table_page = MagicMock()
    mock_no_table_page.find_tables.return_value = []

    assert classifier.classify(mock_table_page) == "table"
    assert classifier.classify(mock_no_table_page) == "text"


def test_context_page_ranges():
    scanner = PDFScanner()
    table_pages = {3, 4, 5, 10, 11, 12, 13}
    context = scanner._compute_context_ranges(table_pages, total_pages=20)
    assert 2 in context
    assert 6 in context
    assert 9 in context
    assert 14 in context


def test_continuous_table_ranges():
    scanner = PDFScanner()
    table_pages = {1, 2, 3, 5, 6, 10}
    ranges = scanner._find_continuous_ranges(table_pages)
    assert len(ranges) == 3
    assert ranges[0].start == 1 and ranges[0].end == 3
    assert ranges[1].start == 5 and ranges[1].end == 6
    assert ranges[2].start == 10 and ranges[2].end == 10