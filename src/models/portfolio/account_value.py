from __future__ import annotations


from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from src.log_messages import error as error_messages
from src import config
from src.models.portfolio.institution import Institution


@dataclass(frozen=True)
class AccountValue:
    account: str
    institution: str
    currency: str
    balance: Decimal
    kind: str
    as_of: date
    source: str
    recorded_at: str
    rate: Decimal | None
    rate_date: date | None
    institution_name: str = ""
    country: str = ""
    account_type: str = "other"
    account_number: str | None = None
    product_type: str = ""

    def institution_record(self) -> Institution:
        return Institution(
            self.institution, self.institution_name or self.institution,
            self.country, self.account_type,
        )

    @property
    def is_liability(self) -> bool:
        return self.kind == "liability"

    @property
    def has_conversion(self) -> bool:
        return self.rate is not None

    @property
    def api_fetch_time(self) -> str | None:
        return self.recorded_at if self.source == "tiger_api" else None

    def is_stale(self, as_of: date, days: int | None = None) -> bool:
        days = config.STALE_AFTER_DAYS if days is None else days
        return (as_of - self.as_of).days > days

    def has_stale_fx(self, base: str, as_of: date, days: int | None = None) -> bool:
        days = config.STALE_AFTER_DAYS if days is None else days
        if not self.rate_date:
            return False
        return (
                self.currency != base
                and (as_of - self.rate_date).days > days
        )

    def require_net_value(self) -> Decimal:
        value = self.net_value
        if value is None:
            raise ValueError(error_messages.A_PORTFOLIO_ACCOUNT_HAS_NO_EXCHANGE_RATE)
        return value

    @property
    def net_value(self) -> Decimal | None:
        if self.rate is None:
            return None
        return self.balance * self.rate * (-1 if self.is_liability else 1)
