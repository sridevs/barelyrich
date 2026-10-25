from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExchangeRates:
    inr_rates: dict[str, tuple[Decimal, date]]
    as_of: date

    def conversion(self, currency: str, base: str) -> tuple[Decimal | None, date | None]:
        if currency == base:
            return Decimal(1), self.as_of
        rates = {**self.inr_rates, "INR": (Decimal(1), self.as_of)}
        if currency not in rates or base not in rates:
            return None, None
        rate = rates[currency][0] / rates[base][0]
        return rate, min(rates[currency][1], rates[base][1])
