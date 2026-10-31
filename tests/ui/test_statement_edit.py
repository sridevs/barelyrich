from dataclasses import replace
from decimal import Decimal

import pytest

from src.ui.statement_batch import StatementBatchSession
from src.ui.statement_edit import _parse_row, _pending_rows, statement_row
from tests.statement_fixtures import statement_extraction


def test_editor_round_trip_preserves_decimal_precision_and_missing_movements():
    original = replace(
        statement_extraction().balances[0],
        balance=Decimal("1234.12345678"), withdrawal=Decimal("0.00"),
    )
    assert _parse_row(statement_row(original)) == original
    row = statement_row(original)
    row["Deposit"] = None
    row["Description"] = None
    assert _parse_row(row).deposit is None
    assert _parse_row(row).description == ""


@pytest.mark.parametrize("column,value", [
    ("Date", "2024-02-31"), ("Date", None), ("Currency", "XYZ"),
    ("Balance", ""), ("Balance", None), ("Balance", "NaN"),
    ("Balance", "1,234"), ("Balance", "0.123456789"),
    ("Withdrawal", "-1"), ("Deposit", "infinity"),
    ("Description", "x" * 2001),
])
def test_editor_rejects_invalid_values(column, value):
    row = statement_row(statement_extraction().balances[0])
    row[column] = value
    with pytest.raises(ValueError):
        _parse_row(row)


def test_batch_uses_applied_corrections_and_blocks_unapplied_edits():
    batch = StatementBatchSession({})
    batch.begin([("one.pdf", b"one"), ("two.pdf", b"two")], "asset")
    for index in (0, 1):
        batch.review_session(index).start(str(index).encode(), "asset", statement_extraction())
    original = batch.pending_snapshots()
    confirmation = batch.confirmation_key(original)
    session = batch.review_session(0)
    account = session.preview.extraction.accounts[0]
    original_review = session.preview
    session.begin_edit(account.number)
    with pytest.raises(ValueError, match="Apply or cancel"):
        batch.pending_snapshots()
    corrected = replace(account.balances[0], balance=Decimal("987.12345678"))
    session.apply_balances(account.number, (corrected,))
    saved = batch.pending_snapshots()
    assert saved[0].balance == Decimal("987.12345678")
    assert saved[1] == original[1]
    assert batch.confirmation_key(saved) != confirmation
    assert session.preview.confirmation_key("DBS") != original_review.confirmation_key("DBS")
    batch.move(1)
    batch.move(-1)
    assert batch.pending_snapshots() == saved
    session.begin_edit(account.number)
    session.cancel_edit()
    assert batch.pending_snapshots() == saved
    session.mark_account_saved(account.number)
    with pytest.raises(ValueError, match="Saved accounts"):
        session.begin_edit(account.number)


def test_editor_contains_only_transaction_fields():
    assert tuple(statement_row(statement_extraction().balances[0])) == (
        "Date", "Currency", "Balance", "Withdrawal", "Deposit", "Description",
    )


def test_native_pending_rows_preserve_exact_values_additions_and_deletions():
    source = [statement_row(row) for row in statement_extraction().balances]
    original = dict(source[0])
    rows = _pending_rows(source, {
        "edited_rows": {0: {"Balance": "999.12345678"}},
        "added_rows": [{"Description": "Incomplete row", "Balance": None}],
        "deleted_rows": [],
    })
    assert rows[0]["Balance"] == "999.12345678"
    assert rows[1] == {"Description": "Incomplete row", "Balance": None}
    assert source[0] == original
    assert _pending_rows(source, {
        "edited_rows": {}, "added_rows": [], "deleted_rows": list(range(len(source))),
    }) == []
