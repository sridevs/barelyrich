from datetime import date
from typing import Protocol

from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.institution import Institution
from src.models.portfolio.portfolio import Portfolio
from src.models.entry.statement_review import StatementReview


class PortfolioReader(Protocol):
    def portfolio(self, as_of: date, base_currency: str | None = None) -> Portfolio: ...


class BalanceWriter(Protocol):
    def institutions(self) -> tuple[Institution, ...]: ...

    def save(self, snapshots: list[BalanceSnapshot]) -> int: ...

    def save_statement(
        self, review: StatementReview, alias: str | dict[str, str], institution: str,
    ) -> int: ...

    def save_rate(self, currency: str, rate: str, as_of: date) -> None: ...


class ExchangeRateWriter(Protocol):
    def save_fetched_rates(self, observations: tuple[ExchangeRateObservation, ...]) -> None: ...

    def historical_fx_currencies(self, as_of: date) -> set[str]: ...

    def save_historical_rates(
        self, observations: tuple[ExchangeRateObservation, ...], requested_date: date,
    ) -> None: ...
