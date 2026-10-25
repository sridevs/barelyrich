from __future__ import annotations

from src.log_messages import error as error_messages
from src.log_messages import warning

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from src.models.currencies import iso_currency_code
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import currency_code, decimal_value, observation_date
from src.models.statements.classifications import (
    ACCOUNT_SCOPES, BALANCE_ROLES, DATE_ROLES, IMPORTABLE_BALANCE_ROLES,
    IMPORTABLE_DATE_ROLES, _readable_role,
)


@dataclass(frozen=True)
class StatementBalance:
    """One AI-interpreted balance and classifications requiring human review."""

    balance: Decimal
    currency: str
    as_of: date
    balance_role: str
    account_scope: str
    date_role: str

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
        self._validate_classifications()

    def _validate_classifications(self) -> None:
        if self.balance_role not in BALANCE_ROLES:
            raise ValueError(error_messages.MODEL_RETURNED_AN_UNKNOWN_BALANCE_ROLE)
        if self.account_scope not in ACCOUNT_SCOPES:
            raise ValueError(error_messages.MODEL_RETURNED_AN_UNKNOWN_ACCOUNT_SCOPE)
        if self.date_role not in DATE_ROLES:
            raise ValueError(error_messages.MODEL_RETURNED_AN_UNKNOWN_DATE_ROLE)

    def to_snapshot(self, institution: str, alias: str, kind: str) -> BalanceSnapshot:
        return BalanceSnapshot(
            institution, alias, self.currency, self.balance, kind, self.as_of, "statement",
        )

    def review_warnings(self) -> tuple[str, ...]:
        candidates = (
            (self.balance_role not in IMPORTABLE_BALANCE_ROLES,
             warning.BALANCE_ROLE_REVIEW.format(role=_readable_role(self.balance_role))),
            (self.account_scope != "single_account",
             warning.ACCOUNT_SCOPE_REVIEW),
            (self.date_role not in IMPORTABLE_DATE_ROLES,
             warning.DATE_ROLE_REVIEW.format(role=_readable_role(self.date_role))),
        )
        return tuple(message for applies, message in candidates if applies)
