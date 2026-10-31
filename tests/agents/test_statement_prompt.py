import json

from src.agents.output import StatementOutput
from src.agents.response import STATEMENT_RESPONSE_SCHEMA
from src.agents.statement_prompt import (
    OUTPUT_RETRY_INSTRUCTIONS,
    STATEMENT_INSTRUCTIONS,
    build_statement_prompt,
)
from src.models.currencies import ISO_CURRENCY_REFERENCE
from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_document import StatementDocument
from tests.prompt_fixtures import STATEMENT_RESPONSE_EXAMPLE
from tests.statement_fixtures import text_document


def test_prompt_excludes_populated_examples_and_schema_overhead():
    document = StatementDocument((
        StatementPage(2, "private statement text"),
        StatementPage(5, "private statement text"),
    ))

    prompt = build_statement_prompt(document)

    assert json.dumps(STATEMENT_RESPONSE_SCHEMA) not in prompt
    assert ISO_CURRENCY_REFERENCE not in prompt
    assert json.dumps(STATEMENT_RESPONSE_EXAMPLE, separators=(",", ":")) not in prompt
    for fictional_value in ("Example Bank", "****1234", "2025-09-29", "9.25", "14.25"):
        assert fictional_value not in prompt
    assert "example" not in prompt.lower()
    assert "example" not in OUTPUT_RETRY_INSTRUCTIONS.lower()
    assert "Page metadata: [2, 5].\n" in prompt
    assert "private statement text" not in prompt
    assert "Follow printed withdrawal/debit and deposit/credit columns" in prompt
    assert "Never invent amounts" in prompt


def test_prompt_metadata_is_document_specific():
    first = build_statement_prompt(text_document())
    second = build_statement_prompt(StatementDocument((StatementPage(3, "statement text"),)))

    assert first.replace("Page metadata: [1]", "Page metadata: [3]") == second


def test_prompt_retains_zero_movements_but_omits_balance_summaries():
    prompt = build_statement_prompt(StatementDocument((StatementPage(1, "statement"),)))
    assert "preserve printed zeros" in prompt
    assert "Omit currencies without transactions" in prompt
    assert "Skip opening, closing and page carry-forward summaries" in prompt
    assert "not a withdrawal/deposit total" in prompt


def test_prompt_requires_printed_transaction_movements_instead_of_two_nulls():
    assert "Copy every printed transaction amount" in STATEMENT_INSTRUCTIONS
    assert "only the unused movement is null" in STATEMENT_INSTRUCTIONS
    assert "At least one movement must be non-null" in STATEMENT_INSTRUCTIONS
    assert "Use null for blank movements" not in STATEMENT_INSTRUCTIONS
    assert "Never invent amounts" in STATEMENT_INSTRUCTIONS


def test_instructions_and_complete_prompt_have_a_concise_budget():
    assert len(STATEMENT_INSTRUCTIONS.split()) <= 260
    prompt = build_statement_prompt(text_document())
    assert len(prompt) <= 2200
    assert "Exclude rows with BOTH movements" not in STATEMENT_INSTRUCTIONS
    assert "Skip opening, closing and page carry-forward summaries" in STATEMENT_INSTRUCTIONS
    assert "cross-check" not in STATEMENT_INSTRUCTIONS
    assert "preserve printed zeros" in STATEMENT_INSTRUCTIONS
    assert all(
        line.startswith(("- ", "  "))
        for line in STATEMENT_INSTRUCTIONS.splitlines()
    )


def test_prompt_distinguishes_transaction_dr_cr_labels_from_balance_labels():
    document = StatementDocument((StatementPage(1, "CSV statement"),))
    prompt = build_statement_prompt(document)
    assert "Transaction DR/debit means withdrawal; CR/credit means deposit (case-insensitive)" in prompt
    assert "separate DR/CR indicator or amount suffix" in prompt
    assert "nonnegative\n  amount in the indicated movement; the other is null" in prompt
    assert "A positive amount alone does not mean credit" in prompt
    assert "DR/CR on a balance describes that balance, not transaction direction" in prompt


def test_prompt_preserves_full_descriptions_for_later_categorization():
    assert "Copy the full description, joining continuation lines with merchant/payee details" in STATEMENT_INSTRUCTIONS


def test_prompt_groups_currency_sections_under_the_printed_account():
    assert "Keep different account numbers separate" in STATEMENT_INSTRUCTIONS
    assert (
        "Currency sections and continuation pages retain their enclosing account number "
        "unless another is printed."
    ) in STATEMENT_INSTRUCTIONS
    assert "Group currencies under that account" in STATEMENT_INSTRUCTIONS
    assert 'or use "null"/"N/A"' in STATEMENT_INSTRUCTIONS
    assert "never invent an account number" in STATEMENT_INSTRUCTIONS
    assert "uppercase ISO currency" in STATEMENT_INSTRUCTIONS


def test_prompt_distinguishes_original_balances_from_converted_equivalents():
    assert "Use the table's ledger currency, not currencies in descriptions" in STATEMENT_INSTRUCTIONS
    assert "Never copy transactions between\n  currency sections" in STATEMENT_INSTRUCTIONS
    assert "Ignore indicative conversions and converted equivalents" in STATEMENT_INSTRUCTIONS


def test_example_matches_contract_and_demonstrates_both_movement_directions():
    output = StatementOutput.model_validate(STATEMENT_RESPONSE_EXAMPLE)
    assert len(output.accounts) == 1
    savings = output.accounts[0]
    assert savings.account_type == "Savings"
    debit, credit = savings.balances
    assert debit.withdrawal == "1.00" and debit.deposit is None
    assert credit.withdrawal is None and credit.deposit == "5.00"
    assert all(row.withdrawal is not None or row.deposit is not None for row in savings.balances)
    assert "evidence" not in json.dumps(STATEMENT_RESPONSE_EXAMPLE)
    assert "evidence" not in json.dumps(STATEMENT_RESPONSE_SCHEMA)
    assert "quote" not in json.dumps(STATEMENT_RESPONSE_SCHEMA)
    for field in ("balance_role", "account_scope", "date_role", "row_number"):
        assert field not in json.dumps(STATEMENT_RESPONSE_SCHEMA)
        assert field not in json.dumps(STATEMENT_RESPONSE_EXAMPLE)
        assert field not in STATEMENT_INSTRUCTIONS
    assert "Keep transaction order and repeated transactions, including interest" in STATEMENT_INSTRUCTIONS
    assert "[as_of, balance, currency, withdrawal, deposit, description]" in STATEMENT_INSTRUCTIONS
    for account in STATEMENT_RESPONSE_EXAMPLE["accounts"]:
        for row in account["balances"]:
            assert isinstance(row, list) and len(row) == 6
