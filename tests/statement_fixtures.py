"""Statement output fixtures for tests that do not run local inference."""

from datetime import date
from decimal import Decimal

from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution


def statement_extraction() -> StatementExtraction:
    return StatementExtraction((
        StatementAccount(
            "TEST1234", (
                StatementBalance(
                    Decimal("1234.50"), "SGD", date.today(),
                    "closing_balance", "single_account", "statement_date",
                ),
            ),
        ),
    ), StatementInstitution("DBS Singapore"))
