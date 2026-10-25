import json

from src.agents.response import STATEMENT_RESPONSE_SCHEMA
from src.agents.output import StatementOutput
from src.agents.statement_prompt import (
    STATEMENT_INSTRUCTIONS, STATEMENT_RESPONSE_EXAMPLE, build_statement_prompt,
)
from src.models.currencies import ISO_CURRENCY_REFERENCE
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage


def test_prompt_uses_one_example_without_schema_or_currency_reference_overhead():
    document = StatementDocument((
        StatementPage(2, b"private image content"),
        StatementPage(5, b"private image content"),
    ))

    prompt = build_statement_prompt(document)

    assert json.dumps(STATEMENT_RESPONSE_SCHEMA) not in prompt
    assert ISO_CURRENCY_REFERENCE not in prompt
    assert json.dumps(STATEMENT_RESPONSE_EXAMPLE, separators=(",", ":")) in prompt
    assert "Page metadata: [2, 5].\n" in prompt
    assert "private image content" not in prompt
    assert "For fixed/term deposits" in prompt


def test_prompt_metadata_is_document_specific():
    first = build_statement_prompt(StatementDocument((StatementPage(1, b"image"),)))
    second = build_statement_prompt(StatementDocument((StatementPage(3, b"image"),)))

    assert first.replace("Page metadata: [1]", "Page metadata: [3]") == second


def test_instructions_and_complete_prompt_have_a_concise_budget():
    assert len(STATEMENT_INSTRUCTIONS.split()) <= 400
    prompt = build_statement_prompt(StatementDocument((StatementPage(1, b"image"),)))
    assert len(prompt) <= 4500
    for heading in ("SOURCE", "ACCOUNT AND ISSUER", "CLASSIFICATION", "OUTPUT"):
        assert f"\n{heading}\n" in STATEMENT_INSTRUCTIONS
    assert "\nTRANSACTIONS\n" not in STATEMENT_INSTRUCTIONS


def test_example_matches_validated_contract_and_keeps_fixed_deposit_separate():
    output = StatementOutput.model_validate(STATEMENT_RESPONSE_EXAMPLE)
    assert len(output.accounts) == 2
    savings, deposit = output.accounts
    assert savings.account_type == "Savings"
    assert deposit.account_type == "Fixed deposit"
    assert "Infer it from headings and context" in STATEMENT_INSTRUCTIONS
    assert savings.number != deposit.number
    assert [balance.currency for balance in savings.balances] == ["SGD", "EUR"]
    assert [(balance.currency, balance.balance) for balance in deposit.balances] == [
        ("SGD", "100.00"),
    ]
    assert "evidence" not in json.dumps(STATEMENT_RESPONSE_EXAMPLE)
    assert "evidence" not in json.dumps(STATEMENT_RESPONSE_SCHEMA)
    assert "quote" not in json.dumps(STATEMENT_RESPONSE_SCHEMA)
