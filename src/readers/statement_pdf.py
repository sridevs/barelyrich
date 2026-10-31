
import math
from contextlib import contextmanager
from io import BytesIO

from src import config
from src.log_messages import error as error_messages

try:
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException
    from pdfplumber.utils.text import DEFAULT_X_DENSITY, DEFAULT_Y_DENSITY
except ImportError:
    pdfplumber = None


class StatementPasswordRequiredError(ValueError):
    """Raised when opening a statement PDF requires a password."""


class IncorrectStatementPasswordError(ValueError):
    """Raised when a supplied password cannot open a statement PDF."""


class StatementPdf:
    """Read bounded, layout-preserving embedded text from an uploaded PDF."""

    __slots__ = ("_content", "_password")

    def __init__(self, content: bytes, password: str | None = None):
        self._content = content
        self._password = password

    def text(self) -> tuple[str, ...]:
        with _open_document(self._content, "read", self._password) as document:
            if len(document.pages) > config.MAX_STATEMENT_PAGES:
                raise ValueError(
                    error_messages.STATEMENT_PAGE_LIMIT.format(max_statement_pages=config.MAX_STATEMENT_PAGES)
                )
            return _extract_text(document)


def _extract_text(document) -> tuple[str, ...]:
    pages = []
    character_count = 0
    for page in document.pages:
        text = _page_text(page, character_count)
        character_count += len(text)
        pages.append(text)
    return tuple(pages)


def _page_text(page, previous_characters: int) -> str:
    try:
        _require_layout_budget(page.width, page.height)
        count = sum(len(char["text"]) for char in page.chars)
        _require_text_budget(previous_characters + count)
        text = page.extract_text(layout=True)
        text = "\n".join(line.rstrip() for line in text.splitlines()).strip("\n")
        _require_text_budget(previous_characters + len(text))
        return text
    finally:
        page.close()


def _require_layout_budget(width: float, height: float) -> None:
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise ValueError(error_messages.STATEMENT_PDF_LAYOUT_TOO_LARGE)
    columns = math.ceil(width / DEFAULT_X_DENSITY)
    rows = math.ceil(height / DEFAULT_Y_DENSITY)
    if columns * rows > config.MAX_STATEMENT_TEXT_CHARACTERS:
        raise ValueError(error_messages.STATEMENT_PDF_LAYOUT_TOO_LARGE)


def _require_text_budget(count: int) -> None:
    if count > config.MAX_STATEMENT_TEXT_CHARACTERS:
        raise ValueError(error_messages.STATEMENT_PDF_TEXT_EXCEEDS_THE_256_000_CHARACTER_LIMIT)


def _require_pdfplumber():
    if pdfplumber is None:
        raise ValueError(
            error_messages.PDF_DEPENDENCY_REQUIRED.format(mode="text")
        )
    return pdfplumber


@contextmanager
def _open_document(content: bytes, operation: str, password: str | None = None):
    parser = _require_pdfplumber()
    try:
        with BytesIO(content) as stream, parser.open(stream, password=password) as document:
            yield document
    except PdfminerException as error:
        if isinstance(error.__context__, PDFPasswordIncorrect):
            if password is None:
                raise StatementPasswordRequiredError(
                    error_messages.PASSWORD_PROTECTED_PDF
                ) from error
            raise IncorrectStatementPasswordError(
                error_messages.INCORRECT_STATEMENT_PASSWORD
            ) from error
        raise ValueError(error_messages.PDF_OPERATION_FAILED.format(operation=operation)) from error
