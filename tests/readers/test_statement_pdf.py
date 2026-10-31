import logging
from io import BytesIO
from unittest.mock import MagicMock, Mock

import pytest
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from src.models.dto.statement_page import StatementPage
from src.readers import statement_pdf as images
from src.readers.statement_pdf import (
    IncorrectStatementPasswordError,
    StatementPasswordRequiredError,
    StatementPdf,
)
from src.service.statements import StatementImportService
from tests.statement_fixtures import text_document


def fictional_pdf(page_count=1, width=600, height=800):
    pdfium = pytest.importorskip("pypdfium2")
    output = BytesIO()
    with pdfium.PdfDocument.new() as document:
        for _ in range(page_count):
            document.new_page(width, height).close()
        document.save(output)
    return output.getvalue()


def test_text_reader_accepts_one_hundred_pages():
    pages = StatementPdf(fictional_pdf(page_count=100, width=60, height=80)).text()
    assert len(pages) == 100


def test_missing_text_dependency_has_install_instructions(monkeypatch):
    monkeypatch.setattr(images, "pdfplumber", None)
    with pytest.raises(ValueError, match="statements.*extra"):
        StatementPdf(b"pdf").text()


def test_text_reader_rejects_corrupt_and_oversized_page_counts():
    with pytest.raises(ValueError, match="Unable to read"):
        StatementPdf(b"not a PDF").text()
    with pytest.raises(ValueError, match="at most 100 pages"):
        StatementPdf(fictional_pdf(page_count=101)).text()


def mock_document(monkeypatch, *texts):
    document = MagicMock()
    document.__enter__.return_value = document
    document.pages = []
    for text in texts:
        page = Mock(width=600, height=800)
        page.chars = [{"text": text}]
        page.extract_text.return_value = text
        document.pages.append(page)
    monkeypatch.setattr(images.pdfplumber, "open", Mock(return_value=document))
    return document


def test_text_reader_closes_resources_when_text_limit_is_exceeded(monkeypatch):
    document = mock_document(monkeypatch, "x" * 256_001)
    with pytest.raises(ValueError, match="256,000-character limit"):
        StatementPdf(b"pdf").text()
    document.pages[0].extract_text.assert_not_called()
    document.pages[0].close.assert_called_once()
    document.__exit__.assert_called_once()


def test_layout_whitespace_counts_toward_combined_text_limit(monkeypatch):
    document = mock_document(monkeypatch, "first", "short")
    document.pages[1].extract_text.return_value = "x" * 255_999
    with pytest.raises(ValueError, match="256,000-character limit"):
        StatementPdf(b"pdf").text()
    assert all(page.close.call_count == 1 for page in document.pages)
    document.__exit__.assert_called_once()


def test_text_reader_preserves_columns_but_removes_empty_padding(monkeypatch):
    document = mock_document(monkeypatch, "\n  Date      Withdrawal    Balance   \n  Jan 1     10.00         90.00   \n\n")
    assert StatementPdf(b"pdf").text() == (
        "  Date      Withdrawal    Balance\n  Jan 1     10.00         90.00",
    )
    document.pages[0].extract_text.assert_called_once_with(layout=True)


@pytest.mark.parametrize("width,height", [
    (float("inf"), 800), (600, float("nan")), (0, 800), (600, -1), (10**9, 10**9),
])
def test_excessive_or_invalid_layout_is_rejected_before_extraction(monkeypatch, width, height):
    document = mock_document(monkeypatch, "small text")
    page = document.pages[0]
    page.width, page.height = width, height
    with pytest.raises(ValueError, match="page dimensions"):
        StatementPdf(b"pdf").text()
    page.extract_text.assert_not_called()
    page.close.assert_called_once()


@pytest.mark.parametrize(
    ("password", "exception"),
    [
        (None, StatementPasswordRequiredError),
        ("wrong password", IncorrectStatementPasswordError),
    ],
)
def test_password_errors_are_actionable_and_never_include_password(
    monkeypatch, password, exception,
):
    error = PdfminerException(PDFPasswordIncorrect())
    error.__context__ = PDFPasswordIncorrect()
    monkeypatch.setattr(images.pdfplumber, "open", Mock(side_effect=error))
    with pytest.raises(exception) as raised:
        StatementPdf(b"protected PDF", password).text()
    assert "wrong password" not in str(raised.value)


def test_password_is_passed_only_to_current_pdf_open(monkeypatch):
    mock_document(monkeypatch)
    assert StatementPdf(b"protected PDF", "open sesame").text() == ()
    args, kwargs = images.pdfplumber.open.call_args
    assert kwargs == {"password": "open sesame"}
    assert args[0].closed


def test_text_budget_applies_across_pages_before_layout_extraction(monkeypatch):
    document = mock_document(monkeypatch, "x" * 128_000, "y" * 128_001)
    with pytest.raises(ValueError, match="256,000-character limit"):
        StatementPdf(b"pdf").text()
    document.pages[1].extract_text.assert_not_called()
    assert all(page.close.call_count == 1 for page in document.pages)


@pytest.mark.parametrize("text", ["", "   ", b"bytes"])
def test_page_rejects_missing_or_non_text_content(text):
    with pytest.raises(ValueError, match="extracted text"):
        StatementPage(1, text)


def test_document_processing_timing_does_not_log_source(caplog, monkeypatch):
    document = text_document()
    monkeypatch.setattr("src.service.statements.read_statement", lambda *_: document)
    with caplog.at_level(logging.INFO):
        StatementImportService(Mock()).preview("private.pdf", b"private")
    assert "document processing completed" in caplog.text
    assert "private" not in caplog.text
