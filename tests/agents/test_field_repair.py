import json
import logging
from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.agents.field_repair import FieldRepairInference
from src.agents.output import StatementOutput
from src.agents.response import StatementParsingError
from src.agents.statement_agent import StatementAgent
from src.inference.progress import InferenceProgress, observe
from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_document import StatementDocument


@pytest.fixture
def payload():
    return {
        "institution": {"name": "Fictional Bank"},
        "accounts": [{
            "number": "DEMO1234",
            "balances": [
                {
                    "withdrawal": None,
                    "balance": str(100 + index), "currency": "INR",
                    "as_of": "2026-09-01",
                    "deposit": "1.00", "description": f"Fictional transaction {index}",
                }
                for index in range(30)
            ],
        }],
    }


def document():
    return StatementDocument((StatementPage(1, "Original fictional INR statement. Account DEMO1234."),))


def runtime_for(payload, corrections):
    runtime = MagicMock()
    runtime.generate.return_value = json.dumps(payload)
    runtime.generate_structured.return_value = json.dumps({"corrections": corrections})
    return runtime


def test_repairs_one_typo_preserving_every_other_field_and_uses_source(payload, caplog):
    expected = deepcopy(payload)
    payload["accounts"][0]["balances"][19]["currency"] = "INT"
    runtime = runtime_for(payload, [{"field_id": 0, "value": "INR"}])
    progress = InferenceProgress()
    source = document()
    with observe(progress), caplog.at_level(logging.INFO):
        repaired = FieldRepairInference(runtime).generate(source, "original instructions")
    assert json.loads(repaired) == expected
    assert StatementOutput.model_validate_json(repaired).to_domain()
    runtime.generate.assert_called_once_with(source, "original instructions")
    runtime.generate_structured.assert_called_once()
    args = runtime.generate_structured.call_args.args
    assert args[0] is source
    assert '"INT"' in args[1]
    assert "Fictional transaction 19" in args[1]
    assert "Fictional transaction 0" not in args[1]
    assert "required_schema" in args[1] and '"INR"' in args[1]
    assert "Fictional transaction" not in caplog.text
    assert "INT" not in caplog.text
    assert any("Repairing 1 rejected fields" in label for label, _ in progress.snapshot().timings)
    assert progress.snapshot().stage == "Revalidating repaired statement"


def test_multiple_fields_are_mapped_by_id_not_response_order(payload):
    payload["accounts"][0]["balances"][0]["currency"] = "INT"
    payload["accounts"][0]["balances"][1]["deposit"] = 2
    runtime = runtime_for(payload, [
        {"field_id": 1, "value": "2.00"}, {"field_id": 0, "value": "INR"},
    ])
    result = json.loads(FieldRepairInference(runtime).generate(document(), "instructions"))
    assert result["accounts"][0]["balances"][1]["deposit"] == "2.00"
    assert result["accounts"][0]["balances"][0]["currency"] == "INR"


def test_shared_agent_accepts_repaired_output_without_full_document_retry(payload):
    payload["accounts"][0]["balances"][19]["currency"] = "INT"
    runtime = runtime_for(payload, [{"field_id": 0, "value": "INR"}])
    result = StatementAgent(
        FieldRepairInference(runtime),
    ).parse(document())
    assert len(result.accounts[0].balances) == 30
    assert all(row.currency == "INR" for row in result.accounts[0].balances)
    assert runtime.generate.call_count == 1
    assert runtime.generate_structured.call_count == 1


@pytest.mark.parametrize("corrections", [
    [], [{"field_id": 0, "value": "INT"}],
    [{"field_id": 0, "value": None}],
    [{"field_id": 1, "value": "INR"}],
    [{"field_id": 0, "value": "INR"}, {"field_id": 0, "value": "INR"}],
    [{"field_id": 0, "value": "INR", "balance": "999.00"}],
    [{"field_id": 0, "value": {"currency": "INR"}}],
])
def test_invalid_repairs_fail_without_regenerating_or_accepting_partial_data(payload, corrections):
    payload["accounts"][0]["balances"][19]["currency"] = "INT"
    runtime = runtime_for(payload, corrections)
    agent = StatementAgent(FieldRepairInference(runtime))
    with pytest.raises(StatementParsingError, match="Targeted field correction failed"):
        agent.parse(document())
    assert runtime.generate.call_count == 1
    assert runtime.generate_structured.call_count == 1


