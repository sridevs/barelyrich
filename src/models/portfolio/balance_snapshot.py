from __future__ import annotations


from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from src.log_messages import error as error_messages
from src.models.portfolio.validation import account_number
from src.models.portfolio.validation import account_product_type
from src.models.portfolio.validation import currency_code
from src.models.portfolio.validation import decimal_value
from src.models.portfolio.validation import institution_name


@dataclass(frozen=True)
class BalanceSnapshot:
    institution: str
    account: str
    currency: str
    balance: Decimal
    kind: str
    as_of: date
    source: str
    account_number: str | None = None
    product_type: str = ""

    @property
    def identity(self) -> tuple[str, str, date] | tuple[str, str, str, date]:
        if self.account_number is None:
            return self.institution, self.account, self.as_of
        return (
            self.institution, account_number(self.account_number), self.currency, self.as_of,
        )

    @property
    def is_liability(self) -> bool:
        return self.kind == "liability"

    def ensure_account_compatible(self, currency: str, is_liability: bool) -> None:
        if currency != self.currency or is_liability != self.is_liability:
            raise ValueError(
                error_messages.ACCOUNT_CURRENCY_OR_KIND_CHANGED
            )

    def __post_init__(self):
        institution_name(self.institution, max_length=300)
        account_product_type(self.product_type)
        if self.account_number is not None:
            account_number(self.account_number)
        if not self.account.strip() or len(self.account) > 100:
            raise ValueError(error_messages.ACCOUNT_ALIAS_MUST_CONTAIN_1_100_CHARACTERS)
        currency_code(self.currency)
        decimal_value(self.balance, "Balance")
        if self.kind not in {"asset", "liability"}:
            raise ValueError(error_messages.KIND_MUST_BE_ASSET_OR_LIABILITY)
        if self.is_liability and self.balance < 0:
            raise ValueError(error_messages.LIABILITIES_MUST_BE_ENTERED_AS_POSITIVE_AMOUNTS_OWED)
        self._validate_provenance()

    def _validate_provenance(self) -> None:
        if type(self.as_of) is not date or self.as_of > date.today():
            raise ValueError(error_messages.INVALID_OBSERVATION_DATE)
        if self.source not in {"manual", "csv", "statement", "tiger_api"}:
            raise ValueError(error_messages.UNSUPPORTED_BALANCE_SOURCE)
        if self.account != self.account.strip():
            raise ValueError(error_messages.REMOVE_LEADING_OR_TRAILING_WHITESPACE_FROM_THE_ACCOUNT_ALIAS)
