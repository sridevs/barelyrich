from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from src.log_messages import error as error_messages
from src.models.dto.spot_quote import SpotQuote
from src.models.portfolio.precious_metal import PRICE_PRECISION, PreciousMetal
from src.models.portfolio.precious_metal_price import PreciousMetalPrice
from src.providers.exchange_rates import FrankfurterExchangeRateProvider
from src.providers.spot_prices import SpotPriceFetchError, SpotPriceProvider
from src.repo.portfolio import PortfolioStore

TROY_OUNCE_GRAMS = Decimal("31.1034768")
PRICE_CURRENCY = "INR"


class PreciousMetalPricing:
    """Price metals per gram in INR from a live spot quote and keep each observation."""

    def __init__(
        self,
        spot_prices: SpotPriceProvider,
        exchange_rates: FrankfurterExchangeRateProvider,
        writer: PortfolioStore,
    ):
        self._spot_prices = spot_prices
        self._exchange_rates = exchange_rates
        self._writer = writer

    @property
    def database_path(self) -> Path:
        return self._writer.path

    def current_prices(self, metal: PreciousMetal) -> tuple[PreciousMetalPrice, ...]:
        quote = self._spot_prices.fetch(metal.symbol)
        prices = metal.prices(
            _per_gram(quote.price * self._inr_rate(quote)),
            PRICE_CURRENCY, self._source(quote), quote.observed_at,
        )
        self._writer.save_precious_metal_prices(prices)
        return prices

    def _inr_rate(self, quote: SpotQuote) -> Decimal:
        if quote.currency == PRICE_CURRENCY:
            return Decimal(1)
        observations = self._exchange_rates.fetch({quote.currency}, date.today())
        for observation in observations:
            if observation.currency == quote.currency:
                return observation.rate
        raise SpotPriceFetchError(error_messages.SPOT_PRICE_REQUIRES_INR_RATE)

    def _source(self, quote: SpotQuote) -> str:
        if quote.currency == PRICE_CURRENCY:
            return self._spot_prices.source
        return f"{self._spot_prices.source} + {self._exchange_rates.source}"


def _per_gram(price_per_troy_ounce: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return (price_per_troy_ounce / TROY_OUNCE_GRAMS).quantize(PRICE_PRECISION)
