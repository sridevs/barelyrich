import sqlite3

import pytest

from src.repo.db import connect, database_session


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
