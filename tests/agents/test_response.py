import json
from datetime import date
from decimal import Decimal

import pytest

from src.agents.response import (
    STATEMENT_RESPONSE_SCHEMA,
    StatementParsingError,
    StatementResponseParser,
)
from tests.statement_fixtures import text_document


def test_response_contract_requires_financial_fields_without_evidence():
    definitions = STATEMENT_RESPONSE_SCHEMA["$defs"]
    for name in ("AccountOutput", "InstitutionOutput"):
        schema = definitions[name]
        optional = {
            "AccountOutput": {"account_type"},
        }.get(name, set())
        assert set(schema["required"]) == set(schema["properties"]) - optional
        assert "evidence" not in schema["properties"]
    assert "EvidenceOutput" not in definitions


def test_wire_schema_contains_only_stored_row_fields():
    definitions = STATEMENT_RESPONSE_SCHEMA["$defs"]
    row_schema = definitions["BalanceOutput"]
    assert row_schema["type"] == "array"
    assert row_schema["minItems"] == row_schema["maxItems"] == 6
    balance_fields = dict(zip(
        ("as_of", "balance", "currency", "withdrawal", "deposit", "description"),
        row_schema["prefixItems"], strict=True,
    ))
    assert "enum" not in definitions["InstitutionOutput"]["properties"]["name"]
    assert set(balance_fields) == {
        "balance", "currency", "as_of", "withdrawal", "deposit", "description",
    }
    for field in ("withdrawal", "deposit"):
        assert "default" not in balance_fields[field]
        assert {"type": "null"} in balance_fields[field]["anyOf"]
    assert balance_fields["description"]["type"] == "string"
    assert "default" not in balance_fields["description"]


@pytest.mark.parametrize("response", ["{", '{"balances":', '{"account": {}, "balances": []}'])
def test_parser_uses_pydantic_json_and_schema_errors(response):
    document = text_document()
    with pytest.raises(StatementParsingError, match="validation error"):
        StatementResponseParser.parse(response, document)


def test_response_parser_builds_domain_models_without_evidence_or_inference():
    document = text_document()
    response = json.dumps({
        "institution": {"name": "DBS Bank"},
        "accounts": [{
            "number": "1234",
            "balances": [{
                "description": "",
                "withdrawal": None, "deposit": "1.00",
                "balance": "10.25", "currency": "SGD", "as_of": date.today().isoformat(),
            }],
        }],
    })
    extraction = StatementResponseParser.parse(response, document)
    assert extraction.account_number == "1234"
    assert extraction.balances[0].balance == Decimal("10.25")
    assert extraction.institution
    assert extraction.institution.alias == "DBS"
    assert not hasattr(extraction.balances[0], "labeled_evidence")
