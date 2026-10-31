from __future__ import annotations

from dataclasses import dataclass

from src.models.entry.validation import required_date, required_text
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import decimal_value


@dataclass(frozen=True)
class ManualBalance:
    institution: str
    alias: str | None
    currency: str | None
    amount: str | None
    kind: str
    as_of: object

    def snapshot(self) -> BalanceSnapshot:
        as_of = required_date(self.as_of, "a balance as-of date")
        return BalanceSnapshot(
            self.institution, required_text(self.alias, "Account name"),
            required_text(self.currency, "Account currency"),
            decimal_value(required_text(self.amount, "Balance"), "Balance"),
            self.kind, as_of, "manual",
        )
