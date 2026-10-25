"""Prepare bounded PDF text or page images for AI extraction."""

from src.documents.images import StatementPdf
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage


class PdfStatementReader:
    def read_text(self, content: bytes) -> StatementDocument | None:
        pages = StatementPdf(content).text()
        if not pages or any(not text.strip() for text in pages):
            return None
        return StatementDocument(tuple(
            StatementPage(number, b"", text) for number, text in enumerate(pages, 1)
        ))

    def read(self, content: bytes) -> StatementDocument:
        page_images = StatementPdf(content).render()
        return StatementDocument(tuple(
            StatementPage(page_number, image)
            for page_number, image in enumerate(page_images, 1)
        ))
