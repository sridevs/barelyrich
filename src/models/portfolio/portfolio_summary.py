from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.portfolio.portfolio import Portfolio


@dataclass(frozen=True)
class PortfolioSummary:
    assets: Decimal
    liabilities: Decimal
    institution_totals: dict[str, Decimal]

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities

    def total_for(self, institution_key: str) -> Decimal:
        return self.institution_totals[institution_key]

    @classmethod
    def from_portfolio(cls, portfolio: Portfolio) -> "PortfolioSummary":
        return portfolio.summarize()
