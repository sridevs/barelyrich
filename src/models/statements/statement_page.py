from __future__ import annotations


from dataclasses import dataclass
from src.log_messages import error as error_messages
from src import config


@dataclass(frozen=True)
class StatementPage:
    number: int
    image: bytes
    text: str = ""

    def __post_init__(self):
        if type(self.number) is not int or self.number < 1:
            raise ValueError(error_messages.STATEMENT_PAGE_NUMBERS_MUST_BE_POSITIVE_INTEGERS)
        if (
                not isinstance(self.text, str)
                or not isinstance(self.image, bytes) or (not self.image and not self.text.strip())
                or len(self.image) > config.MAX_RENDERED_IMAGE_BYTES
        ):
            raise ValueError(
                error_messages.STATEMENT_PAGE_IMAGE_BYTE_LIMIT.format(max_image_megabytes=config.MAX_RENDERED_IMAGE_BYTES / 1000000)
            )
