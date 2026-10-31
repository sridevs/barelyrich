from dataclasses import dataclass
from decimal import Decimal


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
