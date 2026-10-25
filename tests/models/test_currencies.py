import pycountry
import pytest

from src.agents.response import STATEMENT_RESPONSE_SCHEMA
from src.models.currencies import (
    ISO_CURRENCY_CODES, ISO_CURRENCY_REFERENCE, iso_currency_code,
)


def test_currency_reference_and_schema_derive_from_the_same_iso_dataset():
    expected = {currency.alpha_3 for currency in pycountry.currencies}
    assert set(ISO_CURRENCY_CODES) == expected
    assert set(
        STATEMENT_RESPONSE_SCHEMA["$defs"]["BalanceOutput"]["properties"]["currency"]["enum"]
    ) == expected
    for code in ISO_CURRENCY_CODES:
        assert iso_currency_code(code) == code
        assert f"{code}: {pycountry.currencies.get(alpha_3=code).name}" in ISO_CURRENCY_REFERENCE


@pytest.mark.parametrize("code", ["ZZZ", "ABC", "sgd", "Singapore dollar", ""])
def test_non_iso_currency_codes_are_rejected_without_echoing_input(code):
    with pytest.raises(ValueError, match="ISO 4217") as failure:
        iso_currency_code(code)
    assert str(failure.value) == "Currency must be a valid ISO 4217 code."
