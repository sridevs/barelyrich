from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.models.dto.spot_quote import SpotQuote
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.providers.exchange_rates import ExchangeRateFetchError
from src.providers.frankfurter_spot_prices import FrankfurterSpotPriceProvider

PURCHASE_DATE = date(2024, 1, 3)
PUBLISHED_DATE = date(2024, 1, 2)


class FakeExchangeRates:
    source = "frankfurter.dev"

    def __init__(self, outcome):
        self._outcome = outcome
        self.requests: list[tuple[set[str], date]] = []

    def fetch(self, currencies: set[str], as_of: date):
        self.requests.append((currencies, as_of))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def test_metal_is_fetched_as_a_dated_inr_reference_rate():
    rates = FakeExchangeRates((ExchangeRateObservation("XAU", Decimal("172611"), PUBLISHED_DATE),))
    quote = FrankfurterSpotPriceProvider(rates).fetch_on("XAU", PURCHASE_DATE)
    assert rates.requests == [({"XAU"}, PURCHASE_DATE)]
    assert quote == SpotQuote(
        "XAU", "INR", Decimal("172611"), datetime(2024, 1, 2, tzinfo=timezone.utc),
    )


def test_source_is_the_exchange_rate_service():
    assert FrankfurterSpotPriceProvider(FakeExchangeRates(())).source == "frankfurter.dev"


def test_default_provider_uses_frankfurter():
    assert FrankfurterSpotPriceProvider().source == "frankfurter.dev"


def test_rate_service_failures_propagate():
    rates = FakeExchangeRates(ExchangeRateFetchError("unavailable"))
    with pytest.raises(ExchangeRateFetchError, match="unavailable"):
        FrankfurterSpotPriceProvider(rates).fetch_on("XAU", PURCHASE_DATE)
