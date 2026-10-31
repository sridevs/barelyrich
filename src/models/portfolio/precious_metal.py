from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.log_messages import error as error_messages
from src.models.portfolio.precious_metal_price import PreciousMetalPrice

PRICE_PRECISION = Decimal("0.00000001")


@dataclass(frozen=True)
class PreciousMetal:
    """A tradable metal: its spot symbol and the purities it is held in."""

    name: str
    symbol: str
    purities: tuple[tuple[str, Decimal], ...]

    def __post_init__(self) -> None:
        labels = [label for label, _ in self.purities]
        if not labels or len(set(labels)) != len(labels) or any(
            not 0 < fineness <= 1 for _, fineness in self.purities
        ):
            raise ValueError(error_messages.PRECIOUS_METAL_PURITY_INVALID)

    @property
    def purity_labels(self) -> tuple[str, ...]:
        return tuple(label for label, _ in self.purities)

    def prices(
        self, fine_price: Decimal, currency: str, source: str, observed_at: datetime,
    ) -> tuple[PreciousMetalPrice, ...]:
        """Price every purity from the price of the pure (fineness 1) metal per gram."""
        return tuple(
            PreciousMetalPrice(
                self.name, label, currency, "gram",
                (fine_price * fineness).quantize(PRICE_PRECISION), source, observed_at,
            )
            for label, fineness in self.purities
        )
