from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.portfolio import Portfolio
from src.models.portfolio.portfolio_summary import PortfolioSummary
from src.ui.presentation import money, PortfolioPresenter


DAY = date(2026, 1, 10)


def account(**changes):
    values = dict(
        account="Savings", institution="dbs_sg", currency="SGD", balance=Decimal("100"),
        kind="asset", as_of=DAY, source="manual", recorded_at="2026-01-10 10:00:00",
        rate=Decimal("60"), rate_date=DAY,
        institution_name="DBS Singapore", country="SG",
    )
    values.update(changes)
    return AccountValue(**values)


def test_money_does_not_confuse_zero_with_missing():
    assert money(None) is None
    assert money(Decimal("0")) == "0.00"
    assert money(Decimal("-1234.567")) == "-1,234.57"


@pytest.mark.parametrize("value,expected", [
    ("0", "0.00"), ("1234.5", "1,234.50"), ("99999", "99,999.00"),
    ("100000", "1,00,000.00"), ("1234567.89", "12,34,567.89"),
    ("10000000", "1,00,00,000.00"), ("-12345678.9", "-1,23,45,678.90"),
    ("99999.999", "1,00,000.00"),
])
def test_inr_money_uses_lakh_and_crore_grouping(value, expected):
    assert money(Decimal(value), "INR") == expected


def test_other_currencies_keep_international_grouping():
    assert money(Decimal("12345678.9"), "SGD") == "12,345,678.90"
    assert money(None, "INR") is None


def test_inr_grouping_respects_configured_precision(monkeypatch):
    monkeypatch.setattr("src.ui.presentation.config.MONEY_DECIMAL_PLACES", 0)
    assert money(Decimal("12345678.9"), "INR") == "1,23,45,679"


def test_inr_account_and_converted_values_use_indian_grouping():
    value = account(currency="INR", balance=Decimal("12345678.9"), rate=Decimal(1))
    row = PortfolioPresenter(Portfolio((value,), "INR", DAY)).account_rows()[0]
    assert row["Balance"] == "1,23,45,678.90"
    assert row["Net value (INR)"] == "1,23,45,678.90"


def test_staleness_threshold_is_strictly_more_than_seven_days():
    rows = tuple(account(
        account=str(days), as_of=DAY - timedelta(days=days),
        rate_date=DAY - timedelta(days=days),
    ) for days in (0, 7, 8))
    presenter = PortfolioPresenter(Portfolio(rows, "INR", DAY))
    assert presenter.stale_accounts() == ("8",)
    assert presenter.stale_currencies() == ("SGD",)
    assert presenter.stale_accounts(days=8) == ()


def test_stale_currencies_ignore_identity_rates_and_missing_rates_and_deduplicate():
    old = DAY - timedelta(days=8)
    rows = (
        account(currency="INR", rate=Decimal(1), rate_date=old),
        account(currency="USD", rate=None, rate_date=None),
        account(rate_date=old), account(account="Another", rate_date=old),
    )
    presenter = PortfolioPresenter(Portfolio(rows, "INR", DAY))
    assert presenter.stale_currencies() == ("SGD",)


def test_summary_subtracts_liabilities_and_preserves_negative_asset_equity():
    rows = (
        account(),
        account(account="Overdraft", balance=Decimal("-10")),
        account(account="Loan", institution="kotak_in", currency="INR",
                balance=Decimal("500"), rate=Decimal(1), kind="liability"),
    )
    portfolio = Portfolio(rows, "INR", DAY)
    summary = PortfolioSummary.from_portfolio(portfolio)
    assert summary.assets == Decimal("5400")
    assert summary.liabilities == Decimal("500")
    assert summary.assets - summary.liabilities == portfolio.net_worth
    assert summary.institution_totals["dbs_sg"] == Decimal("5400")
    assert summary.institution_totals["kotak_in"] == Decimal("-500")
    assert "uob_sg" not in summary.institution_totals


@pytest.mark.parametrize("rows", [(), (account(rate=None, rate_date=None),)])
def test_incomplete_summary_is_never_success_shaped(rows: tuple[AccountValue, ...]):
    with pytest.raises(ValueError):
        PortfolioSummary.from_portfolio(Portfolio(rows, "INR", DAY))


def test_real_rows_keep_provenance_and_missing_conversion_visible():
    presenter = PortfolioPresenter(Portfolio((account(rate=None, rate_date=None),), "INR", DAY))
    row = presenter.account_rows()[0]
    assert row["Institution"] == "DBS Singapore"
    assert row["Balance"] == "100"
    assert row["Net value (INR)"] is None
    assert row["FX to INR"] is None
    assert row["Source"] == "manual"
    assert row["Recorded / fetched (UTC)"] == "2026-01-10 10:00:00"


def test_identity_conversion_does_not_display_fx_date():
    value = replace(account(), currency="INR", rate=Decimal(1))
    row = PortfolioPresenter(Portfolio((value,), "INR", DAY)).account_rows()[0]
    assert row["Oldest FX date used"] is None
