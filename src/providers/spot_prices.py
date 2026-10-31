import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from src import config
from src.log_messages import error as error_messages
from src.models.dto.spot_quote import SpotQuote
from src.models.portfolio.validation import currency_code, decimal_value
from src.providers.network import is_transient_network_error
from src.retry import retry

_MAX_QUOTE_AGE = timedelta(days=1)
_MAX_CLOCK_SKEW = timedelta(minutes=5)


class SpotPriceFetchError(ValueError):
    """A live metal spot price could not be fetched or validated."""


class SpotPriceProvider(Protocol):
    """Source of live spot prices for pure metals, quoted per troy ounce."""

    @property
    def source(self) -> str: ...

    def fetch(self, symbol: str) -> SpotQuote: ...


class HistoricalSpotPriceProvider(Protocol):
    """Source of daily reference prices for pure metals on a past date, per troy ounce."""

    @property
    def source(self) -> str: ...

    def fetch_on(self, symbol: str, as_of: date) -> SpotQuote: ...


@retry((URLError, OSError), should_retry=is_transient_network_error)
def _read_quote_response(request: Request) -> bytes:
    with urlopen(request, timeout=config.SPOT_PRICE_TIMEOUT_SECONDS) as response:
        return response.read(config.MAX_SPOT_PRICE_RESPONSE_BYTES + 1)


class GoldApiSpotPriceProvider:
    """Fetch public gold-api.com spot quotes (XAU, XAG, ...) without sending account data."""

    @property
    def source(self) -> str:
        return "gold-api.com"

    def fetch(self, symbol: str) -> SpotQuote:
        request = Request(
            f"{config.SPOT_PRICE_URL}/{symbol}",
            headers={"User-Agent": "BarelyRich/0.1", "Accept": "application/json"},
        )
        content = _content(request)
        try:
            return _quote(json.loads(content, parse_float=Decimal), symbol)
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as error:
            raise SpotPriceFetchError(error_messages.SPOT_PRICE_RESPONSE_INVALID) from error


def _content(request: Request) -> bytes:
    try:
        content = _read_quote_response(request)
    except (URLError, TimeoutError, OSError) as error:
        raise SpotPriceFetchError(error_messages.SPOT_PRICE_SERVICE_UNAVAILABLE) from error
    if len(content) > config.MAX_SPOT_PRICE_RESPONSE_BYTES:
        raise SpotPriceFetchError(error_messages.SPOT_PRICE_RESPONSE_OVERSIZED)
    return content


def _quote(payload: dict, symbol: str) -> SpotQuote:
    price = decimal_value(payload["price"], symbol)
    if payload["symbol"] != symbol or price <= 0:
        raise ValueError(error_messages.SPOT_PRICE_RESPONSE_INVALID)
    observed_at = _current_time(payload["updatedAt"])
    return SpotQuote(symbol, currency_code(payload["currency"]), price, observed_at)


def _current_time(value: str) -> datetime:
    observed_at = datetime.fromisoformat(value)
    now = datetime.now(timezone.utc)
    if observed_at.utcoffset() is None or not (
        now - _MAX_QUOTE_AGE <= observed_at <= now + _MAX_CLOCK_SKEW
    ):
        raise ValueError(error_messages.SPOT_PRICE_RESPONSE_INVALID)
    return observed_at.astimezone(timezone.utc)
