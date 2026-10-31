import ast
import re
import sqlite3
import tomllib
from importlib.resources import files
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.repo import queries
from src.repo.db import SCHEMA

PROJECT = Path(__file__).resolve().parents[2]
RESOURCE_NAMES = sorted(
    resource.name.removesuffix(".sql")
    for resource in files(queries).iterdir() if resource.name.endswith(".sql")
)


@pytest.mark.parametrize("name", RESOURCE_NAMES)
def test_all_sql_resources_are_readable_and_declared_as_package_data(name):
    configuration = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = configuration["tool"]["setuptools"]["package-data"][queries.__name__]
    assert any(Path(f"{name}.sql").match(pattern) for pattern in patterns)
    statement = queries.load_query(name)
    assert statement.strip()
    assert statement == files(queries).joinpath(f"{name}.sql").read_text(encoding="utf-8")


def test_schema_constant_remains_a_loaded_sql_string():
    assert SCHEMA == queries.load_query("schema")
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(SCHEMA)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_query_loader_caches_resource_reads():
    queries.load_query.cache_clear()
    try:
        first = queries.load_query("count_accounts")
        assert queries.load_query("count_accounts") is first
        assert queries.load_query.cache_info().hits == 1
    finally:
        queries.load_query.cache_clear()


def test_query_loader_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    queries.load_query.cache_clear()
    monkeypatch.chdir(tmp_path)
    assert queries.load_query("count_accounts").strip()


@pytest.mark.parametrize("name", [
    "", "../schema", "/schema", "schema.sql", "nested/schema", r"nested\schema",
    "schema;DROP", "Schema", " schema", "schema\n",
])
def test_query_loader_rejects_paths_and_invalid_names(name):
    with pytest.raises(ValueError, match="Invalid SQL resource name"):
        queries.load_query(name)


def test_query_loader_surfaces_missing_resources():
    with pytest.raises(FileNotFoundError, match="SQL resource not found: missing_query.sql"):
        queries.load_query("missing_query")


def test_query_loader_rejects_empty_resources(monkeypatch):
    resource_root = Mock()
    resource_root.joinpath.return_value.read_text.return_value = " \n"
    monkeypatch.setitem(vars(queries), "files", Mock(return_value=resource_root))
    with pytest.raises(ValueError, match="SQL resource is empty: empty_query.sql"):
        queries.load_query("empty_query")


def test_application_python_contains_no_inline_sql():
    sql_start = re.compile(
        r"^\s*(?:SELECT\s+(?:[\s\S]+\sFROM\b|[0-9*])|"
        r"INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b|DELETE\s+FROM\b|"
        r"CREATE\s+(?:TABLE|INDEX)\b|ALTER\s+TABLE\b|DROP\s+(?:TABLE|INDEX)\b|"
        r"PRAGMA\b|BEGIN\s+(?:IMMEDIATE|TRANSACTION)\b|ON\s+CONFLICT\b|"
        r"DO\s+(?:UPDATE|NOTHING)\b)", re.IGNORECASE,
    )
    violations = []
    source_files = [PROJECT / "app.py", *(PROJECT / "src").rglob("*.py")]
    for source_file in source_files:
        for node in ast.walk(ast.parse(source_file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if sql_start.match(node.value):
                    violations.append(f"{source_file.relative_to(PROJECT)}:{node.lineno}")
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "executemany", "executescript"}
                and node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr, ast.BinOp))
            ):
                violations.append(f"Inline/dynamic SQL at {source_file.name}:{node.lineno}")
    assert not violations, "\n".join(violations)
