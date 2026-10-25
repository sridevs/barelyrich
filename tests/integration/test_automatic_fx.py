from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import json
import socket
import ssl
from unittest.mock import Mock, create_autospec
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from streamlit.testing.v1 import AppTest

from src.providers.exchange_rates import (
    ExchangeRateFetchError, FrankfurterExchangeRateProvider,
)
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.repo.contracts import ExchangeRateWriter
from src.repo.db import connect, initialise
from src.repo.portfolio import PortfolioStore
from src.service.exchange_rates import ExchangeRateProvider, ExchangeRateRefresh
from src.service.portfolio import PortfolioHistory


TODAY = date.today()


def rate_payload(**changes):
    row = {"date": TODAY.isoformat(), "base": "INR", "quote": "SGD", "rate": 0.0125}
    row.update(changes)
    return [row]


def mock_response(monkeypatch, payload):
    calls = []

    def open_url(request, timeout):
        calls.append((request, timeout))
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("src.providers.exchange_rates.urlopen", open_url)
    return calls


def test_latest_request_is_public_and_returns_inr_per_currency(monkeypatch):
    calls = mock_response(monkeypatch, rate_payload())
    observations = FrankfurterExchangeRateProvider().fetch({"SGD", "INR"}, TODAY)
    assert observations == (ExchangeRateObservation("SGD", Decimal("80.00000000"), TODAY),)
    query = parse_qs(urlsplit(calls[0][0].full_url).query)
    assert query == {"base": ["INR"], "quotes": ["SGD"]}
    assert calls[0][0].get_header("User-agent") == "WealthTracker/0.1"
    assert calls[0][0].get_header("Accept") == "application/json"
    assert calls[0][1] == 30


def test_historical_request_preserves_publication_date(monkeypatch):
    historical_day = TODAY - timedelta(days=4)
    published_day = historical_day - timedelta(days=1)
    calls = mock_response(monkeypatch, rate_payload(date=published_day.isoformat()))
    observations = FrankfurterExchangeRateProvider().fetch({"SGD"}, historical_day)
    assert observations[0].as_of == published_day
    assert parse_qs(urlsplit(calls[0][0].full_url).query)["date"] == [historical_day.isoformat()]


@pytest.mark.parametrize("payload", [
    {}, [], [None], rate_payload(base="USD"), rate_payload(quote="USD"),
    rate_payload(rate=0), rate_payload(rate=-1), rate_payload(rate=True),
    rate_payload(rate="bad"), rate_payload(rate=float("inf")),
    rate_payload(date="not-a-date"),
    rate_payload(date=(TODAY + timedelta(days=1)).isoformat()),
    rate_payload() + rate_payload(),
    [{"date": TODAY.isoformat(), "base": "INR", "quote": "SGD"}],
])
def test_invalid_or_missing_rates_fail_closed(monkeypatch, payload):
    mock_response(monkeypatch, payload)
    with pytest.raises(ExchangeRateFetchError, match="invalid or incomplete"):
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)


def test_historical_fetch_rejects_rate_after_requested_date(monkeypatch):
    mock_response(monkeypatch, rate_payload())
    with pytest.raises(ExchangeRateFetchError):
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY - timedelta(days=1))


@pytest.mark.parametrize("content", [b"not JSON", b"\xff", b"x" * 100_001])
def test_bad_response_bytes_are_explicit_errors(monkeypatch, content):
    monkeypatch.setattr(
        "src.providers.exchange_rates.urlopen",
        lambda url, timeout: BytesIO(content),
    )
    with pytest.raises(ExchangeRateFetchError):
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)


def test_outage_is_explicit_and_identity_conversion_avoids_network(monkeypatch):
    monkeypatch.setattr("src.retry.time.sleep", lambda delay: None)
    def unavailable(url, timeout):
        raise URLError("offline")

    monkeypatch.setattr("src.providers.exchange_rates.urlopen", unavailable)
    assert FrankfurterExchangeRateProvider().fetch({"INR"}, TODAY) == ()
    with pytest.raises(ExchangeRateFetchError, match="unavailable"):
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)


