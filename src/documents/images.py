
from io import BytesIO
from contextlib import contextmanager
import math
from threading import Lock

from src.log_messages import error as error_messages
from src import config

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None


_RENDER_LOCK = Lock()


class StatementPdf:
    """Read bounded text and render page images from an uploaded PDF."""

    __slots__ = ("_content",)

    def __init__(self, content: bytes):
        self._content = content

    def text(self) -> tuple[str, ...]:
        with _open_document(self._content, "read") as document:
            if len(document) > config.MAX_VISION_PAGES:
                raise ValueError(
                    error_messages.STATEMENT_PAGE_LIMIT.format(max_vision_pages=config.MAX_VISION_PAGES)
                )
            return _extract_text(document)

    def render(self) -> tuple[bytes, ...]:
        try:
            with _open_document(self._content, "render") as document:
                if len(document) > config.MAX_VISION_PAGES:
                    raise ValueError(
                        error_messages.VISUAL_STATEMENT_PAGE_LIMIT.format(max_vision_pages=config.MAX_VISION_PAGES)
                    )
                return tuple(_render_page(document, index) for index in range(len(document)))
        except ImportError as error:
            raise ValueError(
                error_messages.PDF_PILLOW_REQUIRED
            ) from error


def _extract_text(document) -> tuple[str, ...]:
    pages = []
    character_count = 0
    for index in range(len(document)):
        text, page_characters = _page_text(document, index, character_count)
        character_count += page_characters
        pages.append(text)
    return tuple(pages)


def _page_text(document, index: int, previous_characters: int) -> tuple[str, int]:
    page = document[index]
    try:
        text_page = page.get_textpage()
        try:
            count = text_page.count_chars()
            if previous_characters + count > config.MAX_STATEMENT_TEXT_CHARACTERS:
                raise ValueError(error_messages.STATEMENT_PDF_TEXT_EXCEEDS_THE_256_000_CHARACTER_LIMIT)
            return text_page.get_text_bounded(), count
        finally:
            text_page.close()
    finally:
        page.close()


def _render_page(document, index: int) -> bytes:
    page = document[index]
    try:
        image_bytes = _render_jpeg(page)
    finally:
        page.close()
    if len(image_bytes) > config.MAX_RENDERED_IMAGE_BYTES:
        raise ValueError(
            error_messages.RENDERED_IMAGE_TOO_LARGE.format(max_image_megabytes=config.MAX_RENDERED_IMAGE_BYTES / 1000000)
        )
    return image_bytes


def _require_pdfium(mode: str):
    if pdfium is None:
        raise ValueError(
            error_messages.PDF_DEPENDENCY_REQUIRED.format(mode=mode)
        )
    return pdfium


@contextmanager
def _open_document(content: bytes, operation: str):
    pdfium_api = _require_pdfium("text" if operation == "read" else "images")
    try:
        with _RENDER_LOCK, pdfium_api.PdfDocument(content, password="") as document:
            yield document
    except pdfium_api.PdfiumError as error:
        if error.err_code == pdfium_api.raw.FPDF_ERR_PASSWORD:
            raise ValueError(
                error_messages.PASSWORD_PROTECTED_PDF
            ) from error
        raise ValueError(error_messages.PDF_OPERATION_FAILED.format(operation=operation)) from error


def _render_jpeg(page) -> bytes:
    width, height = (float(value) for value in page.get_size())
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise ValueError(error_messages.PDF_PAGE_DIMENSIONS_MUST_BE_FINITE_AND_POSITIVE)
    scale = min(2.0, config.MAX_IMAGE_EDGE / max(width, height))
    bitmap = page.render(scale=scale)
    try:
        with bitmap.to_pil() as image:
            with image.convert("RGB") as rgb_image:
                output = BytesIO()
                rgb_image.save(output, format="JPEG", quality=90)
                return output.getvalue()
    finally:
        bitmap.close()
