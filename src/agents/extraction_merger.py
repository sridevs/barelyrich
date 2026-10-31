"""Combine per-chunk extractions into one statement."""

from src.agents.response import StatementParsingError
from src.log_messages import error as error_messages
from src.models.portfolio.validation import account_number
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution


class ExtractionMerger:
    """Append each chunk's rows to its account and keep one institution across chunks."""

    __slots__ = ("_accounts", "_institution")

    def __init__(self):
        self._accounts: dict[str, StatementAccount] = {}
        self._institution: StatementInstitution | None = None

    @property
    def institution(self) -> StatementInstitution | None:
        return self._institution

    def add(self, extracted: StatementExtraction, chunk: StatementDocument) -> None:
        self._merge_institution(extracted.institution, chunk)
        for account in extracted.accounts:
            number = account_number(account.number)
            existing = self._accounts.get(number)
            self._accounts[number] = existing.followed_by(account) if existing else account

    def result(self) -> StatementExtraction:
        return StatementExtraction(tuple(self._accounts.values()), self._institution)

    def _merge_institution(
        self, institution: StatementInstitution | None, chunk: StatementDocument,
    ) -> None:
        if not self._institution:
            self._institution = institution
        elif institution and institution.name.casefold() != self._institution.name.casefold():
            raise StatementParsingError(error_messages.STATEMENT_CHUNK_INSTITUTION_CONFLICT.format(
                page_range=chunk.page_range,
            ))