def test_full_financial_validation_still_rejects_repaired_schema(payload):
    payload["accounts"][0]["balances"][19]["currency"] = "INT"
    payload["accounts"][0]["balances"][0]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, [{"field_id": 0, "value": "INR"}])
    with pytest.raises(StatementParsingError, match="failed full validation"):
        FieldRepairInference(runtime).generate(document(), "instructions")
    assert runtime.generate.call_count == 1


@pytest.mark.parametrize("response", [
    "{", "{}", "[]",
    '{"institution":{"name":"Bank"},"accounts":[]}',
])
def test_nonrepairable_structure_keeps_existing_flow(response):
    runtime = MagicMock()
    runtime.generate.return_value = response
    assert FieldRepairInference(runtime).generate(document(), "instructions") == response
    runtime.generate_structured.assert_not_called()


def test_valid_response_is_returned_unchanged(payload):
    runtime = runtime_for(payload, [])
    response = runtime.generate.return_value
    assert FieldRepairInference(runtime).generate(document(), "instructions") == response
    runtime.generate_structured.assert_not_called()


def test_large_error_set_is_not_repaired(payload):
    for row in payload["accounts"][0]["balances"]:
        row["currency"] = "INT"
    runtime = runtime_for(payload, [])
    assert FieldRepairInference(runtime).generate(document(), "instructions") == runtime.generate.return_value
    runtime.generate_structured.assert_not_called()


def test_repair_runtime_errors_propagate_without_full_regeneration(payload):
    payload["accounts"][0]["balances"][0]["currency"] = "INT"
    runtime = runtime_for(payload, [])
    runtime.generate_structured.side_effect = ValueError("Ollama timeout")
    with pytest.raises(ValueError, match="Ollama timeout"):
        FieldRepairInference(runtime).generate(document(), "instructions")
    assert runtime.generate.call_count == 1


def test_account_field_context_does_not_repeat_entire_statement(payload):
    payload["accounts"][0]["account_type"] = 123
    runtime = runtime_for(payload, [{"field_id": 0, "value": "Savings"}])
    result = json.loads(FieldRepairInference(runtime).generate(document(), "instructions"))
    assert result["accounts"][0]["account_type"] == "Savings"
    assert "Fictional transaction" not in runtime.generate_structured.call_args.args[1]


@pytest.mark.parametrize("invalid", [
    {"balance": "1000000000000000001"},
    {"as_of": "not-a-date"},
])
def test_financial_row_repair_preserves_every_other_row_without_full_retry(payload, invalid):
    expected = deepcopy(payload)
    corrected = deepcopy(payload["accounts"][0]["balances"][19])
    payload["accounts"][0]["balances"][19].update(invalid)
    runtime = runtime_for(payload, [{"row_id": 0, "value": corrected}])
    source = document()
    progress = InferenceProgress()
    with observe(progress):
        result = StatementAgent(
            FieldRepairInference(runtime),
        ).parse(source)
    assert len(result.accounts[0].balances) == 30
    assert result == StatementOutput.model_validate(expected).to_domain()
    runtime.generate.assert_called_once()
    runtime.generate_structured.assert_called_once()
    args = runtime.generate_structured.call_args.args
    assert args[0] is source
    assert "Fictional transaction 19" in args[1]
    assert "Fictional transaction 0" not in args[1]
    assert "balance differences" in args[1]
    assert any(
        label == "Revalidating repaired statement"
        for label, _ in progress.snapshot().timings
    )


def test_final_interest_credit_needs_no_classification_or_repair(payload):
    interest = {
        "balance": "1315612.95", "currency": "INR", "as_of": "2026-09-30",
        "deposit": "5351.00", "withdrawal": "0.00",
        "description": "Interest credit",
    }
    payload["accounts"][0]["balances"].append(interest)
    runtime = runtime_for(payload, [])
    repaired = json.loads(FieldRepairInference(runtime).generate(document(), "instructions"))
    assert repaired == payload
    assert StatementOutput.model_validate(repaired).to_domain().balances[-1].deposit == Decimal("5351.00")
    runtime.generate.assert_called_once()
    runtime.generate_structured.assert_not_called()


@pytest.mark.parametrize("corrections", [
    [], [{"row_id": 1, "value": {}}],
    [{"row_id": 0, "value": {}}],
])
def test_invalid_row_corrections_stop_without_full_retry(payload, corrections):
    payload["accounts"][0]["balances"][0]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, corrections)
    with pytest.raises(StatementParsingError):
        StatementAgent(
            FieldRepairInference(runtime),
        ).parse(document())
    runtime.generate.assert_called_once()
    runtime.generate_structured.assert_called_once()


