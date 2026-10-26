
from typing import Protocol
import logging
from time import perf_counter

from src.log_messages import error as error_messages
from src.log_messages import info
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import institution_name
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction


LOGGER = logging.getLogger(__name__)


class StatementReader(Protocol):
    def read(
        self, file_name: str, content: bytes, password: str | None = None,
    ) -> StatementDocument: ...


class StatementAgent(Protocol):
    def parse(
        self,
        document: StatementDocument,
    ) -> StatementExtraction: ...


class StatementImportService:
    """Coordinate statement extraction without persisting extracted data."""

    def __init__(self, reader: StatementReader, agent: StatementAgent):
        self._reader = reader
        self._agent = agent

    def preview(
        self,
        file_name: str,
        content: bytes,
        password: str | None = None,
    ) -> StatementExtraction:
        started_at = perf_counter()
        document = (
            self._reader.read(file_name, content)
            if password is None else
            self._reader.read(file_name, content, password)
        )
        LOGGER.info(
            info.DOCUMENT_PROCESSED,
            perf_counter() - started_at, len(document.pages),
        )
        statement_balance = self._agent.parse(document)
        if statement_balance.institution is None:
            raise ValueError(error_messages.STATEMENT_INSTITUTION_MISSING_NO_SAVE)
        return statement_balance

    @staticmethod
    def to_snapshot(
        statement_balance: StatementBalance,
        institution: str,
        alias: str,
        kind: str,
    ) -> BalanceSnapshot:
        institution_name(institution)
        return statement_balance.to_snapshot(institution, alias, kind)