@pytest.mark.parametrize("error", [
    TimeoutError("read timed out"), ConnectionResetError("reset"),
    URLError(TimeoutError("wrapped timeout")),
    URLError(socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")),
    *[HTTPError("https://example.test", code, "transient", {}, None)
      for code in (408, 429, 500, 502, 503, 504)],
])
@pytest.mark.parametrize("historical", [False, True])
def test_transient_rate_errors_retry_and_recover(monkeypatch, error, historical):
    day = TODAY - timedelta(days=1) if historical else TODAY
    response = BytesIO(json.dumps(rate_payload(date=day.isoformat())).encode())
    open_url = Mock(side_effect=[error, response])
    sleep = Mock()
    monkeypatch.setattr("src.providers.exchange_rates.urlopen", open_url)
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    observations = FrankfurterExchangeRateProvider().fetch({"SGD"}, day)
    assert len(observations) == 1
    assert open_url.call_count == 2
    assert all(item.kwargs["timeout"] == 30 for item in open_url.call_args_list)
    assert open_url.call_args_list[0] == open_url.call_args_list[1]
    sleep.assert_called_once_with(1)


def test_repeated_timeouts_exhaust_retries_and_preserve_cause(monkeypatch):
    error = TimeoutError("read timed out")
    open_url = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr("src.providers.exchange_rates.urlopen", open_url)
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    with pytest.raises(ExchangeRateFetchError, match="unavailable") as caught:
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)
    assert caught.value.__cause__ is error
    assert open_url.call_count == 3
    assert [item.args[0] for item in sleep.call_args_list] == [1, 2]


@pytest.mark.parametrize("error", [
    HTTPError("https://example.test", 400, "bad request", {}, None),
    HTTPError("https://example.test", 404, "not found", {}, None),
    URLError(ssl.SSLCertVerificationError("invalid certificate")),
    ssl.SSLError("TLS configuration failure"),
    PermissionError("permission denied"),
    URLError(socket.gaierror(socket.EAI_NONAME, "unknown host")),
])
def test_permanent_rate_errors_do_not_retry(monkeypatch, error):
    open_url = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr("src.providers.exchange_rates.urlopen", open_url)
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    with pytest.raises(ExchangeRateFetchError):
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)
    open_url.assert_called_once()
    sleep.assert_not_called()


def test_invalid_rate_data_is_not_retried(monkeypatch):
    calls = mock_response(monkeypatch, rate_payload(rate=-1))
    sleep = Mock()
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    with pytest.raises(ExchangeRateFetchError, match="invalid or incomplete"):
        FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)
    assert len(calls) == 1
    sleep.assert_not_called()


def test_timeout_while_reading_body_retries_entire_request(monkeypatch):
    broken_response = Mock()
    broken_response.__enter__ = Mock(return_value=broken_response)
    broken_response.__exit__ = Mock(return_value=False)
    broken_response.read.side_effect = TimeoutError("body read timed out")
    response = BytesIO(json.dumps(rate_payload()).encode())
    open_url = Mock(side_effect=[broken_response, response])
    monkeypatch.setattr("src.providers.exchange_rates.urlopen", open_url)
    monkeypatch.setattr("src.retry.time.sleep", lambda delay: None)
    assert len(FrankfurterExchangeRateProvider().fetch({"SGD"}, TODAY)) == 1
    assert open_url.call_count == 2
    broken_response.__exit__.assert_called_once()


def test_refresh_fetches_required_cross_rates_and_persists_atomically(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([BalanceSnapshot(
        "tiger_sg", "Portfolio", "USD", Decimal("100"), "asset", TODAY, "manual",
    )])
    provider = create_autospec(ExchangeRateProvider, instance=True)
    observations = (
        ExchangeRateObservation("SGD", Decimal("60"), TODAY),
        ExchangeRateObservation("USD", Decimal("80"), TODAY),
    )
    provider.fetch.return_value = observations
    assert ExchangeRateRefresh(provider, store).refresh(store.portfolio(TODAY, "SGD")) == observations
    provider.fetch.assert_called_once_with({"SGD", "USD"}, TODAY)
    assert store.portfolio(TODAY, "SGD").net_worth == Decimal("100") * Decimal(80) / 60
    with connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM exchange_rates WHERE source='frankfurter'",
        ).fetchone()[0] == 2
    ExchangeRateRefresh(provider, store).refresh(store.portfolio(TODAY, "SGD"))
    assert provider.fetch.call_count == 2


def test_refresh_skips_identity_and_empty_portfolios(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    provider = create_autospec(ExchangeRateProvider, instance=True)
    writer = create_autospec(ExchangeRateWriter, instance=True)
    service = ExchangeRateRefresh(provider, writer)
    assert service.refresh(store.portfolio(TODAY)) == ()
    store.save([BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("100"), "asset", TODAY, "manual",
    )])
    assert service.refresh(store.portfolio(TODAY, "SGD")) == ()
    provider.fetch.assert_not_called()
    writer.save_fetched_rates.assert_not_called()


