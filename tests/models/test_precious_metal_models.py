from datetime import date, datetime
from decimal import Decimal

import pytest

from src.models.entry.precious_metal_valuation import PreciousMetalValuation
from src.models.portfolio.precious_metal import PreciousMetal
from src.models.portfolio.precious_metal_holding import PreciousMetalHolding
from src.models.precious_metals import GOLD, PRECIOUS_METALS
from tests.metal_fixtures import OBSERVED_AT, gold_holding, gold_price


def test_gold_is_registered_with_24k_and_22k_purities():
    assert PRECIOUS_METALS["gold"] is GOLD
    assert GOLD.symbol == "XAU"
    assert GOLD.purity_labels == ("24K", "22K")


def test_purity_prices_scale_the_fine_price_by_fineness():
    prices = GOLD.prices(Decimal("12000"), "INR", "test", OBSERVED_AT)
    assert [(price.purity, price.price) for price in prices] == [
        ("24K", Decimal("12000.00000000")), ("22K", Decimal("11000.00000000")),
    ]
    assert all(price.unit == "gram" and price.metal == "gold" for price in prices)


@pytest.mark.parametrize("purities", [
    (), (("24K", Decimal(1)), ("24K", Decimal(1))),
    (("0K", Decimal(0)),), (("Over", Decimal("1.1")),),
])
def test_metal_rejects_invalid_purities(purities):
    with pytest.raises(ValueError, match="purities"):
        PreciousMetal("gold", "XAU", purities)


@pytest.mark.parametrize("changes,message", [
    ({"metal": " "}, "required"),
    ({"source": ""}, "required"),
    ({"currency": "XX"}, "Currency"),
    ({"price": "0"}, "positive"),
    ({"observed_at": datetime(2026, 1, 10)}, "timezone"),
])
def test_price_validates_fields(changes, message):
    with pytest.raises(ValueError, match=message):
        gold_price(**changes)


def test_price_exposes_iso_observation_time():
    assert gold_price().observation_time == "2026-01-10T09:30:00+00:00"


def test_holding_values_quantity_at_rate_rounded_to_paise():
    assert gold_holding("10.5", price="11000.12345").value() == Decimal("115501.30")


@pytest.mark.parametrize("quantity", ["0", "-1"])
def test_holding_requires_positive_quantity(quantity):
    with pytest.raises(ValueError, match="positive"):
        PreciousMetalHolding(Decimal(quantity), gold_price())


def test_valuation_snapshot_is_a_manual_inr_asset():
    snapshot = PreciousMetalValuation(
        "Precious metals", "Gold", gold_holding("2"), date(2026, 1, 10),
    ).snapshot()
    assert (snapshot.institution, snapshot.account, snapshot.currency) == (
        "Precious metals", "Gold", "INR",
    )
    assert (snapshot.balance, snapshot.kind, snapshot.source) == (
        Decimal("24000.00"), "asset", "manual",
    )


def test_valuation_requires_a_name():
    valuation = PreciousMetalValuation("Precious metals", " ", gold_holding(), date(2026, 1, 10))
    with pytest.raises(ValueError, match="Asset name"):
        valuation.snapshot()
