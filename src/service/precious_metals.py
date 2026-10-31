from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from src.log_messages import error as error_messages
from src.models.dto.spot_quote import SpotQuote
from src.models.portfolio.precious_metal import PRICE_PRECISION, PreciousMetal
from src.models.portfolio.precious_metal_price import PreciousMetalPrice
from src.providers.exchange_rates import FrankfurterExchangeRateProvider
from src.providers.spot_prices import (
    HistoricalSpotPriceProvider,
    SpotPriceFetchError,
    SpotPriceProvider,
)
from src.repo.portfolio import PortfolioStore

TROY_OUNCE_GRAMS = Decimal("31.1034768")
PRICE_CURRENCY = "INR"


class PreciousMetalPricing:
    """Price metals per gram in INR on a given date and keep each observation.

    Today's price comes from a live spot quote; past dates use that day's reference price,
    so back-dated holdings are valued as they were then.
    """

    def __init__(
        self,
        spot_prices: SpotPriceProvider,
        historical_prices: HistoricalSpotPriceProvider,
        exchange_rates: FrankfurterExchangeRateProvider,
        writer: PortfolioStore,
    ):
        self._spot_prices = spot_prices
        self._historical_prices = historical_prices
        self._exchange_rates = exchange_rates
        self._writer = writer

    @property
    def database_path(self) -> Path:
        return self._writer.path

    def prices_on(self, metal: PreciousMetal, as_of: date) -> tuple[PreciousMetalPrice, ...]:
        if as_of < date.today():
            quote = self._historical_prices.fetch_on(metal.symbol, as_of)
            source = self._historical_prices.source
        else:
            quote = self._spot_prices.fetch(metal.symbol)
            source = self._spot_prices.source
        prices = metal.prices(
            _per_gram(quote.price * self._inr_rate(quote, as_of)),
            PRICE_CURRENCY, self._source(quote, source), quote.observed_at,
        )
        self._writer.save_precious_metal_prices(prices)
        return prices

    def _inr_rate(self, quote: SpotQuote, as_of: date) -> Decimal:
        if quote.currency == PRICE_CURRENCY:
            return Decimal(1)
        observations = self._exchange_rates.fetch({quote.currency}, min(as_of, date.today()))
        for observation in observations:
            if observation.currency == quote.currency:
                return observation.rate
        raise SpotPriceFetchError(error_messages.SPOT_PRICE_REQUIRES_INR_RATE)

    def _source(self, quote: SpotQuote, source: str) -> str:
        if quote.currency == PRICE_CURRENCY:
            return source
        return f"{source} + {self._exchange_rates.source}"


def _per_gram(price_per_troy_ounce: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return (price_per_troy_ounce / TROY_OUNCE_GRAMS).quantize(PRICE_PRECISION)
