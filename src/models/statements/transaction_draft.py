"""An editable, optionally incomplete transaction row."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.log_messages import error as error_messages
from src.models.statements.statement_balance import StatementBalance


@dataclass(frozen=True)
class TransactionDraft:
    balance: Decimal | None
    currency: str
    as_of: date
    withdrawal: Decimal | None = None
    deposit: Decimal | None = None
    description: str = ""

    def __post_init__(self):
        self._validated(self.balance or Decimal(0))

    def _validated(self, balance: Decimal) -> StatementBalance:
        return StatementBalance(
            balance, self.currency, self.as_of, self.withdrawal, self.deposit, self.description,
        )

    def to_balance(self) -> StatementBalance:
        if self.balance is None:
            raise ValueError(error_messages.STATEMENT_DRAFT_BALANCE_REQUIRED)
        return self._validated(self.balance)