def test_multicurrency_statement_pockets_use_automatic_cross_rates(tmp_path, monkeypatch):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([
        BalanceSnapshot(
            "dbs_sg", "Savings SGD", "SGD", Decimal("100"), "asset", TODAY, "statement",
        ),
        BalanceSnapshot(
            "dbs_sg", "Savings THB", "THB", Decimal("1000"), "asset", TODAY, "statement",
        ),
    ])
    calls = mock_response(monkeypatch, [
        {"date": TODAY.isoformat(), "base": "INR", "quote": "SGD", "rate": 0.0125},
        {"date": TODAY.isoformat(), "base": "INR", "quote": "THB", "rate": 0.4},
    ])
    ExchangeRateRefresh(FrankfurterExchangeRateProvider(), store).refresh(
        store.portfolio(TODAY, "SGD"),
    )
    assert parse_qs(urlsplit(calls[0][0].full_url).query)["quotes"] == ["SGD,THB"]
    assert store.portfolio(TODAY, "SGD").net_worth == Decimal("131.25")
    assert store.portfolio(TODAY, "INR").net_worth == Decimal("10500")


def test_failed_refresh_does_not_write(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("100"), "asset", TODAY, "manual",
    )])
    provider = create_autospec(ExchangeRateProvider, instance=True)
    provider.fetch.side_effect = ExchangeRateFetchError("offline")
    writer = create_autospec(ExchangeRateWriter, instance=True)
    with pytest.raises(ExchangeRateFetchError):
        ExchangeRateRefresh(provider, writer).refresh(store.portfolio(TODAY))
    writer.save_fetched_rates.assert_not_called()


def test_saved_rates_prefer_latest_date_and_automatic_ties_without_future_leak(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    earlier_day = TODAY - timedelta(days=3)
    store.save([BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("100"), "asset", earlier_day, "manual",
    )])
    store.save_rate("SGD", "60", earlier_day)
    store.save_fetched_rates((ExchangeRateObservation("SGD", Decimal("65"), earlier_day),))
    store.save_fetched_rates((ExchangeRateObservation("SGD", Decimal("70"), TODAY),))
    assert store.portfolio(earlier_day).net_worth == Decimal("6500")
    assert store.portfolio(TODAY).net_worth == Decimal("7000")
    store.save_rate("SGD", "80", TODAY)
    assert store.portfolio(TODAY).net_worth == Decimal("7000")
    store.save_rate("SGD", "75", TODAY - timedelta(days=1))
    assert store.portfolio(TODAY - timedelta(days=1)).net_worth == Decimal("7500")


