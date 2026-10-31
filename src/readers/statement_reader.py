"""Pick the reader for an uploaded statement by its file extension."""

from collections.abc import Callable
from pathlib import Path

from src import config
from src.log_messages import error as error_messages
from src.models.statements.statement_document import StatementDocument
from src.readers.csv_reader import read_csv
from src.readers.pdf_reader import read_pdf

_FORMAT_READERS: dict[str, Callable[[bytes, str | None], StatementDocument]] = {
    ".pdf": read_pdf, ".csv": read_csv,
}


def read_statement(file_name: str, content: bytes, password: str | None = None) -> StatementDocument:
    """Reject oversized or unsupported uploads, then read text pages with the format's reader."""
    if len(content) > config.MAX_STATEMENT_BYTES:
        raise ValueError(error_messages.STATEMENT_FILE_TOO_LARGE.format(
            max_statement_megabytes=config.MAX_STATEMENT_BYTES / 1000000,
        ))
    read = _FORMAT_READERS.get(Path(file_name).suffix.lower())
    if not read:
        raise ValueError(error_messages.UPLOAD_A_SUPPORTED_STATEMENT)
    return read(content, password)
