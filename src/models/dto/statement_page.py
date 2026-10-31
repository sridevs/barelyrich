from __future__ import annotations

from dataclasses import dataclass

from src.log_messages import error as error_messages


@dataclass(frozen=True)
class StatementPage:
    number: int
    text: str
    record_count: int | None = None

    def __post_init__(self):
        if type(self.number) is not int or self.number < 1:
            raise ValueError(error_messages.STATEMENT_PAGE_NUMBERS_MUST_BE_POSITIVE_INTEGERS)
        if self.record_count is not None and (type(self.record_count) is not int or self.record_count < 0):
            raise ValueError(error_messages.STATEMENT_PAGE_RECORD_COUNT_INVALID)
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError(error_messages.STATEMENT_PAGE_TEXT_REQUIRED)
