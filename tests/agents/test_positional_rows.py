import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.agents.field_repair import FieldRepairInference
from src.agents.output import BalanceOutput, StatementOutput
from src.agents.statement_agent import StatementAgent
from src.models.dto.statement_page import StatementPage
from src.models.entry.statement_review import StatementReview
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution
from src.ui.statement_batch import StatementBatchSession

ROW = ["2025-01-01", "100.25", "INR", None, "0.00", ""]


def statement(rows):
    return {"institution": {"name": "Example"}, "accounts": [
        {"number": "1234", "balances": rows},
    ]}


def document():
    return StatementDocument((StatementPage(1, "Fictional account 1234 statement"),))


def test_positional_row_converts_to_named_domain_fields():
    output = BalanceOutput.model_validate_json(json.dumps(ROW))
    assert output.to_wire_row() == ROW
    row = output.to_domain()
    assert row.balance == Decimal("100.25")
    assert row.currency == "INR"
    assert row.withdrawal is None
    assert row.deposit == Decimal("0.00")
    assert row.description == ""


@pytest.mark.parametrize("row", [ROW[:5], ROW + ["extra"], []])
def test_exactly_six_positions_are_required(row):
    with pytest.raises(ValidationError):
        BalanceOutput.model_validate_json(json.dumps(row))


@pytest.mark.parametrize(("position", "value"), [
    (0, None), (0, 123), (1, 100), (1, "1,000"), (2, "INT"),
    (3, -1), (3, "-1"), (4, 0), (4, ""), (5, None), (5, 123),
    (5, "x" * 2001),
])
def test_positions_keep_existing_strict_field_constraints(position, value):
    row = list(ROW)
    row[position] = value
    with pytest.raises(ValidationError):
        BalanceOutput.model_validate_json(json.dumps(row))


@pytest.mark.parametrize("movement", [None, "0", "0.00", "1.25"])
def test_nullable_and_zero_movement_positions(movement):
    row = list(ROW)
    row[3] = row[4] = movement
    if movement is None:
        with pytest.raises(ValidationError, match="both cannot be null"):
            BalanceOutput.model_validate_json(json.dumps(row))
    else:
        assert BalanceOutput.model_validate_json(json.dumps(row)).to_wire_row() == row


def test_swapped_date_and_balance_fail_validation():
    row = list(ROW)
    row[0], row[1] = row[1], row[0]
    with pytest.raises(ValidationError):
        BalanceOutput.model_validate_json(json.dumps(row))


@pytest.mark.parametrize(("position", "invalid", "correction_type"), [
    (2, "INT", "field_id"), (4, 2, "field_id"),
    (0, "not-a-date", "row_id"), (1, "1000000000000000001", "row_id"),
])
def test_positional_repairs_preserve_rows_and_do_not_regenerate(
    position, invalid, correction_type,
):
    expected = statement([list(ROW), list(ROW)])
    payload = deepcopy(expected)
    payload["accounts"][0]["balances"][1][position] = invalid
    runtime = MagicMock()
    runtime.generate.return_value = json.dumps(payload)
    replacement = ROW if correction_type == "row_id" else ROW[position]
    runtime.generate_structured.return_value = json.dumps({
        "corrections": [{correction_type: 0, "value": replacement}],
    })
    repaired = FieldRepairInference(runtime).generate(document(), "instructions")
    assert json.loads(repaired) == expected
    assert StatementOutput.model_validate_json(repaired).to_domain()
    runtime.generate.assert_called_once()
    runtime.generate_structured.assert_called_once()


def test_agent_accepts_compact_rows_and_keeps_repeated_transactions():
    runtime = MagicMock()
    runtime.generate.return_value = json.dumps(statement([ROW, ROW]))
    result = StatementAgent(FieldRepairInference(runtime)).parse(document())
    assert len(result.accounts[0].balances) == 2
    runtime.generate.assert_called_once()


def test_agent_merges_currency_sections_without_model_retry():
    payload = statement([ROW])
    payload["accounts"][0]["account_type"] = "Savings"
    payload["accounts"].append({
        "number": "12-34", "account_type": "currency_breakdown",
        "balances": [["2025-01-01", "11.01", "EUR", "0", "0", "Closing balance"]],
    })
    runtime = MagicMock()
    runtime.generate.return_value = json.dumps(payload)
    result = StatementAgent(FieldRepairInference(runtime)).parse(document())
    assert len(result.accounts) == 1
    assert result.accounts[0].account_type == "Savings"
    assert [row.currency for row in result.balances] == ["INR", "EUR"]
    runtime.generate.assert_called_once()
    runtime.generate_structured.assert_not_called()


def test_conflicting_summaries_reach_review_and_require_correction_before_save():
    extraction = StatementExtraction(
        (StatementAccount("1234", (
            StatementBalance(Decimal("11.01"), "EUR", date(2025, 1, 1)),
            StatementBalance(Decimal("16.05"), "EUR", date(2025, 1, 1)),
        )),),
        StatementInstitution("Example"),
    )
    review = StatementReview.create(b"statement", "asset", extraction)
    account = review.extraction.accounts[0]
    assert account.has_conflicting_summaries
    assert len(account.balances) == 2
    with pytest.raises(ValueError, match="before saving"):
        review.snapshots("Savings")
    batch = StatementBatchSession({})
    batch.begin([("one.pdf", b"statement")], "asset")
    session = batch.review_session(0)
    session.start(b"statement", "asset", extraction)
    with pytest.raises(ValueError, match="before saving"):
        batch.pending_snapshots()
    session.begin_edit(account.number)
    session.apply_balances(account.number, (account.balances[0],))
    assert batch.pending_snapshots()[0].balance == Decimal("11.01")
    assert review.with_account_balances(account.number, (account.balances[0],)).snapshots(
        "Savings",
    )[0].balance == Decimal("11.01")


def test_truncated_row_is_not_patched_or_silently_padded():
    runtime = MagicMock()
    runtime.generate.return_value = json.dumps(statement([ROW[:5]]))
    assert FieldRepairInference(runtime).generate(
        document(), "instructions",
    ) == runtime.generate.return_value
    runtime.generate_structured.assert_not_called()
