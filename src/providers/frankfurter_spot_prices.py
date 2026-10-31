from datetime import date, datetime, time, timezone

from src.models.dto.spot_quote import SpotQuote
from src.providers.exchange_rates import FrankfurterExchangeRateProvider


class FrankfurterSpotPriceProvider:
    """Daily metal reference prices (XAU, XAG, ...) in INR, published like currencies."""

    def __init__(self, exchange_rates: FrankfurterExchangeRateProvider | None = None):
        self._exchange_rates = exchange_rates or FrankfurterExchangeRateProvider()

    @property
    def source(self) -> str:
        return self._exchange_rates.source

    def fetch_on(self, symbol: str, as_of: date) -> SpotQuote:
        (observation,) = self._exchange_rates.fetch({symbol}, as_of)
        observed_at = datetime.combine(observation.as_of, time.min, timezone.utc)
        return SpotQuote(symbol, "INR", observation.rate, observed_at)
