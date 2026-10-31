from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.log_messages import error as error_messages
from src.models.portfolio.precious_metal_price import PreciousMetalPrice
from src.models.portfolio.validation import decimal_value


@dataclass(frozen=True)
class PreciousMetalHolding:
    """A quantity of metal, measured in its price unit, valued at that price."""

    quantity: Decimal
    price: PreciousMetalPrice

    def __post_init__(self) -> None:
        if decimal_value(self.quantity, self.price.unit) <= 0:
            raise ValueError(error_messages.PRECIOUS_METAL_QUANTITY_MUST_BE_POSITIVE)

    def value(self) -> Decimal:
        return (self.quantity * self.price.price).quantize(Decimal("0.01"))
