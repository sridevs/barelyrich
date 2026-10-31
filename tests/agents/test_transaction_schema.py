
import pytest
from pydantic import ValidationError

from src.agents.output import BalanceOutput, StatementOutput
from src.agents.statement_agent import StatementAgent
from src.agents.statement_prompt import STATEMENT_INSTRUCTIONS
from tests.statement_fixtures import RepairingRuntime, text_document


@pytest.mark.parametrize("positional", [False, True])
@pytest.mark.parametrize(("withdrawal", "deposit"), [
    (None, None), ("1.00", None), (None, "1.00"), ("0", None),
    (None, "0.00"), ("1.00", "2.00"),
])
def test_transaction_requires_a_movement(positional, withdrawal, deposit):
    row = ["2025-11-18", "100", "SGD", withdrawal, deposit, "Description"]
    value = row if positional else dict(zip(BalanceOutput.COLUMNS, row))
    if withdrawal is None and deposit is None:
        with pytest.raises(ValidationError, match="both cannot be null"):
            BalanceOutput.model_validate(value)
    else:
        result = BalanceOutput.model_validate(value)
        assert result.to_wire_row() == row
        result.to_domain()


def test_generated_schema_requires_one_movement_position_to_be_a_string():
    schema = StatementOutput.model_json_schema()["$defs"]["BalanceOutput"]
    assert len(schema["anyOf"]) == 2
    for position, branch in zip((3, 4), schema["anyOf"], strict=True):
        assert branch["type"] == "array"
        assert branch["minItems"] == branch["maxItems"] == 6
        assert len(branch["prefixItems"]) == 6
        assert branch["prefixItems"][position]["type"] == "string"
        assert "pattern" in branch["prefixItems"][position]
        assert branch["prefixItems"][5]["type"] == "string"
        for index in set(range(6)) - {position}:
            assert branch["prefixItems"][index] == schema["prefixItems"][index]
    assert schema["minItems"] == schema["maxItems"] == 6
    assert "Omit currencies without transactions" in STATEMENT_INSTRUCTIONS
    assert "Skip opening, closing and page carry-forward summaries" in STATEMENT_INSTRUCTIONS


def test_both_null_error_reaches_model_retry_without_dropping_transaction():
    runtime = RepairingRuntime(
        ["2025-11-18", "100", "SGD", None, None, "Interest"],
        ["2025-11-18", "100", "SGD", None, "1.00", "Interest"],
    )
    result = StatementAgent(runtime).parse(text_document())
    assert len(runtime.prompts) == 2
    assert "both cannot be null" in runtime.prompts[1]
    assert len(result.balances) == 1
    assert str(result.balances[0].deposit) == "1.00"
