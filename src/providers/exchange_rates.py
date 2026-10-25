
from datetime import date
from decimal import Decimal, localcontext
import errno
import json
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.log_messages import error as error_messages
from src import config
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.validation import currency_code, observation_date
from src.retry import retry


def _is_transient_network_error(error: Exception) -> bool:
    if isinstance(error, HTTPError):
        return _is_transient_http_error(error)
    if isinstance(error, URLError):
        return (
            _is_transient_network_error(error.reason)
            if isinstance(error.reason, Exception) else True
        )
    if isinstance(error, ssl.SSLError):
        return False
    if isinstance(error, socket.gaierror):
        return error.errno == socket.EAI_AGAIN
    return isinstance(error, (TimeoutError, ConnectionError)) or (
        isinstance(error, OSError)
        and error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT}
    )


def _is_transient_http_error(error: HTTPError) -> bool:
    transient = error.code in {408, 429, 500, 502, 503, 504}
    error.close()
    return transient


@retry((URLError, OSError), should_retry=_is_transient_network_error)
def _read_rate_response(request: Request) -> bytes:
    with urlopen(request, timeout=config.FX_TIMEOUT_SECONDS) as response:
        return response.read(config.MAX_FX_RESPONSE_BYTES + 1)


class ExchangeRateFetchError(ValueError):
    """Public exchange rates could not be fetched or validated."""


class FrankfurterExchangeRateProvider:
    """Fetch public daily reference rates, without sending account data."""

    def fetch(
        self, currencies: set[str], as_of: date,
    ) -> tuple[ExchangeRateObservation, ...]:
        observation_date(as_of.isoformat())
        foreign_currencies = currencies - {"INR"}
        for currency in foreign_currencies:
            currency_code(currency)
        if not foreign_currencies:
            return ()
        request = self._request(foreign_currencies, as_of)
        content = self._fetch_content(request)
        return self._parse_observations(content, foreign_currencies, as_of)

    @staticmethod
    def _request(currencies: set[str], as_of: date) -> Request:
        parameters = {"base": "INR", "quotes": ",".join(sorted(currencies))}
        if as_of < date.today():
            parameters["date"] = as_of.isoformat()
        url = config.FRANKFURTER_URL + "?" + urlencode(parameters)
        return Request(
            url, headers={"User-Agent": "WealthTracker/0.1", "Accept": "application/json"},
        )

    @staticmethod
    def _fetch_content(request: Request) -> bytes:
        try:
            content = _read_rate_response(request)
        except (URLError, TimeoutError, OSError) as error:
            raise ExchangeRateFetchError(
                error_messages.FX_SERVICE_UNAVAILABLE
            ) from error
        if len(content) > config.MAX_FX_RESPONSE_BYTES:
            raise ExchangeRateFetchError(error_messages.EXCHANGE_RATE_SERVICE_RETURNED_AN_OVERSIZED_RESPONSE)
        return content

    def _parse_observations(
        self, content: bytes, currencies: set[str], as_of: date,
    ) -> tuple[ExchangeRateObservation, ...]:
        try:
            payload = json.loads(content, parse_float=Decimal)
            return self._validated_observations(payload, currencies, as_of)
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            raise ExchangeRateFetchError(
                error_messages.FX_RESPONSE_INVALID
            ) from error

    def _validated_observations(
        self, payload: object, currencies: set[str], as_of: date,
    ) -> tuple[ExchangeRateObservation, ...]:
        if not isinstance(payload, list):
            raise ValueError(error_messages.EXPECTED_A_LIST_OF_EXCHANGE_RATES)
        observations: dict[str, ExchangeRateObservation] = {}
        for row in payload:
            observation = self._observation(row, as_of)
            if observation.currency not in currencies or observation.currency in observations:
                raise ValueError(error_messages.UNEXPECTED_OR_DUPLICATE_EXCHANGE_RATE_CURRENCY)
            observations[observation.currency] = observation
        if set(observations) != currencies:
            raise ValueError(error_messages.THE_SERVICE_DID_NOT_PROVIDE_EVERY_REQUIRED_CURRENCY)
        return tuple(observations[currency] for currency in sorted(observations))

    @staticmethod
    def _observation(row: object, as_of: date) -> ExchangeRateObservation:
        if not isinstance(row, dict) or row.get("base") != "INR":
            raise ValueError(error_messages.UNEXPECTED_EXCHANGE_RATE_BASE_CURRENCY)
        rate_date = observation_date(row["date"])
        if rate_date > as_of:
            raise ValueError(error_messages.EXCHANGE_RATE_DATE_IS_LATER_THAN_THE_VALUATION_DATE)
        return ExchangeRateObservation(row["quote"], _inr_rate(row["rate"]), rate_date)


def _inr_rate(quote_rate: object) -> Decimal:
    if (
        isinstance(quote_rate, bool)
        or not isinstance(quote_rate, (int, Decimal))
        or not Decimal(quote_rate).is_finite()
        or quote_rate <= 0
    ):
        raise ValueError(error_messages.EXCHANGE_RATE_MUST_BE_A_FINITE_POSITIVE_NUMBER)
    with localcontext() as context:
        context.prec = 50
        return (Decimal(1) / quote_rate).quantize(Decimal("0.00000001"))
