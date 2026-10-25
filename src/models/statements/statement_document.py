from __future__ import annotations


from dataclasses import dataclass
from src.log_messages import error as error_messages
from src.models.statements.statement_page import StatementPage


@dataclass(frozen=True)
class StatementDocument:
    pages: tuple[StatementPage, ...]

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
    def text_only(self) -> bool:
        return all(not page.image for page in self.pages)
