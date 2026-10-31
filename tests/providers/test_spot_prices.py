import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from src import config
from src.models.dto.spot_quote import SpotQuote
from src.providers.spot_prices import GoldApiSpotPriceProvider, SpotPriceFetchError

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def quote_payload(**changes):
    payload = {
        "currency": "USD", "price": 2650.5, "symbol": "XAU",
        "updatedAt": NOW.isoformat().replace("+00:00", "Z"),
    }
    payload.update(changes)
    return payload


def mock_urlopen(monkeypatch, side_effect) -> Mock:
    open_url = Mock(side_effect=side_effect)
    monkeypatch.setattr("src.providers.spot_prices.urlopen", open_url)
    return open_url


def respond_with(monkeypatch, content) -> Mock:
    return mock_urlopen(monkeypatch, lambda request, timeout: BytesIO(content))


@pytest.fixture(autouse=True)
def sleep(monkeypatch) -> Mock:
    sleep = Mock()
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    return sleep


def test_fetch_requests_symbol_and_returns_utc_quote(monkeypatch):
    open_url = respond_with(monkeypatch, json.dumps(quote_payload()).encode())
    quote = GoldApiSpotPriceProvider().fetch("XAU")
    assert quote == SpotQuote("XAU", "USD", Decimal("2650.5"), NOW)
    request, timeout = open_url.call_args.args[0], open_url.call_args.kwargs["timeout"]
    assert request.full_url == f"{config.SPOT_PRICE_URL}/XAU"
    assert request.get_header("Accept") == "application/json"
    assert timeout == config.SPOT_PRICE_TIMEOUT_SECONDS


def test_provider_names_its_source():
    assert GoldApiSpotPriceProvider().source == "gold-api.com"


@pytest.mark.parametrize("changes", [
    {"symbol": "XAG"},
    {"price": 0},
    {"price": "not a price"},
    {"currency": "usd"},
    {"updatedAt": (NOW - timedelta(days=2)).isoformat()},
    {"updatedAt": (NOW + timedelta(hours=1)).isoformat()},
    {"updatedAt": NOW.replace(tzinfo=None).isoformat()},
    {"updatedAt": None},
])
def test_invalid_or_stale_quotes_are_rejected(monkeypatch, changes):
    respond_with(monkeypatch, json.dumps(quote_payload(**changes)).encode())
    with pytest.raises(SpotPriceFetchError, match="invalid or stale"):
        GoldApiSpotPriceProvider().fetch("XAU")


@pytest.mark.parametrize("content", [b"not json", b"[]", json.dumps({"price": 1}).encode()])
def test_malformed_responses_are_rejected(monkeypatch, content):
    respond_with(monkeypatch, content)
    with pytest.raises(SpotPriceFetchError, match="invalid or stale"):
        GoldApiSpotPriceProvider().fetch("XAU")


def test_oversized_response_is_rejected(monkeypatch):
    respond_with(monkeypatch, b" " * (config.MAX_SPOT_PRICE_RESPONSE_BYTES + 1))
    with pytest.raises(SpotPriceFetchError, match="oversized"):
        GoldApiSpotPriceProvider().fetch("XAU")


def test_transient_network_errors_are_retried_then_reported(monkeypatch, sleep):
    open_url = mock_urlopen(monkeypatch, URLError(TimeoutError()))
    with pytest.raises(SpotPriceFetchError, match="unavailable"):
        GoldApiSpotPriceProvider().fetch("XAU")
    assert open_url.call_count > 1
    assert sleep.called


def test_retry_recovers_from_a_transient_failure(monkeypatch):
    responses = iter([URLError(TimeoutError()), BytesIO(json.dumps(quote_payload()).encode())])

    def open_url(request, timeout):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("src.providers.spot_prices.urlopen", open_url)
    assert GoldApiSpotPriceProvider().fetch("XAU").price == Decimal("2650.5")
