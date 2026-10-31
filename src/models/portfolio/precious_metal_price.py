from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.log_messages import error as error_messages
from src.models.portfolio.validation import currency_code, decimal_value


@dataclass(frozen=True)
class PreciousMetalPrice:
    """A dated, sourced price for one unit of a metal at a given purity."""

    metal: str
    purity: str
    currency: str
    unit: str
    price: Decimal
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not all(item.strip() for item in (self.metal, self.purity, self.unit, self.source)):
            raise ValueError(error_messages.PRECIOUS_METAL_PRICE_FIELDS_REQUIRED)
        currency_code(self.currency)
        if decimal_value(self.price, self.metal) <= 0:
            raise ValueError(error_messages.PRECIOUS_METAL_PRICE_MUST_BE_POSITIVE)
        if self.observed_at.utcoffset() is None:
            raise ValueError(error_messages.PRECIOUS_METAL_PRICE_TIMEZONE_REQUIRED)

    @property
    def observation_time(self) -> str:
        return self.observed_at.isoformat()
