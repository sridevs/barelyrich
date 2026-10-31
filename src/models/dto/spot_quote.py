from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SpotQuote:
    """Market spot price of a pure metal per troy ounce."""

    symbol: str
    currency: str
    price: Decimal
    observed_at: datetime
