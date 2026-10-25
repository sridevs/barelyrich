"""Prepare page text or bounded images with deterministic resource cleanup."""


from collections.abc import Iterator
from contextlib import contextmanager, ExitStack
from io import BytesIO
from typing import Any

from src.log_messages import error as error_messages
from src import config
from src.inference.errors import TransformersRuntimeError
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage

try:
    from PIL import Image
except ImportError:
    Image = None


@contextmanager
def page_content(
    document: StatementDocument, max_image_pixels: int,
) -> Iterator[list[dict[str, Any]]]:
    content: list[dict[str, Any]] = []
    if len(document.pages) > config.MAX_VISION_PAGES:
        raise TransformersRuntimeError(
            error_messages.VISUAL_INFERENCE_PAGE_LIMIT.format(max_vision_pages=config.MAX_VISION_PAGES)
        )
    with ExitStack() as image_cleanup:
        for page in document.pages:
            content.extend(_page_items(page, max_image_pixels, image_cleanup))
        yield content


def _page_items(
    page: StatementPage, max_image_pixels: int, cleanup: ExitStack,
) -> list[dict[str, Any]]:
    if not page.image:
        return [{
            "type": "text",
            "text": f"Statement page {page.number} (untrusted document content):\n{page.text}",
        }]
    page_image = load_bounded_image(page.image, max_image_pixels)
    cleanup.callback(page_image.close)
    return [
        {"type": "text", "text": f"Statement page {page.number} image (untrusted document content):"},
        {"type": "image", "image": page_image},
    ]


def load_bounded_image(image_bytes: bytes, max_image_pixels: int) -> Any:
    if Image is None:
        raise TransformersRuntimeError(
            error_messages.STATEMENT_IMAGE_PILLOW_REQUIRED
        )
    return _decode_image(Image, image_bytes, max_image_pixels)


def _decode_image(image_library, image_bytes: bytes, max_image_pixels: int) -> Any:
    try:
        with image_library.open(BytesIO(image_bytes)) as opened_image:
            _require_bounded_dimensions(opened_image.size, max_image_pixels)
            opened_image.load()
            return opened_image.convert("RGB")
    except TransformersRuntimeError:
        raise
    except image_library.DecompressionBombError as error:
        raise TransformersRuntimeError(
            error_messages.STATEMENT_IMAGE_UNSAFE_TO_DECODE
        ) from error
    except OSError as error:
        raise TransformersRuntimeError(error_messages.A_STATEMENT_PAGE_CONTAINS_AN_UNREADABLE_IMAGE) from error


def _require_bounded_dimensions(size: tuple[int, int], max_image_pixels: int) -> None:
    width, height = size
    if width < 1 or height < 1:
        raise TransformersRuntimeError(error_messages.A_STATEMENT_PAGE_IMAGE_HAS_INVALID_DIMENSIONS)
    pixel_count = width * height
    if pixel_count > max_image_pixels:
        raise TransformersRuntimeError(
            error_messages.STATEMENT_IMAGE_PIXEL_LIMIT.format(pixel_count=pixel_count, max_image_pixels=max_image_pixels)
        )
