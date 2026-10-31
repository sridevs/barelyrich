"""Transaction extraction, daily valuations and reimport identity."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from src.agents.output import StatementOutput
from src.models.entry.statement_review import StatementReview
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution
from src.service.portfolio import PortfolioHistory

JANUARY = date(2024, 1, 31)
FEBRUARY = date(2024, 2, 29)


def movement(*, balance="90", withdrawal="10", deposit=None, as_of=JANUARY):
    return StatementBalance(
        Decimal(balance), "SGD", as_of,
        None if withdrawal is None else Decimal(withdrawal),
        None if deposit is None else Decimal(deposit), "Example transaction",
    )


def review(*balances):
    return StatementReview.create(
        b"fictional ledger", "asset", StatementExtraction(
            (StatementAccount("1234", balances),), StatementInstitution("Example Bank"),
        ),
    )


def snapshot(*, balance="100", currency="SGD", as_of=JANUARY):
    return StatementBalance(
        Decimal(balance), currency, as_of,
    )


def test_same_day_transactions_and_reimports_do_not_sum_running_balances(store):
    first = movement()
    last = movement(balance="95", withdrawal=None, deposit="5")
    preview = review(first, last)
    assert store.save_statement(preview, "Savings", "Example Bank") == 2
    assert store.portfolio(JANUARY, "SGD").net_worth == Decimal("95")
    assert store.save_statement(preview, "Renamed", "Example Bank") == 2
    rows = store.balance_history(JANUARY)
    assert len(rows) == 2
    assert [(row["withdrawal"], row["deposit"]) for row in rows] == [(None, "5"), ("10", None)]
    assert all(row["account"] == "Renamed SGD" for row in rows)


def test_identical_legitimate_transactions_are_not_collapsed(store):
    first = movement()
    preview = review(first, first)
    store.save_statement(preview, "Savings", "Example Bank")
    store.save_statement(preview, "Savings", "Example Bank")
    assert len(store.balance_history(JANUARY)) == 2
    assert len({item.transaction_key for item in preview.snapshots("Savings")}) == 2


def test_zero_and_missing_opposite_movement_have_same_reimport_identity(store):
    first = movement()
    store.save_statement(review(first), "Savings", "Example Bank")
    store.save_statement(review(replace(first, deposit=Decimal(0))), "Savings", "Example Bank")
    assert len(store.balance_history(JANUARY)) == 1


def test_overlapping_statement_rows_are_upserted_not_duplicated(store):
    first = movement()
    last = movement(balance="95", withdrawal=None, deposit="5")
    store.save_statement(review(first, last), "Savings", "Example Bank")
    store.save_statement(review(last), "Savings", "Example Bank")
    assert len(store.balance_history(JANUARY)) == 2
    assert store.portfolio(JANUARY, "SGD").net_worth == Decimal("95")


def test_reimport_of_earlier_row_cannot_replace_end_of_day_balance(store):
    first = movement()
    last = movement(balance="95", withdrawal=None, deposit="5")
    store.save_statement(review(first, last), "Savings", "Example Bank")
    store.save_statement(review(first), "Savings", "Example Bank")
    assert len(store.balance_history(JANUARY)) == 2
    assert store.portfolio(JANUARY, "SGD").net_worth == Decimal("95")


def test_yearly_history_keeps_transaction_dates_and_monthly_closing_snapshots(store):
    preview = review(
        movement(), snapshot(),
        movement(balance="110", withdrawal=None, deposit="10", as_of=FEBRUARY),
        snapshot(balance="120", as_of=FEBRUARY),
    )
    store.save_statement(preview, "Savings", "Example Bank")
    points = PortfolioHistory(store).at_dates([JANUARY, FEBRUARY], "SGD")
    assert [point.net_worth for point in points] == [Decimal("100"), Decimal("120")]
    assert len(store.balance_history(FEBRUARY)) == 4


def test_transaction_update_preserves_other_currency_pocket(store):
    store.save_statement(review(snapshot(), snapshot(currency="EUR", balance="50")), "Savings", "Example Bank")
    store.save_statement(review(movement(as_of=FEBRUARY)), "Savings", "Example Bank")
    accounts = store.portfolio(FEBRUARY, "SGD").accounts
    assert {item.currency: item.balance for item in accounts} == {
        "SGD": Decimal("90"), "EUR": Decimal("50"),
    }


@pytest.mark.parametrize("changes", [
    {"withdrawal": Decimal("-1")},
    {"withdrawal": Decimal("NaN")},
    {"description": None}, {"balance": None},
])
def test_invalid_transaction_facts_fail_explicitly(changes):
    with pytest.raises(ValueError):
        replace(movement(), **changes)


@pytest.mark.parametrize("withdrawal,deposit", [
    ("0", None), (None, "0"), ("0", "0"), ("10", "1"),
])
def test_printed_movements_can_be_reviewed_and_saved(store, withdrawal, deposit):
    row = movement(withdrawal=withdrawal, deposit=deposit)
    store.save_statement(review(row), "Savings", "Example Bank")
    saved = store.balance_history(JANUARY)
    assert len(saved) == 1
    assert saved[0]["withdrawal"] == withdrawal
    assert saved[0]["deposit"] == deposit


def test_storage_uses_array_order_for_same_day_rows():
    preview = review(movement(balance="95"), movement(balance="80"))
    snapshots = preview.snapshots("Savings")
    assert [(item.balance, item.row_number) for item in snapshots] == [
        (Decimal("95"), 1), (Decimal("80"), 2),
    ]


def test_wire_output_preserves_more_than_thirty_transactions():
    rows = [
        {
            "balance": str(1000 - index), "currency": "SGD", "as_of": JANUARY.isoformat(),
            "withdrawal": "1", "deposit": None,
            "description": "Example payment",
        }
        for index in range(1, 101)
    ]
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [{"number": "1234", "balances": rows}],
    })
    extraction = output.to_domain()
    assert len(extraction.balances) == 100
    assert all(balance.is_transaction for balance in extraction.balances)


def test_wire_array_order_preserves_identical_transactions_and_zero_movements():
    row = {
        "description": "",
        "deposit": None,
        "balance": "100", "currency": "SGD", "as_of": JANUARY.isoformat(),
        "withdrawal": "0.00",
    }
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [{"number": "1234", "balances": [
            {"description": "", "withdrawal": "0", "deposit": None, "balance": "110", "currency": "SGD", "as_of": JANUARY.isoformat()},
            row, dict(row),
        ]}],
    })
    account = output.to_domain().accounts[0]
    assert len(account.balances) == 3
    snapshots = account.to_snapshots("Example Bank", "Savings", "asset")
    assert [item.row_number for item in snapshots] == [1, 2, 3]
    assert snapshots[1].transaction_key != snapshots[2].transaction_key
    assert "row_number" not in output.model_dump_json()


def test_review_displays_transaction_dates_and_movements():
    app = AppTest.from_string("""
