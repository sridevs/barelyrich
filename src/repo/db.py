
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from src.log_messages import error as error_messages
from src.repo.queries import load_query
from src.models.portfolio.institution import Institution


SCHEMA = load_query("schema")

def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(load_query("enable_foreign_keys"))
    return conn


@contextmanager
def database_session(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Commit or roll back each operation and always release its connection."""
    connection = connect(db_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialise(db_path: str | Path) -> None:
    with database_session(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate_account_numbers(conn)
        _migrate_account_product_types(conn)
        _migrate_account_balance_statement_source(conn)
        _migrate_institutions(conn)


def _migrate_account_product_types(conn: sqlite3.Connection) -> None:
    columns = conn.execute(load_query("select_account_columns")).fetchall()
    if "product_type" not in {column["name"] for column in columns}:
        conn.execute(load_query("migrate_account_product_type"))


def _migrate_account_numbers(conn: sqlite3.Connection) -> None:
    columns = conn.execute(load_query("select_account_columns")).fetchall()
    if "account_number" not in {column["name"] for column in columns}:
        _rebuild_numbered_accounts(conn, {column["name"] for column in columns})
    conn.execute(load_query("index_legacy_accounts"))
    conn.execute(load_query("index_numbered_accounts"))


def _rebuild_numbered_accounts(conn: sqlite3.Connection, columns: set[str]) -> None:
    conn.execute(load_query("disable_foreign_keys"))
    try:
        with conn:
            conn.execute(load_query("begin_immediate_transaction"))
            _copy_numbered_accounts(conn, columns)
            if conn.execute(load_query("check_foreign_keys")).fetchall():
                raise ValueError(error_messages.ACCOUNT_MIGRATION_WOULD_BREAK_EXISTING_REFERENCES)
    finally:
        conn.execute(load_query("enable_foreign_keys"))


def _copy_numbered_accounts(conn: sqlite3.Connection, columns: set[str]) -> None:
    # Preserve IDs referenced by balances, holdings and transactions.
    copy_query = (
        "migrate_numbered_accounts_copy" if "created_at" in columns
        else "migrate_numbered_accounts_copy_undated"
    )
    for query in (
        "migrate_numbered_accounts_create", copy_query,
        "migrate_numbered_accounts_drop", "migrate_numbered_accounts_rename",
    ):
        conn.execute(load_query(query))


def _migrate_institutions(conn: sqlite3.Connection) -> None:
    # Legacy identifiers remain stable; these are compatibility records, not an allowlist.
    conn.execute(load_query("seed_legacy_institutions"))
    for row in conn.execute(load_query("select_account_institutions")).fetchall():
        record = Institution(
            row["institution"], row["institution"], row["country_code"], row["account_type"],
        )
        _migrate_institution(conn, record)


def _migrate_institution(conn: sqlite3.Connection, record: Institution) -> None:
    conn.execute(
        load_query("insert_institution"),
        (record.key, record.name, record.normalized_name, record.country, record.account_type),
    )
    persisted = conn.execute(
        load_query("select_institution"),
        (record.key, record.normalized_name, record.key),
    ).fetchone()
    if persisted is None or persisted["key"] != record.key:
        raise ValueError(
            error_messages.INSTITUTION_MIGRATION_CONFLICT.format(record_key=record.key)
        )


def _migrate_account_balance_statement_source(conn: sqlite3.Connection) -> None:
    table = conn.execute(
        load_query("select_account_balances_schema")
    ).fetchone()
    if table is None or "'statement'" in table["sql"]:
        return
    with conn:
        conn.execute(load_query("begin_immediate_transaction"))
        conn.execute(load_query("migrate_statement_source_create_balances"))
        conn.execute(load_query("migrate_statement_source_copy_balances"))
        conn.execute(load_query("migrate_statement_source_drop_old_balances"))
        conn.execute(load_query("migrate_statement_source_rename_balances"))
