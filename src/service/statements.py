import logging
from time import perf_counter

from src.agents.statement_agent import StatementAgent
from src.inference.progress import report_stage
from src.log_messages import error as error_messages
from src.log_messages import info
from src.models.statements.statement_extraction import StatementExtraction
from src.readers.statement_reader import read_statement

LOGGER = logging.getLogger(__name__)


class StatementImportService:
    """Coordinate statement extraction without persisting extracted data."""

    def __init__(self, agent: StatementAgent):
        self._agent = agent

    def preview(
        self,
        file_name: str,
        content: bytes,
        password: str | None = None,
    ) -> StatementExtraction:
        started_at = perf_counter()
        report_stage("Reading statement")
        document = read_statement(file_name, content, password)
        LOGGER.info(
            info.DOCUMENT_PROCESSED,
            perf_counter() - started_at, len(document.pages),
        )
        statement_balance = self._agent.parse(document)
        if statement_balance.institution is None:
            raise ValueError(error_messages.STATEMENT_INSTITUTION_MISSING_NO_SAVE)
        return statement_balance
