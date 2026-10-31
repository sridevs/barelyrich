"""Packaged SQL statements shared by SQLite adapters."""


import re
from functools import lru_cache
from importlib.resources import files

from src.log_messages import error as error_messages


def _validate_query_name(name: str) -> None:
    if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
        raise ValueError(error_messages.INVALID_SQL_RESOURCE_NAME.format(name=name))


@lru_cache(maxsize=128)
def load_query(name: str) -> str:
    """Read a named UTF-8 SQL resource, never a caller-supplied filesystem path."""
    _validate_query_name(name)
    resource = files(__package__).joinpath(f"{name}.sql")
    try:
        statement = resource.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(error_messages.SQL_RESOURCE_NOT_FOUND_SQL.format(name=name)) from exc
    if not statement.strip():
        raise ValueError(error_messages.SQL_RESOURCE_IS_EMPTY_SQL.format(name=name))
    return statement
