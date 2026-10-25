
from collections.abc import Iterable
from datetime import date

from src.log_messages import error as error_messages
from src.models.entry.manual_balance import ManualBalance
from src.models.entry.validation import required_date, required_text
from src.models.history.history_point import HistoryPoint
from src.models.entry.statement_review import StatementReview
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.institution import Institution
from src.repo.contracts import BalanceWriter, PortfolioReader


class PortfolioActions:
    def __init__(self, writer: BalanceWriter):
        self._writer = writer

    def institutions(self) -> tuple[Institution, ...]:
        return self._writer.institutions()

    def save_manual(self, command: ManualBalance) -> None:
        self._writer.save([command.snapshot()])

    def save_statement(self, snapshot: BalanceSnapshot) -> None:
        if snapshot.source != "statement":
            raise ValueError(error_messages.STATEMENT_IMPORT_REQUIRES_A_STATEMENT_SOURCED_BALANCE)
        self._writer.save([snapshot])

    def save_statement_balances(self, snapshots: list[BalanceSnapshot]) -> int:
        if not snapshots or any(snapshot.source != "statement" for snapshot in snapshots):
            raise ValueError(error_messages.STATEMENT_IMPORT_REQUIRES_STATEMENT_SOURCED_BALANCES)
        return self._writer.save(snapshots)

    def save_statement_review(
        self, review: StatementReview, alias: str | dict[str, str], institution: str,
    ) -> int:
        return self._writer.save_statement(review, alias, institution)

    def save_rate(self, currency: str | None, rate: str | None, as_of: object) -> None:
        rate_date = required_date(as_of, "an FX rate date")
        self._writer.save_rate(
            required_text(currency, "Foreign currency"),
            required_text(rate, "FX rate"), rate_date,
        )


class PortfolioHistory:
    def __init__(self, reader: PortfolioReader):
        self._reader = reader

    def at_dates(self, dates: Iterable[date], currency: str) -> tuple[HistoryPoint, ...]:
        points = []
        for day in sorted(set(dates)):
            value = self._reader.portfolio(day, currency).net_worth
            if value is None:
                raise ValueError(
                    error_messages.HISTORICAL_NET_WORTH_UNAVAILABLE.format(day=day)
                )
            points.append(HistoryPoint(day, value))
        return tuple(points)
