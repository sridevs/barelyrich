
import logging
from pathlib import Path

from src.log_messages import error as error_messages
from src import config
from src.log_messages import info
from src.documents.pdf_statement import PdfStatementReader
from src.models.statements.statement_document import StatementDocument


LOGGER = logging.getLogger(__name__)


class StatementDocumentReader:
    """Validate PDF uploads; optionally try embedded text before page images."""

    def __init__(self, *, prefer_text: bool = False):
        self._prefer_text = prefer_text

    def read(self, file_name: str, content: bytes) -> StatementDocument:
        if len(content) > config.MAX_STATEMENT_BYTES:
            raise ValueError(
                error_messages.STATEMENT_FILE_TOO_LARGE.format(max_statement_megabytes=config.MAX_STATEMENT_BYTES / 1000000)
            )
        if Path(file_name).suffix.lower() != ".pdf":
            raise ValueError(error_messages.UPLOAD_A_PDF_STATEMENT)
        return self._read_pdf(content)

    def _read_pdf(self, content: bytes) -> StatementDocument:
        reader = PdfStatementReader()
        if self._prefer_text:
            LOGGER.info(info.PDF_TEXT_EXTRACTION)
            document = reader.read_text(content)
            if document:
                LOGGER.info(info.PDF_TEXT_AVAILABLE, len(document.pages))
                return document
            LOGGER.info(info.PDF_TEXT_MISSING)
        LOGGER.info(info.PDF_IMAGE_PREPARATION)
        return reader.read(content)
