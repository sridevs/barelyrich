from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.repo.db import connect, initialise
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import decimal_value
from src.repo.portfolio import PortfolioStore


DAY = date(2026, 1, 1)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    return PortfolioStore(path)


def snapshot(
    institution="dbs_sg", account="Savings", currency="SGD", balance="100",
    kind="asset", as_of=DAY,
):
    return BalanceSnapshot(
        institution, account, currency, Decimal(balance), kind, as_of, "manual",
    )


def test_all_institutions_assets_liabilities_and_fx(store):
    store.save([
        snapshot(),
        snapshot("uob_sg", balance="200"),
        snapshot("tiger_sg", account="Investments", balance="500"),
        snapshot("hdfc_in", currency="INR", balance="10000"),
        snapshot("kotak_in", currency="INR", balance="5000", kind="liability"),
    ])
    store.save_rate("SGD", "60", DAY)
    portfolio = store.portfolio(DAY)
    assert len(portfolio.accounts) == 5
    assert portfolio.net_worth == Decimal("53000")
    sgd_total = store.portfolio(DAY, "SGD").net_worth
    assert sgd_total is not None
    assert sgd_total.quantize(Decimal("0.01")) == Decimal("883.33")


def test_missing_rate_suppresses_total(store):
    store.save([snapshot(), snapshot("hdfc_in", currency="INR")])
    assert store.portfolio(DAY).net_worth is None
    assert store.portfolio(DAY).missing_currencies == ("SGD",)
    assert store.portfolio(DAY, "SGD").missing_currencies == ("INR",)
    assert PortfolioStore(store.path).portfolio(DAY).accounts


def test_empty_portfolio_is_not_zero(store):
    assert store.portfolio(DAY).net_worth is None


def test_same_currency_requires_no_fx(store):
    store.save([snapshot()])
    assert store.portfolio(DAY, "SGD").net_worth == Decimal(100)


def test_historical_queries_never_use_future_observations_or_rates(store):
    next_day = DAY + timedelta(days=1)
    store.save([snapshot(), snapshot(balance="200", as_of=next_day)])
    store.save_rate("SGD", "60", DAY)
    store.save_rate("SGD", "70", next_day)
    assert store.portfolio(DAY).net_worth == Decimal("6000")
    assert store.portfolio(next_day).net_worth == Decimal("14000")
    assert not store.portfolio(DAY - timedelta(days=1)).accounts


def test_rate_must_exist_before_valuation_date(store):
    store.save([snapshot()])
    store.save_rate("SGD", "60", DAY + timedelta(days=1))
    assert store.portfolio(DAY).net_worth is None


def test_cross_rates_and_overdraft(store):
    store.save([snapshot(currency="USD", balance="-100")])
    store.save_rate("USD", "80", DAY)
    store.save_rate("SGD", "60", DAY)
    assert store.portfolio(DAY).net_worth == Decimal("-8000")
    assert store.portfolio(DAY, "SGD").net_worth == Decimal("-8000") / 60


def test_reimports_replace_observations_not_add_balances(store):
    store.save([snapshot()])
    store.save([snapshot(balance="101")])
    store.save([snapshot(balance="101")])
    assert store.portfolio(DAY, "SGD").net_worth == Decimal(101)
    with connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_balances").fetchone()[0] == 1


def test_batch_duplicate_rolls_back_all_changes(store):
    store.save([snapshot()])
    with pytest.raises(ValueError, match="Duplicate"):
        store.save([snapshot(balance="999"), snapshot(balance="888")])
    assert store.portfolio(DAY, "SGD").net_worth == Decimal(100)


@pytest.mark.parametrize("change", [{"currency": "INR"}, {"kind": "liability"}])
def test_identity_changes_rollback_batch(store, change):
    store.save([snapshot()])
    with pytest.raises(ValueError, match="currency or kind cannot change"):
        store.save([snapshot("uob_sg"), snapshot(**change)])
    assert len(store.portfolio(DAY).accounts) == 1


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "abc", "1e19", "0.000000001", ""])
def test_reject_invalid_numbers(value):
    with pytest.raises(ValueError):
        decimal_value(value, "Balance")


@pytest.mark.parametrize("kwargs", [
    {"institution": ""}, {"account": ""}, {"account": " "},
    {"currency": "sgd"}, {"kind": "loan"}, {"kind": "liability", "balance": "-1"},
    {"balance": "NaN"}, {"as_of": date.today() + timedelta(days=1)},
])
def test_reject_invalid_snapshots(kwargs):
    with pytest.raises(ValueError):
        snapshot(**kwargs)


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", ""])
def test_reject_invalid_rates(store, rate):
    with pytest.raises(ValueError):
        store.save_rate("SGD", rate, DAY)


def test_currency_inr_identity_rate_cannot_change(store):
    with pytest.raises(ValueError):
        store.save_rate("INR", "2", DAY)


def test_legacy_csv_balances_remain_compatible_and_idempotent(store):
    rows = [
        BalanceSnapshot("dbs_sg", "DBS savings", "SGD", Decimal("1234.56"), "asset", DAY, "csv"),
        BalanceSnapshot("kotak_in", "Kotak loan", "INR", Decimal("200"), "liability", DAY, "csv"),
    ]
    store.save(rows)
    store.save(rows)
    store.save_rate("SGD", "60", DAY)
    assert store.portfolio(DAY).net_worth == Decimal("73873.60")
    assert {row.source for row in store.portfolio(DAY).accounts} == {"csv"}


def test_balance_history_is_ordered_and_excludes_future_rows(store):
    next_day = DAY + timedelta(days=1)
    store.save([
        snapshot(), snapshot("uob_sg"),
        snapshot(balance="200", as_of=next_day),
    ])
    rows = store.balance_history(DAY)
    assert len(rows) == 2
    assert [row["institution"] for row in rows] == ["dbs_sg", "uob_sg"]
    assert all(row["as_of"] == DAY.isoformat() and row["balance"] == "100" for row in rows)
    assert all(row["source"] == "manual" for row in rows)
    assert store.balance_history(next_day)[0]["as_of"] == next_day.isoformat()
    assert not store.balance_history(DAY - timedelta(days=1))


def test_exact_rate_queries_do_not_use_a_different_days_rate(store):
    store.save_rate("SGD", "60", DAY)
    assert store.rate_on("SGD", DAY) == Decimal(60)
    with pytest.raises(ValueError, match="No dated INR exchange rate"):
        store.rate_on("SGD", DAY + timedelta(days=1))
