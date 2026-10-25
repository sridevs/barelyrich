"""Balance-only review persistence, atomic replacement and legacy data compatibility."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import sqlite3
from unittest.mock import create_autospec

import pytest

from tests.statement_fixtures import statement_extraction
from src.models.entry.statement_review import StatementReview
from src.repo.contracts import BalanceWriter
from src.repo.db import database_session, initialise
from src.repo.portfolio import PortfolioStore
from src.service.portfolio import PortfolioActions


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    return PortfolioStore(path)


def review():
    content = b"fictional statement"
    extraction = statement_extraction()
    return StatementReview.create(content, "asset", extraction)


def test_review_save_returns_balance_count_and_delegates_to_atomic_writer():
    writer = create_autospec(BalanceWriter, instance=True)
    writer.save_statement.return_value = 1
    preview = review()
    assert PortfolioActions(writer).save_statement_review(preview, "Savings", "DBS") == 1
    writer.save_statement.assert_called_once_with(preview, "Savings", "DBS")


def test_review_replaces_exact_currency_set_and_retains_decimal_balances(store):
    preview = review()
    balance = preview.extraction.balances[0]
    multi = replace(preview, extraction=replace(
        preview.extraction,
        accounts=(replace(preview.extraction.accounts[0], balances=(
            balance, replace(balance, currency="USD", balance=Decimal("15.00")),
        )),),
    ))
    assert store.save_statement(multi, "Savings", "DBS") == 2
    assert len(store.balance_history(date.today())) == 2
    assert store.save_statement(preview, "Renamed", "DBS") == 1
    rows = store.balance_history(date.today())
    assert len(rows) == 1
    assert rows[0]["balance"] == "1234.50"
    assert store.portfolio(date.today(), "SGD").accounts[0].account == "Renamed SGD"


def test_failed_second_balance_rolls_back_replacement_alias_and_first_insert(store):
    preview = review()
    store.save_statement(preview, "Savings", "DBS")
    old_balances = store.balance_history(date.today())
    balance = preview.extraction.balances[0]
    changed = replace(preview, extraction=replace(
        preview.extraction,
        accounts=(replace(preview.extraction.accounts[0], balances=(
            replace(balance, balance=Decimal("500")),
            replace(balance, currency="USD", balance=Decimal("15")),
        )),),
    ))
    with database_session(store.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_usd BEFORE INSERT ON account_balances "
            "WHEN (SELECT currency FROM accounts WHERE id = NEW.account_id) = 'USD' "
            "BEGIN SELECT RAISE(ABORT, 'second balance failed'); END"
        )
    with pytest.raises(sqlite3.DatabaseError, match="second balance failed"):
        store.save_statement(changed, "Changed alias", "DBS")
    assert store.balance_history(date.today()) == old_balances
    assert store.portfolio(date.today(), "SGD").accounts[0].account == "Savings SGD"


def test_initialise_and_balance_reimport_leave_legacy_transaction_records_untouched(store):
    preview = review()
    store.save_statement(preview, "Savings", "DBS")
    with database_session(store.path) as conn:
        account_id = conn.execute("SELECT id FROM accounts").fetchone()[0]
        conn.execute(
            "INSERT INTO transactions(account_id,transaction_date,transaction_type,amount,currency) "
            "VALUES (?, '2026-01-01', 'deposit', '7.50', 'SGD')", (account_id,),
        )
        conn.execute(
            "INSERT INTO statement_transactions(account_id,source_file_hash,row_number,"
            "transaction_date,description,amount,currency,direction,page_number,quote) "
            "VALUES (?, 'legacy', 1, '2026-01-01', 'Legacy record', '2.50', 'SGD',"
            "'debit', 1, 'Legacy record')", (account_id,),
        )
        legacy = {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in ("transactions", "statement_transactions")
        }
    initialise(store.path)
    initialise(store.path)
    store.save_statement(preview, "Renamed", "DBS")
    with database_session(store.path) as conn:
        for table, previous in legacy.items():
            assert [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")] == previous
