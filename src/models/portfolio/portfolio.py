from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.log_messages import error as error_messages
from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.institution import Institution
from src.models.portfolio.portfolio_summary import PortfolioSummary


@dataclass(frozen=True)
class Portfolio:
    accounts: tuple[AccountValue, ...]
    base_currency: str
    as_of: date

    def institutions(self) -> tuple[Institution, ...]:
        records = {account.institution: account.institution_record() for account in self.accounts}
        return tuple(sorted(records.values(), key=lambda item: item.normalized_name))

    def accounts_for(self, institution: Institution) -> tuple[AccountValue, ...]:
        return tuple(account for account in self.accounts if account.institution == institution.key)

    def stale_accounts(self, days: int | None = None) -> tuple[AccountValue, ...]:
        return tuple(account for account in self.accounts if account.is_stale(self.as_of, days))

    def stale_currencies(self, days: int | None = None) -> tuple[str, ...]:
        return tuple(sorted({
            account.currency for account in self.accounts
            if account.has_stale_fx(self.base_currency, self.as_of, days)
        }))

    def required_rate_currencies(self) -> set[str]:
        currencies = {
            account.currency for account in self.accounts
            if account.currency != self.base_currency
        }
        if not currencies:
            return set()
        return (currencies | {self.base_currency}) - {"INR"}

    def summarize(self) -> "PortfolioSummary":
        if not self.accounts:
            raise ValueError(error_messages.PORTFOLIO_HAS_NO_ACCOUNT_BALANCES)
        assets, liabilities = Decimal(0), Decimal(0)
        totals: dict[str, Decimal] = {}
        for account in self.accounts:
            value = account.require_net_value()
            if account.is_liability:
                liabilities -= value
            else:
                assets += value
            totals[account.institution] = totals.get(account.institution, Decimal(0)) + value
        return PortfolioSummary(assets, liabilities, totals)

    @property
    def missing_currencies(self) -> tuple[str, ...]:
        return tuple(sorted({row.currency for row in self.accounts if not row.has_conversion}))

    @property
    def net_worth(self) -> Decimal | None:
        if not self.accounts or self.missing_currencies:
            return None
        total = Decimal(0)
        for row in self.accounts:
            value = row.net_value
            if value is None:
                return None
            total += value
        return total