from tests.integration.test_transactions import review, movement
from src.ui.statement_review import _render_balances
_render_balances(review(movement()).extraction.accounts[0])
""").run()
    assert not app.exception
    displayed = app.dataframe[0].value
    assert displayed.iloc[0]["Date"] == JANUARY.isoformat()
    assert displayed.iloc[0]["Withdrawal"] == "10.00"
    assert displayed.iloc[0]["Deposit"] == ""
    assert displayed.iloc[0]["Description"] == "Example transaction"
    assert not app.warning


def test_last_interest_transaction_supplies_closing_balance_without_extra_labels(store):
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [{
            "number": "1234",
            "balances": [{
                "as_of": JANUARY.isoformat(), "currency": "INR",
                "balance": "1315612.95", "withdrawal": "0.00", "deposit": "5351.00",
                "description": "Interest credit",
            }],
        }],
    })
    preview = StatementReview.create(b"fictional interest statement", "asset", output.to_domain())
    assert store.save_statement(preview, "Savings", "Example Bank") == 1
    saved = store.balance_history(JANUARY)[0]
    assert saved["deposit"] == "5351.00"
    assert saved["withdrawal"] == "0.00"
    assert saved["description"] == "Interest credit"
    assert store.portfolio(JANUARY, "INR").net_worth == Decimal("1315612.95")