def test_history_fetches_2022_rate_and_preserves_current_valuation(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    historical_day = date(2022, 6, 30)
    store.save([
        BalanceSnapshot("Example Bank", "Savings SGD", "SGD", Decimal("1000"), "asset",
                        day, "statement", "1234")
        for day in (historical_day, TODAY)
    ])
    store.save_rate("SGD", "70", TODAY)
    provider = create_autospec(ExchangeRateProvider, instance=True)
    provider.fetch.return_value = (
        ExchangeRateObservation("SGD", Decimal("52"), historical_day),
    )
    service = ExchangeRateRefresh(provider, store)
    service.refresh_historical(store.portfolio(historical_day, "INR"))
    points = PortfolioHistory(store).at_dates([historical_day, TODAY], "INR")
    assert [point.net_worth for point in points] == [Decimal("52000"), Decimal("70000")]
    assert store.historical_fx_currencies(historical_day) == {"SGD"}
    # Reopen the store: the request cache must survive application restarts.
    reopened = PortfolioStore(path)
    assert ExchangeRateRefresh(provider, reopened).refresh_historical(
        reopened.portfolio(historical_day, "INR"),
    ) == ()
    provider.fetch.assert_called_once_with({"SGD"}, historical_day)


def test_weekend_history_caches_requested_date_but_keeps_publication_date(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    sunday, friday = date(2022, 7, 3), date(2022, 7, 1)
    store.save([BalanceSnapshot(
        "Example Bank", "Savings", "USD", Decimal("100"), "asset", sunday, "manual",
    )])
    provider = create_autospec(ExchangeRateProvider, instance=True)
    provider.fetch.return_value = (
        ExchangeRateObservation("USD", Decimal("80"), friday),
        ExchangeRateObservation("SGD", Decimal("52"), friday),
    )
    service = ExchangeRateRefresh(provider, store)
    service.refresh_historical(store.portfolio(sunday, "SGD"))
    assert service.refresh_historical(store.portfolio(sunday, "SGD")) == ()
    portfolio = store.portfolio(sunday, "SGD")
    assert portfolio.net_worth == Decimal("100") * 80 / 52
    assert portfolio.accounts[0].rate_date == friday
    provider.fetch.assert_called_once_with({"USD", "SGD"}, sunday)


def test_historical_refresh_fetches_new_currencies_without_repeating_saved_ones(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    day = date(2022, 6, 30)
    store.save([BalanceSnapshot(
        "Example Bank", "Savings", "SGD", Decimal("100"), "asset", day, "manual",
    )])
    store.save_historical_rates((ExchangeRateObservation("SGD", Decimal("52"), day),), day)
    store.save([BalanceSnapshot(
        "Example Bank", "Other", "USD", Decimal("10"), "asset", day, "manual",
    )])
    provider = create_autospec(ExchangeRateProvider, instance=True)
    provider.fetch.return_value = (ExchangeRateObservation("USD", Decimal("80"), day),)
    ExchangeRateRefresh(provider, store).refresh_historical(store.portfolio(day, "INR"))
    provider.fetch.assert_called_once_with({"USD"}, day)
    assert store.portfolio(day, "INR").net_worth == Decimal("6000")


@pytest.mark.parametrize("observations", [
    (),
    (ExchangeRateObservation("USD", Decimal("80"), date(2022, 6, 30)),),
    (ExchangeRateObservation("SGD", Decimal("52"), date(2022, 7, 1)),),
    (ExchangeRateObservation("SGD", Decimal("52"), date(2022, 6, 30)),) * 2,
])
def test_invalid_historical_response_does_not_mark_request_complete(tmp_path, observations):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    day = date(2022, 6, 30)
    store.save([BalanceSnapshot(
        "Example Bank", "Savings", "SGD", Decimal("100"), "asset", day, "manual",
    )])
    provider = create_autospec(ExchangeRateProvider, instance=True)
    provider.fetch.return_value = observations
    with pytest.raises(ExchangeRateFetchError):
        ExchangeRateRefresh(provider, store).refresh_historical(store.portfolio(day, "INR"))
    assert store.historical_fx_currencies(day) == set()
    assert store.portfolio(day, "INR").net_worth is None


def test_historical_outage_can_be_retried_and_identity_needs_no_network(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    day = date(2022, 6, 30)
    store.save([BalanceSnapshot(
        "Example Bank", "Savings", "SGD", Decimal("100"), "asset", day, "manual",
    )])
    provider = create_autospec(ExchangeRateProvider, instance=True)
    service = ExchangeRateRefresh(provider, store)
    assert service.refresh_historical(store.portfolio(day, "SGD")) == ()
    provider.fetch.assert_not_called()
    provider.fetch.side_effect = [
        ExchangeRateFetchError("offline"),
        (ExchangeRateObservation("SGD", Decimal("52"), day),),
    ]
    with pytest.raises(ExchangeRateFetchError):
        service.refresh_historical(store.portfolio(day, "INR"))
    assert store.historical_fx_currencies(day) == set()
    service.refresh_historical(store.portfolio(day, "INR"))
    assert store.portfolio(day, "INR").net_worth == Decimal("5200")


@pytest.mark.parametrize("offline_history", [False, True])
def test_real_chart_fetches_history_and_never_substitutes_current_fx(
    tmp_path, monkeypatch, offline_history,
):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    old_day = date(2022, 6, 30)
    store.save([
        BalanceSnapshot("Example Bank", "Savings", "SGD", Decimal("1000"), "asset",
                        day, "statement", "1234")
        for day in (old_day, TODAY)
    ])
    calls = []

    def fetch(provider, currencies, as_of):
        calls.append((currencies, as_of))
        if offline_history and as_of == old_day:
            raise ExchangeRateFetchError("historical service unavailable")
        return (ExchangeRateObservation(
            "SGD", Decimal("52") if as_of == old_day else Decimal("70"), as_of,
        ),)

    monkeypatch.setattr(FrankfurterExchangeRateProvider, "fetch", fetch)
    script = f"""
from pathlib import Path
from datetime import date
from src.repo.portfolio import PortfolioStore
from src.ui.dashboard import render_live_overview
store = PortfolioStore(Path({str(path)!r}))
render_live_overview(store, store.portfolio(date.today(), "INR"))
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert app.metric[0].value == "70,000.00"
    assert calls == [({"SGD"}, TODAY), ({"SGD"}, old_day)]
    assert len(app.get("vega_lite_chart")) == int(not offline_history)
    if offline_history:
        assert any("Historical chart unavailable" in item.value for item in app.warning)
        assert store.portfolio(old_day, "INR").net_worth is None
    else:
        assert store.portfolio(old_day, "INR").net_worth == Decimal("52000")
        app.run()
        assert not app.exception
        assert calls == [({"SGD"}, TODAY), ({"SGD"}, old_day), ({"SGD"}, TODAY)]


def test_repository_rejects_future_publication_without_writing_cache(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    day = date(2022, 6, 30)
    with pytest.raises(ValueError, match="publication date"):
        store.save_historical_rates(
            (ExchangeRateObservation("SGD", Decimal("52"), day + timedelta(days=1)),), day,
        )
    assert store.historical_fx_currencies(day) == set()
