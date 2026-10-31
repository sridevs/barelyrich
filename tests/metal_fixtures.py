"""Shared precious-metal prices and holdings for tests."""

from datetime import datetime, timezone
from decimal import Decimal

from src.models.portfolio.precious_metal_holding import PreciousMetalHolding
from src.models.portfolio.precious_metal_price import PreciousMetalPrice

OBSERVED_AT = datetime(2026, 1, 10, 9, 30, tzinfo=timezone.utc)


def gold_price(purity="22K", price="12000", observed_at=OBSERVED_AT, **changes):
    values = dict(
        metal="gold", purity=purity, currency="INR", unit="gram", price=Decimal(price),
        source="gold-api.com + frankfurter.dev", observed_at=observed_at,
    )
    values.update(changes)
    return PreciousMetalPrice(**values)


def gold_holding(quantity="10.5", **changes):
    return PreciousMetalHolding(Decimal(quantity), gold_price(**changes))
