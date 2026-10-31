from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.institution import Institution
from src.models.portfolio.portfolio import Portfolio

DAY = date(2026, 1, 10)


def account(**changes) -> AccountValue:
    values = dict(
        account="Savings", institution="dbs_sg", currency="SGD", balance=Decimal("100"),
        kind="asset", as_of=DAY, source="manual", recorded_at="2026-01-10 12:00:00",
        rate=Decimal("60"), rate_date=DAY,
    )
    values.update(changes)
    return AccountValue(**values)


def test_snapshot_owns_observation_identity_and_account_compatibility():
    snapshot = BalanceSnapshot("dbs_sg", "Savings", "SGD", Decimal(100), "asset", DAY, "manual")
    assert snapshot.identity == ("dbs_sg", "Savings", DAY)
    assert not snapshot.is_liability
    snapshot.ensure_account_compatible("SGD", False)
    for currency, liability in (("INR", False), ("SGD", True)):
        with pytest.raises(ValueError, match="currency or kind cannot change"):
            snapshot.ensure_account_compatible(currency, liability)
    debt = replace(snapshot, kind="liability")
    assert debt.is_liability
    debt.ensure_account_compatible("SGD", True)


@pytest.mark.parametrize("kind,balance,expected", [
    ("asset", "100", "6000"), ("liability", "100", "-6000"),
    ("asset", "-100", "-6000"), ("asset", "0", "0"),
])
def test_account_owns_signed_valuation(kind, balance, expected):
    value = account(kind=kind, balance=Decimal(balance))
    assert value.require_net_value() == Decimal(expected)
    assert value.is_liability == (kind == "liability")
    assert value.has_conversion


def test_missing_conversion_is_not_a_zero_valuation():
    value = account(rate=None, rate_date=None)
    assert not value.has_conversion
    assert value.net_value is None
    with pytest.raises(ValueError, match="no exchange rate"):
        value.require_net_value()


def test_account_owns_balance_and_fx_staleness_rules():
    value = account()
    assert not value.is_stale(DAY + timedelta(days=7))
    assert value.is_stale(DAY + timedelta(days=8), days=7)
    assert value.has_stale_fx("INR", DAY + timedelta(days=8), days=7)
    assert not value.has_stale_fx("SGD", DAY + timedelta(days=8))
    assert not replace(value, rate_date=None).has_stale_fx(
        "INR", DAY + timedelta(days=8), days=7,
    )
    assert not value.is_stale(DAY + timedelta(days=8), days=8)


def test_only_api_observations_report_api_fetch_time():
    value = account()
    assert value.api_fetch_time is None
    assert replace(value, source="tiger_api").api_fetch_time == value.recorded_at


def test_portfolio_owns_grouping_staleness_and_summary():
    stale = account(as_of=DAY - timedelta(days=8), rate_date=DAY - timedelta(days=8))
    loan = account(
        account="Loan", institution="kotak_in", currency="INR",
        balance=Decimal(500), kind="liability", rate=Decimal(1),
    )
    portfolio = Portfolio((stale, loan), "INR", DAY)
    assert portfolio.accounts_for(Institution("dbs_sg", "DBS")) == (stale,)
    assert portfolio.accounts_for(Institution("uob_sg", "UOB")) == ()
    assert portfolio.stale_accounts(days=7) == (stale,)
    assert portfolio.stale_currencies(days=7) == ("SGD",)
    summary = portfolio.summarize()
    assert summary.net_worth == portfolio.net_worth == Decimal(5500)
    assert summary.total_for("kotak_in") == Decimal(-500)
    assert "uob_sg" not in summary.institution_totals
    with pytest.raises(KeyError):
        summary.total_for("unknown")


@pytest.mark.parametrize("currency,rate", [
    ("SGD", "0"), ("SGD", "-1"), ("INR", "2"), ("sgd", "60"), ("SGD", "NaN"),
])
def test_exchange_rate_observation_enforces_its_own_invariants(currency, rate):
    with pytest.raises(ValueError):
        ExchangeRateObservation.parse(currency, rate, DAY)


def test_exchange_rate_observation_parses_and_validates_date():
    rate = ExchangeRateObservation.parse("SGD", "60.25", DAY)
    assert rate.rate == Decimal("60.25")
    with pytest.raises(ValueError, match="future"):
        ExchangeRateObservation("SGD", Decimal(60), date.today() + timedelta(days=1))


@pytest.mark.parametrize("key,name,country,kind", [
    ("", "Bank", "SG", "bank"), ("bank", " ", "SG", "bank"),
    ("bank", "Bank", "sg", "bank"), ("bank", "Bank", "SG", "unknown"),
])
def test_institution_rejects_invalid_identity(key, name, country, kind):
    with pytest.raises(ValueError):
        Institution(key, name, country, kind)


@pytest.mark.parametrize("name", ["Example Credit Union", "新銀行", "Regional Brokerage"])
def test_institution_identity_is_generic_and_normalized(name):
    institution = Institution.from_name(name)
    assert institution.name == name
    assert institution.key == name.casefold()
    assert institution.normalized_name == name.casefold()


@pytest.mark.parametrize("currencies,base,expected", [
    ((), "INR", set()),
    (("SGD",), "SGD", set()),
    (("INR",), "INR", set()),
    (("SGD",), "INR", {"SGD"}),
    (("INR",), "SGD", {"SGD"}),
    (("USD", "THB", "SGD"), "SGD", {"USD", "THB", "SGD"}),
    (("USD", "USD"), "INR", {"USD"}),
])
def test_portfolio_owns_exact_cross_rate_requirements(currencies, base, expected):
    portfolio = Portfolio(tuple(account(currency=currency) for currency in currencies), base, DAY)
    assert portfolio.required_rate_currencies() == expected
    requested = portfolio.required_rate_currencies()
    requested.add("JPY")
    assert portfolio.required_rate_currencies() == expected
