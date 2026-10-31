from datetime import date, datetime, timedelta, timezone
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


class FakeHistoricalPrices:
    source = "history.test"

    def __init__(self, quote: SpotQuote):
        self._quote = quote
        self.requests: list[tuple[str, date]] = []

    def fetch_on(self, symbol: str, as_of: date) -> SpotQuote:
        self.requests.append((symbol, as_of))
        return self._quote


class FakeExchangeRates:
    source = "fx.test"

    def __init__(self, observations=()):
        self._observations = observations
        self.requests: list[set[str]] = []
        self.dates: list[date] = []

    def fetch(self, currencies: set[str], as_of: date):
        self.requests.append(currencies)
        self.dates.append(as_of)
        return self._observations


PURCHASE_DATE = date(2024, 1, 3)
PUBLISHED_AT = datetime(2024, 1, 2, tzinfo=timezone.utc)


def pricing_for(
    store, currency="USD", price=TROY_OUNCE_GRAMS * 30, observations=(), historical_currency="INR",
):
    spot = FakeSpotPrices(SpotQuote("XAU", currency, Decimal(price), OBSERVED_AT))
    history = FakeHistoricalPrices(SpotQuote(
        "XAU", historical_currency, TROY_OUNCE_GRAMS * 48, PUBLISHED_AT,
    ))
    rates = FakeExchangeRates(observations)
    return PreciousMetalPricing(spot, history, rates, store), spot, history, rates


def saved_prices(db_path):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT purity, currency, unit, price, source, observed_at FROM precious_metal_prices"
            " ORDER BY purity",
        ).fetchall()
    return [tuple(row) for row in rows]


def test_usd_quote_is_converted_to_inr_per_gram_for_each_purity(store, db_path):
    usd = ExchangeRateObservation("USD", Decimal("80"), date.today())
    pricing, spot, _, rates = pricing_for(store, observations=(usd,))
    prices = pricing.prices_on(GOLD, date.today())
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
    pricing, _, _, rates = pricing_for(store, currency="INR")
    prices = pricing.prices_on(GOLD, date.today())
    assert rates.requests == []
    assert prices[0].price == Decimal("30.00000000")
    assert prices[0].source == "spot.test"


def test_missing_inr_rate_is_reported_and_nothing_is_saved(store, db_path):
    pricing, _, _, _ = pricing_for(store)
    with pytest.raises(SpotPriceFetchError, match="INR exchange rate"):
        pricing.prices_on(GOLD, date.today())
    assert saved_prices(db_path) == []


def test_pricing_exposes_its_database_for_cache_isolation(store, db_path):
    pricing, _, _, _ = pricing_for(store)
    assert pricing.database_path == db_path


def test_past_date_is_priced_from_that_days_reference_rate(store, db_path):
    pricing, spot, history, rates = pricing_for(store)
    prices = pricing.prices_on(GOLD, PURCHASE_DATE)
    assert history.requests == [("XAU", PURCHASE_DATE)]
    assert spot.symbols == []
    assert rates.requests == []
    assert [(price.purity, price.price) for price in prices] == [
        ("24K", Decimal("48.00000000")), ("22K", Decimal("44.00000000")),
    ]
    assert {(price.source, price.observed_at) for price in prices} == {("history.test", PUBLISHED_AT)}
    assert len(saved_prices(db_path)) == 2


def test_past_foreign_quote_is_converted_at_the_valuation_date_rate(store):
    usd = ExchangeRateObservation("USD", Decimal("80"), PURCHASE_DATE)
    pricing, _, _, rates = pricing_for(
        store, observations=(usd,), historical_currency="USD",
    )
    prices = pricing.prices_on(GOLD, PURCHASE_DATE)
    assert rates.dates == [PURCHASE_DATE]
    assert prices[0].price == Decimal("3840.00000000")
    assert prices[0].source == "history.test + fx.test"


def test_today_uses_the_live_quote_and_todays_exchange_rate(store):
    usd = ExchangeRateObservation("USD", Decimal("80"), date.today())
    pricing, spot, history, rates = pricing_for(store, observations=(usd,))
    pricing.prices_on(GOLD, date.today())
    assert (spot.symbols, history.requests, rates.dates) == (["XAU"], [], [date.today()])


def test_future_date_uses_the_live_quote_with_todays_exchange_rate(store):
    usd = ExchangeRateObservation("USD", Decimal("80"), date.today())
    pricing, spot, _, rates = pricing_for(store, observations=(usd,))
    pricing.prices_on(GOLD, date.today() + timedelta(days=1))
    assert (spot.symbols, rates.dates) == (["XAU"], [date.today()])
