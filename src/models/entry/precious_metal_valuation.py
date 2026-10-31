from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.models.entry.validation import required_date, required_text
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.precious_metal_holding import PreciousMetalHolding


@dataclass(frozen=True)
class PreciousMetalValuation:
    group: str
    name: str
    holding: PreciousMetalHolding
    as_of: date

    def snapshot(self) -> BalanceSnapshot:
        return BalanceSnapshot(
            required_text(self.group, "Asset group"),
            required_text(self.name, "Asset name"),
            self.holding.price.currency,
            self.holding.value(),
            "asset",
            required_date(self.as_of, "a balance as-of date"),
            "manual",
        )
