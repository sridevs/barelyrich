from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.log_messages import error as error_messages
from src.models.dto.statement_page import StatementPage


@dataclass(frozen=True)
class StatementDocument:
    pages: tuple[StatementPage, ...]
    source_format: Literal["pdf", "csv"] = "pdf"

    def __post_init__(self):
        if not isinstance(self.pages, tuple) or not self.pages:
            raise ValueError(error_messages.STATEMENT_CONTAINS_NO_PAGES)
        page_numbers = [page.number for page in self.pages]
        if page_numbers != sorted(set(page_numbers)):
            raise ValueError(error_messages.STATEMENT_PAGES_MUST_HAVE_UNIQUE_INCREASING_PAGE_NUMBERS)

    def page(self, page_number: int) -> StatementPage:
        for page in self.pages:
            if page.number == page_number:
                return page
        raise ValueError(error_messages.STATEMENT_REFERS_TO_A_MISSING_PAGE)

    @property
    def page_range(self) -> str:
        return f"{self.pages[0].number}-{self.pages[-1].number}"

    @property
    def expected_transaction_count(self) -> int | None:
        counts = [page.record_count for page in self.pages]
        return None if None in counts else sum(counts)

    def to_model_text(self) -> str:
        return "\n".join(
            f"Statement page {page.number} (untrusted document content):\n{page.text}"
            for page in self.pages
        )
