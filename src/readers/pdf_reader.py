"""Read embedded PDF text into statement pages for AI extraction."""

import logging

from src.log_messages import error as error_messages
from src.log_messages import info
from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_document import StatementDocument
from src.readers.statement_pdf import StatementPdf

LOGGER = logging.getLogger(__name__)


def read_pdf(content: bytes, password: str | None = None) -> StatementDocument:
    """Reject scanned PDFs: every page must carry embedded text."""
    LOGGER.info(info.PDF_TEXT_EXTRACTION)
    pages = StatementPdf(content, password).text()
    if not pages or any(not text.strip() for text in pages):
        raise ValueError(error_messages.STATEMENT_PDF_TEXT_REQUIRED)
    LOGGER.info(info.PDF_TEXT_AVAILABLE, len(pages))
    return StatementDocument(tuple(
        StatementPage(number, text) for number, text in enumerate(pages, 1)
    ))
