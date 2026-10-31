import sqlite3

import pytest

from src.repo.db import connect, database_session, initialise


def test_initialise_creates_current_schema_without_legacy_tables(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    with database_session(path) as connection:
        tables = {row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "transactions" in tables
        assert not {"account_balances", "statement_transactions", "transactions_new", "accounts_numbered"} & tables
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(accounts)")}
        assert {"account_number", "product_type", "created_at"} <= columns
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(transactions)")}
        assert {"withdrawal", "deposit", "description", "transaction_key", "row_number"} <= columns
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_initialise_is_idempotent_and_preserves_current_data(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    with database_session(path) as connection:
        connection.execute(
            "INSERT INTO accounts(id,name,institution,country_code,account_type,currency,account_number,product_type) "
            "VALUES(42,'Savings','dbs_sg','SG','bank','SGD','1234','Savings')"
        )
        connection.execute(
            "INSERT INTO transactions(account_id,as_of,balance,source,withdrawal,description,transaction_key,row_number) "
            "VALUES(42,'2024-01-31','100.25','statement','10','Example debit','row-1',1)"
        )
        accounts = [tuple(row) for row in connection.execute("SELECT * FROM accounts")]
        transactions = [tuple(row) for row in connection.execute("SELECT * FROM transactions")]
        institutions = [tuple(row) for row in connection.execute("SELECT * FROM institutions")]
    initialise(path)
    initialise(path)
    with database_session(path) as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM accounts")] == accounts
        assert [tuple(row) for row in connection.execute("SELECT * FROM transactions")] == transactions
        assert [tuple(row) for row in connection.execute("SELECT * FROM institutions")] == institutions
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO accounts(name,institution,country_code,account_type,currency,account_number) "
                "VALUES('Other alias','dbs_sg','SG','bank','SGD','1234')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transactions(account_id,as_of,balance,source) "
                "VALUES(999,'2024-01-31','100','statement')"
            )


def test_database_session_commits_rows_and_closes_connection(tmp_path):
    path = tmp_path / "session.sqlite3"
    with database_session(path) as connection:
        connection.execute("CREATE TABLE observations (amount TEXT NOT NULL)")
        connection.execute("INSERT INTO observations VALUES ('10.25')")
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with database_session(path) as saved:
        assert saved.execute("SELECT amount FROM observations").fetchone()["amount"] == "10.25"


def test_database_session_rolls_back_entire_batch_and_closes_on_error(tmp_path):
    path = tmp_path / "session.sqlite3"
    with database_session(path) as setup:
        setup.execute("CREATE TABLE observations (amount TEXT NOT NULL)")
    with pytest.raises(ValueError, match="invalid import"):
        with database_session(path) as connection:
            connection.execute("INSERT INTO observations VALUES ('10.25')")
            raise ValueError("invalid import")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with database_session(path) as saved:
        assert saved.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_low_level_connect_retains_caller_owned_lifetime(tmp_path):
    connection = connect(tmp_path / "session.sqlite3")
    try:
        with connection:
            assert connection.execute("SELECT 1").fetchone()[0] == 1
        assert connection.execute("SELECT 2").fetchone()[0] == 2
    finally:
        connection.close()
