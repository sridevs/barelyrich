from datetime import date
from decimal import Decimal

import pytest

from src.models.dto.spot_quote import SpotQuote
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.precious_metals import GOLD
from src.providers.spot_prices import SpotPriceFetchError
from src.repo.db import connect
from src.service.precious_metals import TROY_OUNCE_GRAMS, PreciousMetalPricing
from tests.metal_fixtures import OBSERVED_AT


class FakeSpotPrices:
    source = "spot.test"

    def __init__(self, quote: SpotQuote):
        self._quote = quote
        self.symbols: list[str] = []

    def fetch(self, symbol: str) -> SpotQuote:
        self.symbols.append(symbol)
        return self._quote


class FakeExchangeRates:
    source = "fx.test"

    def __init__(self, observations=()):
        self._observations = observations
        self.requests: list[set[str]] = []

    def fetch(self, currencies: set[str], as_of: date):
        self.requests.append(currencies)
        return self._observations


def pricing_for(store, currency="USD", price=TROY_OUNCE_GRAMS * 30, observations=()):
    spot = FakeSpotPrices(SpotQuote("XAU", currency, Decimal(price), OBSERVED_AT))
    rates = FakeExchangeRates(observations)
    return PreciousMetalPricing(spot, rates, store), spot, rates


def saved_prices(db_path):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT purity, currency, unit, price, source, observed_at FROM precious_metal_prices"
            " ORDER BY purity",
        ).fetchall()
    return [tuple(row) for row in rows]


def test_usd_quote_is_converted_to_inr_per_gram_for_each_purity(store, db_path):
    usd = ExchangeRateObservation("USD", Decimal("80"), date.today())
    pricing, spot, rates = pricing_for(store, observations=(usd,))
    prices = pricing.current_prices(GOLD)
    assert spot.symbols == ["XAU"]
    assert rates.requests == [{"USD"}]
    assert [(price.purity, price.price) for price in prices] == [
        ("24K", Decimal("2400.00000000")), ("22K", Decimal("2200.00000000")),
    ]
    assert {price.source for price in prices} == {"spot.test + fx.test"}
    assert saved_prices(db_path) == [
        ("22K", "INR", "gram", "2200.00000000", "spot.test + fx.test", OBSERVED_AT.isoformat()),
        ("24K", "INR", "gram", "2400.00000000", "spot.test + fx.test", OBSERVED_AT.isoformat()),
    ]


def test_inr_quote_needs_no_exchange_rate(store):
    pricing, _, rates = pricing_for(store, currency="INR")
    prices = pricing.current_prices(GOLD)
    assert rates.requests == []
    assert prices[0].price == Decimal("30.00000000")
    assert prices[0].source == "spot.test"


def test_missing_inr_rate_is_reported_and_nothing_is_saved(store, db_path):
    pricing, _, _ = pricing_for(store)
    with pytest.raises(SpotPriceFetchError, match="INR exchange rate"):
        pricing.current_prices(GOLD)
    assert saved_prices(db_path) == []


def test_pricing_exposes_its_database_for_cache_isolation(store, db_path):
    pricing, _, _ = pricing_for(store)
    assert pricing.database_path == db_path
