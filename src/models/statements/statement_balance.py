from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.log_messages import error as error_messages
from src.models.currencies import iso_currency_code
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import (
    currency_code,
    decimal_value,
    observation_date,
    transaction_movements,
)


@dataclass(frozen=True)
class StatementBalance:
    """One extracted transaction or balance requiring human review."""

    balance: Decimal
    currency: str
    as_of: date
    withdrawal: Decimal | None = None
    deposit: Decimal | None = None
    description: str = ""

    def __post_init__(self):
        if not isinstance(self.balance, Decimal):
            raise ValueError(error_messages.STATEMENT_BALANCE_MUST_BE_A_DECIMAL_VALUE)
        if not isinstance(self.currency, str):
            raise ValueError(error_messages.STATEMENT_CURRENCY_MUST_BE_A_THREE_LETTER_CODE)
        if type(self.as_of) is not date:
            raise ValueError(error_messages.STATEMENT_DATE_MUST_BE_A_DATE)
        decimal_value(self.balance, "Statement balance")
        currency_code(self.currency)
        iso_currency_code(self.currency)
        observation_date(self.as_of.isoformat())
        self._validate_movement()

    @property
    def is_transaction(self) -> bool:
        return self.withdrawal is not None or self.deposit is not None

    def _validate_movement(self) -> None:
        transaction_movements(self.withdrawal, self.deposit)
        if not isinstance(self.description, str) or len(self.description) > 2000:
            raise ValueError(error_messages.INVALID_TRANSACTION_DESCRIPTION)

    def to_snapshot(self, institution: str, alias: str, kind: str) -> BalanceSnapshot:
        return BalanceSnapshot(
            institution, alias, self.currency, self.balance, kind, self.as_of, "statement",
            withdrawal=self.withdrawal, deposit=self.deposit, description=self.description,
            transaction_key=self.transaction_key(), row_number=int(self.is_transaction),
        )

    def transaction_key(self, occurrence: int = 1) -> str:
        if not self.is_transaction:
            return ""
        identity = (
            self.as_of, self.currency, self.balance.normalize(),
            (self.withdrawal or Decimal(0)).normalize(),
            (self.deposit or Decimal(0)).normalize(), self.description, occurrence,
        )
        return hashlib.sha256(repr(identity).encode()).hexdigest()
