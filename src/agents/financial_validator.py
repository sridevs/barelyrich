"""Ask the model to correct output that fails domain or transaction-count checks."""

import logging

from pydantic_ai import ModelRetry

from src.agents.output import StatementOutput
from src.agents.response import DOMAIN_RETRY_FEEDBACK
from src.log_messages import error as error_messages
from src.log_messages import warning
from src.models.statements.errors import DuplicateStatementCurrency
from src.models.statements.statement_extraction import StatementExtraction

LOGGER = logging.getLogger(__name__)


class FinancialOutputValidator:
    """Turn domain failures into retry feedback and remember the last one for the final error."""

    __slots__ = ("_expected_transactions", "_last_issue")

    def __init__(self, expected_transactions: int | None = None):
        self._expected_transactions = expected_transactions
        self._last_issue = ""

    def validate(self, candidate: StatementOutput) -> StatementOutput:
        try:
            self._validate_transaction_count(self._to_domain(candidate))
        except ModelRetry as error:
            self._last_issue = str(error)
            LOGGER.warning(warning.FINANCIAL_CORRECTION, self._last_issue)
            raise
        return candidate

    def failure_message(self) -> str:
        if not self._last_issue:
            return error_messages.STATEMENT_VALIDATION_EXHAUSTED
        return error_messages.STATEMENT_VALIDATION_EXHAUSTED + error_messages.LAST_FINANCIAL_ISSUE.format(
            issue=self._last_issue,
        )

    @staticmethod
    def _to_domain(output: StatementOutput) -> StatementExtraction:
        try:
            return output.to_domain()
        except DuplicateStatementCurrency:
            raise ModelRetry(error_messages.DUPLICATE_CURRENCY_RETRY_FEEDBACK) from None
        except ValueError as failure:
            raise ModelRetry(error_messages.FINANCIAL_VALIDATION_RETRY.format(
                guidance=DOMAIN_RETRY_FEEDBACK, failure=failure,
            )) from None

    def _validate_transaction_count(self, extraction: StatementExtraction) -> None:
        actual = sum(balance.is_transaction for balance in extraction.balances)
        if self._expected_transactions is None or actual == self._expected_transactions:
            return
        raise ModelRetry(error_messages.TRANSACTION_COUNT_MISMATCH_RETRY_FEEDBACK.format(
            expected=self._expected_transactions, actual=actual,
        ))
