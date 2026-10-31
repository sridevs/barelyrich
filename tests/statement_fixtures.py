"""Statement output fixtures for tests that do not run local inference."""

import json
from datetime import date
from decimal import Decimal

from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution


def statement_extraction() -> StatementExtraction:
    return StatementExtraction((
        StatementAccount(
            "TEST1234", (
                StatementBalance(
                    Decimal("1234.50"), "SGD", date.today(),
                ),
            ),
        ),
    ), StatementInstitution("DBS Singapore"))


def text_document(text: str = "statement text") -> StatementDocument:
    return StatementDocument((StatementPage(1, text),))


class RepairingRuntime:
    """Answers with `first` row, then with `repaired` once the agent retries."""

    def __init__(self, first: list, repaired: list):
        self.prompts = []
        self._rows = (first, repaired)

    def generate(self, document, prompt):
        self.prompts.append(prompt)
        return json.dumps({
            "institution": {"name": "Example Bank"},
            "accounts": [{
                "number": "1234", "account_type": "Savings",
                "balances": [self._rows[len(self.prompts) > 1]],
            }],
        })
