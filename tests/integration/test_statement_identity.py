from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import account_number, account_product_type
from src.repo.db import connect
from src.repo.portfolio import PortfolioStore
from src.service.portfolio import PortfolioHistory
from tests.statement_fixtures import statement_extraction

OCTOBER = date(2024, 10, 31)
JANUARY = date(2025, 1, 31)


def pocket(number="123456", currency="SGD", balance="100", day=OCTOBER, alias="Savings"):
    return BalanceSnapshot(
        "dbs_sg", f"{alias} {currency}", currency, Decimal(balance),
        "asset", day, "statement", number,
    )


def test_account_number_links_statements_despite_alias_and_upload_order(store):
    store.save([pocket(day=JANUARY, balance="200", alias="Renamed")])
    store.save([pocket(number="123-456")])
    current = store.portfolio(JANUARY, "SGD")
    assert len(current.accounts) == 1
    assert current.net_worth == Decimal("200")
    assert store.portfolio(OCTOBER, "SGD").net_worth == Decimal("100")
    assert len(store.balance_history(JANUARY)) == 2
    with connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert conn.execute("SELECT account_number FROM accounts").fetchone()[0] == "123456"
    points = PortfolioHistory(store).at_dates([JANUARY, OCTOBER, JANUARY], "SGD")
    assert [(point.as_of, point.net_worth) for point in points] == [
        (OCTOBER, Decimal("100")), (JANUARY, Decimal("200")),
    ]


def test_account_type_corrections_persist_across_all_currency_pockets(store):
    store.save([
        replace(pocket(), product_type="Savings"),
        replace(pocket(currency="INR"), product_type="Savings"),
    ])
    store.save([replace(pocket(day=JANUARY), product_type="  Fixed deposit  ")])
    assert {row["product_type"] for row in store.balance_history(JANUARY)} == {"Fixed deposit"}
    current = PortfolioStore(store.path).portfolio(JANUARY, "SGD")
    assert current.accounts[0].product_type == "Fixed deposit"
    assert current.accounts[0].institution_record().account_type == "bank"
    assert current.net_worth == Decimal("100")
    with pytest.raises(ValueError, match="Duplicate"):
        store.save([
            replace(pocket(day=JANUARY), product_type="Wrong type"),
            replace(pocket(day=JANUARY), product_type="Wrong type"),
        ])
    assert store.portfolio(JANUARY, "SGD").accounts[0].product_type == "Fixed deposit"


@pytest.mark.parametrize("value", [None, 123, "x" * 101, "Fixed\nDeposit"])
def test_account_product_type_rejects_invalid_descriptions(value):
    with pytest.raises(ValueError, match="Account type"):
        account_product_type(value)


def test_same_alias_different_numbers_remain_distinct_and_institution_scoped(store):
    store.save([pocket(), pocket(number="654321")])
    store.save([replace(pocket(), institution="uob_sg")])
    assert len(store.portfolio(OCTOBER, "SGD").accounts) == 3
    assert store.portfolio(OCTOBER, "SGD").net_worth == Decimal("300")


def test_latest_statement_keeps_all_its_pockets_without_carrying_old_currencies(store):
    store.save([
        pocket(), pocket(currency="USD", balance="20"),
        pocket(day=JANUARY, balance="200"),
        pocket(day=JANUARY, currency="INR", balance="300"),
    ])
    store.save_rate("SGD", "60", OCTOBER)
    store.save_rate("USD", "80", OCTOBER)
    assert store.portfolio(OCTOBER, "INR").net_worth == Decimal("7600")
    latest = store.portfolio(JANUARY, "INR")
    assert {item.currency for item in latest.accounts} == {"SGD", "INR"}
    assert latest.net_worth == Decimal("12300")
    assert len(store.balance_history(JANUARY)) == 4
    assert not store.portfolio(date(2024, 10, 30), "INR").accounts


def test_same_date_reimport_replaces_currency_set_and_rollback_preserves_original(store):
    store.save([pocket(), pocket(currency="USD")])
    with pytest.raises(ValueError, match="Duplicate"):
        store.save([pocket(balance="999"), pocket(balance="888")])
    assert len(store.balance_history(OCTOBER)) == 2
    store.save([pocket(balance="300")])
    assert len(store.balance_history(OCTOBER)) == 1
    assert store.portfolio(OCTOBER, "SGD").net_worth == Decimal("300")


def test_legacy_alias_only_accounts_are_preserved_not_guessed(store):
    store.save([replace(pocket(), account_number=None, source="csv")])
    store.save([pocket()])
    assert len(store.portfolio(OCTOBER, "SGD").accounts) == 2


@pytest.mark.parametrize("number", ["", "Savings", "\n123", "x" * 101])
def test_account_number_requires_visible_identifier(number):
    with pytest.raises(ValueError, match="account number"):
        account_number(number)


def test_extraction_requires_valid_account_number_and_preserves_multiple_dates():
    extraction = statement_extraction()
    assert extraction.to_snapshots("dbs_sg", "Savings", "asset")[0].account_number == "TEST1234"
    account = extraction.accounts[0]
    updated = replace(extraction, accounts=(replace(account, number="9999"),))
    assert updated.account_number == "9999"
    with pytest.raises(ValueError, match="account number"):
        replace(extraction, accounts=(replace(account, number=""),)).to_snapshots(
            "dbs_sg", "Savings", "asset",
        )
    historical = replace(extraction, accounts=(replace(account, balances=(
        account.balances[0],
        replace(account.balances[0], as_of=OCTOBER),
    )),))
    assert [balance.as_of for balance in historical.balances] == [date.today(), OCTOBER]
    assert replace(
        extraction, accounts=(replace(
            account, number="123-456",
        ),),
    ).to_snapshots("dbs_sg", "Savings", "asset")[0].account_number == "123456"


def test_history_reports_missing_historical_fx_instead_of_partial_totals(store):
    store.save([pocket(), pocket(balance="200", day=JANUARY)])
    store.save_rate("SGD", "60", JANUARY)
    with pytest.raises(ValueError, match="2024-10-31.*dated FX"):
        PortfolioHistory(store).at_dates([OCTOBER, JANUARY], "INR")




def test_real_overview_plots_historical_net_worth(store):
    store.save([pocket(), pocket(balance="200", day=JANUARY)])
    app = AppTest.from_string(f"""
from pathlib import Path
from datetime import date
from src.repo.portfolio import PortfolioStore
from src.ui.dashboard import render_live_overview
store = PortfolioStore(Path({str(store.path)!r}))
render_live_overview(store, store.portfolio(date(2025, 1, 31), "SGD"))
""").run()
    assert not app.exception
    assert app.metric[0].value == "200.00"
    assert any(heading.value == "Net worth over time" for heading in app.subheader)
    assert len(app.get("vega_lite_chart")) == 1
