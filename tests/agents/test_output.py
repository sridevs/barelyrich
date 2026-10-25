from datetime import date
from copy import deepcopy
from decimal import Decimal

from pydantic import ValidationError
import pytest

from src.agents.output import BalanceOutput, StatementOutput
from src.agents.response import StatementResponseParser


def balance_data():
    return {
        "balance": "10.25",
        "currency": "SGD",
        "as_of": date.today().isoformat(),
        "balance_role": "closing_balance",
        "account_scope": "single_account",
        "date_role": "statement_date",
    }


@pytest.mark.parametrize("account_type", [None, "", "  ", "Fixed deposit", "Custom bank product"])
def test_optional_free_text_account_type_does_not_trigger_missing_data_fallback(account_type):
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [{
            "number": "1234", "account_type": account_type, "balances": [balance_data()],
        }],
    })
    StatementResponseParser.require_present_fields(output.model_dump_json())
    account = output.to_domain().accounts[0]
    assert account.account_type == (account_type or "")
    assert account.to_snapshots("Example Bank", "Deposit", "asset")[0].product_type == (
        account_type or ""
    ).strip()


def test_omitted_account_type_is_backward_compatible():
    output = statement_output([balance_data()])
    assert output.to_domain().accounts[0].account_type == ""
    StatementResponseParser.require_present_fields(output.model_dump_json())


@pytest.mark.parametrize("account_type", [123, ["Savings"], "x" * 101])
def test_account_type_is_bounded_text_not_an_enum(account_type):
    with pytest.raises(ValidationError):
        StatementOutput.model_validate({
            "institution": {"name": "Example Bank"},
            "accounts": [{
                "number": "1234", "account_type": account_type, "balances": [balance_data()],
            }],
        })


@pytest.mark.parametrize("field,value", [
    ("balance", 10.25), ("balance", True), ("balance", "1e3"),
    ("balance", "10.123456789"), ("balance", "NaN"), ("balance", ""),
    ("currency", "sgd"), ("currency", 123), ("as_of", 20260101),
    ("as_of", " "), ("balance_role", "invented"), ("extra", "private data"),
])
def test_typed_balance_rejects_coercions_and_extra_fields(field, value):
    fields = balance_data()
    fields[field] = value
    with pytest.raises(ValidationError):
        BalanceOutput.model_validate(fields)


def test_typed_output_preserves_extracted_values_for_review_without_evidence():
    output = StatementOutput.model_validate({
        "institution": {"name": "DBS"},
        "account": {"number": "1234"},
        "balances": [balance_data()],
    })
    extraction = output.to_domain()
    assert extraction.balances[0].balance == Decimal("10.25")
    assert extraction.institution is not None
    assert extraction.institution.name == "DBS"
    fields = balance_data()
    fields["balance"] = "999"
    changed = StatementOutput.model_validate({
        "institution": {"name": "DBS"},
        "account": {"number": "1234"},
        "balances": [fields],
    }).to_domain()
    assert changed.balances[0].balance == Decimal("999")


def test_typed_output_hides_sensitive_invalid_input():
    fields = balance_data()
    fields["balance"] = "private account value"
    with pytest.raises(ValidationError) as failure:
        BalanceOutput.model_validate(fields)
    assert "private account value" not in str(failure.value)


def test_root_transaction_array_is_not_part_of_balance_only_contract():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StatementOutput.model_validate({
            "institution": {"name": "DBS"},
            "account": {"number": "1234"},
            "balances": [balance_data()],
            "transactions": [],
        })


@pytest.mark.parametrize("issuer", [None, {}])
def test_issuer_is_required(issuer):
    with pytest.raises(ValidationError, match="institution"):
        StatementOutput.model_validate({
            "institution": issuer,
            "account": {"number": "1234"},
            "balances": [balance_data()],
        })


def statement_output(balances):
    return StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "account": {"number": "1234"},
        "balances": balances,
    })


def test_repeated_financial_values_are_collapsed_for_review(caplog):
    original = balance_data()
    repeated = deepcopy(original)
    repeated["balance"] = "10.250"
    with caplog.at_level("INFO"):
        extraction = statement_output([original, repeated]).to_domain()
    assert len(extraction.balances) == 1
    assert extraction.balances[0].balance == Decimal("10.25")
    assert "repeated equivalent balance rows collapsed" in caplog.text
    assert "10.250" not in caplog.text
    assert "Account 1234" not in caplog.text


@pytest.mark.parametrize("field,value", [
    ("balance", "20.50"), ("as_of", "2020-01-01"),
    ("balance_role", "opening_balance"), ("account_scope", "aggregate"),
    ("date_role", "period_end"),
])
def test_distinct_same_currency_rows_are_never_silently_collapsed(field, value):
    original = balance_data()
    distinct = deepcopy(original)
    distinct[field] = value
    with pytest.raises(ValueError, match="same currency"):
        statement_output([original, distinct]).to_domain()


def test_different_currencies_are_not_collapsed():
    original = balance_data()
    distinct = deepcopy(original)
    distinct["currency"] = "EUR"
    assert len(statement_output([original, distinct]).to_domain().balances) == 2


def test_fixed_deposit_account_is_kept_separate_with_its_sgd_balance():
    savings = balance_data()
    fixed_deposit = balance_data()
    fixed_deposit["balance"] = "50000.00"
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [
            {
                "number": "****1234",
                "balances": [savings],
            },
            {
                "number": "****5678",
                "balances": [fixed_deposit],
            },
        ],
    })

    extraction = output.to_domain()
    snapshots = extraction.to_snapshots(
        "example_bank", {"****1234": "Savings", "****5678": "Fixed deposit"}, "asset",
    )

    assert [(item.account_number, item.currency, item.balance) for item in snapshots] == [
        ("****1234", "SGD", Decimal("10.25")),
        ("****5678", "SGD", Decimal("50000.00")),
    ]
