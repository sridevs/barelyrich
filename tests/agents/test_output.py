from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.agents.output import BalanceOutput, StatementOutput
from src.agents.response import StatementResponseParser


def balance_data():
    return {
        "description": "",
        "withdrawal": None, "deposit": "1.00",
        "balance": "10.25",
        "currency": "SGD",
        "as_of": date.today().isoformat(),
    }


def currency_section(number, currency, account_type=None):
    return {
        "number": number, "account_type": account_type,
        "balances": [{**balance_data(), "currency": currency}],
    }


@pytest.mark.parametrize("currency_type", [None, "", "EUR", "currency_breakdown",
                                          "current_and_savings_account"])
def test_currency_sections_merge_before_domain_validation(currency_type, caplog):
    with caplog.at_level("INFO"):
        extraction = StatementOutput.model_validate({
            "institution": {"name": "Example Bank"},
            "accounts": [
                currency_section("123-456", "SGD", "Current and Savings Account"),
                currency_section("123456", "EUR", currency_type),
            ],
        }).to_domain()
    assert len(extraction.accounts) == 1
    account = extraction.accounts[0]
    assert account.number == "123-456"
    assert account.account_type == "Current and Savings Account"
    assert [row.currency for row in account.balances] == ["SGD", "EUR"]
    assert "merged currency account sections" in caplog.text
    assert [row.currency for row in account.to_snapshots("Example Bank", "Savings", "asset")] == [
        "SGD", "EUR",
    ]


def test_currency_section_first_uses_later_product_type_and_keeps_distinct_accounts():
    extraction = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [
            currency_section("1234", "EUR", "currency_breakdown"),
            currency_section("5678", "USD", "Checking"),
            currency_section("1234", "SGD", "Savings"),
        ],
    }).to_domain()
    assert [item.number for item in extraction.accounts] == ["1234", "5678"]
    assert extraction.accounts[0].account_type == "Savings"
    assert [row.currency for row in extraction.accounts[0].balances] == ["EUR", "SGD"]


@pytest.mark.parametrize(("number", "product", "message"), [
    ("N/A", "EUR", "digits"),
])
def test_invalid_or_conflicting_sections_still_fail(number, product, message):
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [
            currency_section("1234", "SGD", "Savings"),
            currency_section(number, "EUR", product),
        ],
    })
    with pytest.raises(ValueError, match=message):
        output.to_domain()


def test_conflicting_account_types_are_cleared_for_review(caplog):
    with caplog.at_level("WARNING"):
        extraction = StatementOutput.model_validate({
            "institution": {"name": "Example Bank"},
            "accounts": [
                currency_section("1234", "SGD", "Savings"),
                currency_section("1234", "EUR", "Loan"),
                currency_section("1234", "USD", "Savings"),
            ],
        }).to_domain()
    assert extraction.accounts[0].account_type == ""
    assert len(extraction.balances) == 3
    assert "conflicting account types" in caplog.text


def test_merging_preserves_repeated_transaction_rows_and_is_repeatable():
    section = currency_section("1234", "SGD", "Savings")
    section["balances"][0].update(withdrawal="1.00", description="Printed transaction")
    output = StatementOutput.model_validate({
        "institution": {"name": "Example Bank"},
        "accounts": [section, deepcopy(section)],
    })
    extraction = output.to_domain()
    assert len(extraction.balances) == 2
    assert extraction.balances[0] == extraction.balances[1]
    assert output.to_domain() == extraction
    assert len(output.accounts) == 2


@pytest.mark.parametrize("field", ["withdrawal", "deposit", "description"])
def test_movement_keys_are_required_even_when_other_movement_is_present(field):
    fields = balance_data()
    fields.update(withdrawal="0.00", deposit="5.00")
    del fields[field]
    with pytest.raises(ValidationError) as failure:
        BalanceOutput.model_validate(fields)
    assert any(item["loc"] == (field,) and item["type"] == "missing"
               for item in failure.value.errors())


@pytest.mark.parametrize("withdrawal,deposit", [
    ("0", None), (None, "0.00"), ("0.00", "0"),
    ("5.00", None), (None, "5.00"), ("5.00", "2.00"),
])
def test_required_movements_accept_null_zero_and_printed_amounts(withdrawal, deposit):
    output = BalanceOutput.model_validate({
        **balance_data(), "withdrawal": withdrawal, "deposit": deposit,
    })
    assert output.withdrawal == withdrawal
    assert output.deposit == deposit
    row = output.to_domain()
    assert row.withdrawal == (None if withdrawal is None else Decimal(withdrawal))
    assert row.deposit == (None if deposit is None else Decimal(deposit))


@pytest.mark.parametrize("description", ["", "Interest credit", "x" * 2000])
def test_required_description_preserves_text(description):
    output = BalanceOutput.model_validate({**balance_data(), "description": description})
    assert output.to_domain().description == description


@pytest.mark.parametrize("description", [None, 123, "x" * 2001])
def test_required_description_rejects_null_wrong_types_and_oversized_text(description):
    with pytest.raises(ValidationError):
        BalanceOutput.model_validate({**balance_data(), "description": description})


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
    assert extraction.institution
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


def test_repeated_transaction_values_are_preserved_for_review(caplog):
    original = balance_data()
    repeated = deepcopy(original)
    repeated["balance"] = "10.250"
    with caplog.at_level("INFO"):
        extraction = statement_output([original, repeated]).to_domain()
    assert len(extraction.balances) == 2
    assert extraction.balances[0].balance == Decimal("10.25")
    assert "repeated equivalent balance rows collapsed" not in caplog.text
    assert "10.250" not in caplog.text
    assert "Account 1234" not in caplog.text


@pytest.mark.parametrize("field,value", [
    ("balance", "20.50"),
])
def test_distinct_same_currency_rows_are_never_silently_collapsed(field, value):
    original = balance_data()
    distinct = deepcopy(original)
    distinct[field] = value
    extraction = statement_output([original, distinct]).to_domain()
    assert len(extraction.balances) == 2
    assert not extraction.accounts[0].has_conflicting_summaries
    assert len(extraction.to_snapshots("Example", "Savings", "asset")) == 2


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
