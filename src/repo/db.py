
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from src.repo.queries import load_query

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
