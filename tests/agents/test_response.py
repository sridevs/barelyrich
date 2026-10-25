from datetime import date
from decimal import Decimal
import json

import pytest

from src.models.statements.classifications import ACCOUNT_SCOPES, BALANCE_ROLES, DATE_ROLES
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage
from src.agents.response import (
    STATEMENT_RESPONSE_SCHEMA, StatementParsingError, StatementResponseParser,
)


def test_response_contract_requires_financial_fields_without_evidence():
    definitions = STATEMENT_RESPONSE_SCHEMA["$defs"]
    for name in ("BalanceOutput", "AccountOutput", "InstitutionOutput"):
        schema = definitions[name]
        optional = {"account_type"} if name == "AccountOutput" else set()
        assert set(schema["required"]) == set(schema["properties"]) - optional
        assert "evidence" not in schema["properties"]
    assert "EvidenceOutput" not in definitions


def test_wire_schema_and_domain_classifications_cannot_drift():
    definitions = STATEMENT_RESPONSE_SCHEMA["$defs"]
    balance_fields = definitions["BalanceOutput"]["properties"]
    assert "enum" not in definitions["InstitutionOutput"]["properties"]["name"]
    assert tuple(balance_fields["balance_role"]["enum"]) == BALANCE_ROLES
    assert tuple(balance_fields["account_scope"]["enum"]) == ACCOUNT_SCOPES
    assert tuple(balance_fields["date_role"]["enum"]) == DATE_ROLES


@pytest.mark.parametrize("response", ["{", '{"balances":', '{"account": {}, "balances": []}'])
def test_parser_uses_pydantic_json_and_schema_errors(response):
    document = StatementDocument((StatementPage(1, b"page image"),))
    with pytest.raises(StatementParsingError, match="validation error"):
        StatementResponseParser.parse(response, document)


def test_response_parser_builds_domain_models_without_evidence_or_inference():
    document = StatementDocument((StatementPage(1, b"page image"),))
    response = json.dumps({
        "institution": {"name": "DBS Bank"},
        "accounts": [{
            "number": "1234",
            "balances": [{
                "balance": "10.25", "currency": "SGD", "as_of": date.today().isoformat(),
                "balance_role": "closing_balance", "account_scope": "single_account",
                "date_role": "statement_date",
            }],
        }],
    })
    extraction = StatementResponseParser.parse(response, document)
    assert extraction.account_number == "1234"
    assert extraction.balances[0].balance == Decimal("10.25")
    assert extraction.institution is not None
    assert extraction.institution.alias == "DBS"
    assert not hasattr(extraction.balances[0], "labeled_evidence")