def test_duplicate_row_ids_and_still_invalid_financial_rows_are_rejected(payload):
    row = deepcopy(payload["accounts"][0]["balances"][0])
    payload["accounts"][0]["balances"][0]["as_of"] = "not-a-date"
    payload["accounts"][0]["balances"][1]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, [
        {"row_id": 0, "value": row}, {"row_id": 0, "value": row},
    ])
    with pytest.raises(StatementParsingError):
        FieldRepairInference(runtime).generate(document(), "instructions")
    runtime.generate_structured.return_value = json.dumps({"corrections": [
        {"row_id": 0, "value": payload["accounts"][0]["balances"][0]},
        {"row_id": 1, "value": payload["accounts"][0]["balances"][1]},
    ]})
    with pytest.raises(StatementParsingError):
        FieldRepairInference(runtime).generate(document(), "instructions")


def test_multiple_row_corrections_are_mapped_by_id(payload):
    expected = deepcopy(payload)
    rows = payload["accounts"][0]["balances"]
    corrections = [
        {"row_id": 1, "value": deepcopy(rows[10])},
        {"row_id": 0, "value": deepcopy(rows[0])},
    ]
    rows[0]["as_of"] = "not-a-date"
    rows[10]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, corrections)
    result = FieldRepairInference(runtime).generate(document(), "instructions")
    assert json.loads(result) == expected


def test_schema_then_row_repair_are_both_bounded(payload):
    expected = deepcopy(payload)
    payload["accounts"][0]["balances"][19]["currency"] = "INT"
    payload["accounts"][0]["balances"][0]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, [])
    runtime.generate_structured.side_effect = [
        json.dumps({"corrections": [{"field_id": 0, "value": "INR"}]}),
        json.dumps({"corrections": [{
            "row_id": 0, "value": expected["accounts"][0]["balances"][0],
        }]}),
    ]
    assert json.loads(FieldRepairInference(runtime).generate(document(), "instructions")) == expected
    runtime.generate.assert_called_once()
    assert runtime.generate_structured.call_count == 2


def test_excessive_financial_row_errors_keep_existing_flow(payload):
    for row in payload["accounts"][0]["balances"][:9]:
        row["as_of"] = "not-a-date"
    runtime = runtime_for(payload, [])
    assert FieldRepairInference(runtime).generate(document(), "instructions") == runtime.generate.return_value
    runtime.generate_structured.assert_not_called()


def test_zero_withdrawal_with_positive_deposit_needs_no_repair(payload):
    payload["accounts"][0]["balances"][0]["withdrawal"] = "0.00"
    runtime = runtime_for(payload, [])
    assert FieldRepairInference(runtime).generate(document(), "instructions") == runtime.generate.return_value
    runtime.generate_structured.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_financial_failure_logging_includes_output_only_when_enabled(payload, caplog, enabled):
    row = deepcopy(payload["accounts"][0]["balances"][19])
    payload["accounts"][0]["balances"][19]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, [{"row_id": 0, "value": row}])
    with caplog.at_level(logging.WARNING):
        FieldRepairInference(runtime, log_model_output=enabled).generate(document(), "instructions")
    assert '"accounts", 0, "balances", 19' in caplog.text
    assert '"reason":' in caplog.text
    assert ("Fictional transaction 19" in caplog.text) is enabled
    assert ("SENSITIVE:" in caplog.text) is enabled


def test_invalid_correction_output_is_logged_when_enabled(payload, caplog):
    payload["accounts"][0]["balances"][0]["as_of"] = "not-a-date"
    runtime = runtime_for(payload, [])
    with caplog.at_level(logging.WARNING), pytest.raises(StatementParsingError):
        FieldRepairInference(runtime, log_model_output=True).generate(document(), "instructions")
    assert "row_correction_failed_full_validation" in caplog.text
    assert "corrections" in caplog.text


def test_zero_only_movement_reaches_review_without_repair(payload):
    payload["accounts"][0]["balances"][0].update(deposit="0.00", withdrawal="0.00")
    runtime = runtime_for(payload, [])
    result = StatementAgent(
        FieldRepairInference(runtime),
    ).parse(document())
    assert result.accounts[0].balances[0].deposit == Decimal("0.00")
    runtime.generate.assert_called_once()
    runtime.generate_structured.assert_not_called()


def test_schema_failure_logging_hides_unknown_field_names(payload, caplog):
    payload["private-extra-data"] = "private-value"
    runtime = runtime_for(payload, [])
    with caplog.at_level(logging.WARNING):
        FieldRepairInference(runtime).generate(document(), "instructions")
    assert "extra_forbidden" in caplog.text
    assert "private-extra-data" not in caplog.text
    assert "private-value" not in caplog.text
