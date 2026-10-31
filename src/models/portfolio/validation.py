from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from src.log_messages import error as error_messages


def institution_name(value: str, *, max_length: int = 100) -> str:
    if not isinstance(value, str):
        raise ValueError(error_messages.INSTITUTION_NAME_MUST_BE_TEXT)
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(error_messages.INSTITUTION_NAME_MUST_NOT_CONTAIN_CONTROL_CHARACTERS)
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized or len(normalized) > max_length:
        raise ValueError(error_messages.INSTITUTION_NAME_LENGTH.format(max_length=max_length))
    return normalized


def decimal_value(value: str | Decimal, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(error_messages.DECIMAL_REQUIRED.format(label=label)) from exc
    if not result.is_finite() or abs(result) > Decimal("1e18"):
        raise ValueError(error_messages.DECIMAL_MAGNITUDE_LIMIT.format(label=label))
    if result.as_tuple().exponent < -8:
        raise ValueError(error_messages.DECIMAL_PRECISION_LIMIT.format(label=label))
    return result


def transaction_movements(withdrawal: Decimal | None, deposit: Decimal | None) -> bool:
    movements = (withdrawal, deposit)
    for amount in movements:
        if amount is not None:
            decimal_value(amount, "Transaction amount")
            if not isinstance(amount, Decimal) or amount < 0:
                raise ValueError(error_messages.INVALID_TRANSACTION_MOVEMENT)
    present = any(amount is not None for amount in movements)
    return present


def transaction_metadata(description: str, row_number: int, is_transaction: bool) -> None:
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError(error_messages.INVALID_TRANSACTION_DESCRIPTION)
    if type(row_number) is not int or (row_number < 1 if is_transaction else row_number != 0):
        raise ValueError(error_messages.INVALID_TRANSACTION_ORDER)


def country_code(value: str) -> str:
    if value and not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError(error_messages.INSTITUTION_COUNTRY_MUST_BE_A_TWO_LETTER_UPPERCASE_CODE)
    return value


def is_currency_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", value))


def currency_code(value: str) -> str:
    if not is_currency_code(value):
        raise ValueError(error_messages.INVALID_CURRENCY_CODE)
    return value


def account_number(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ValueError(error_messages.STATEMENT_ACCOUNT_NUMBER_MUST_CONTAIN_1_100_CHARACTERS)
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(error_messages.STATEMENT_ACCOUNT_NUMBER_MUST_NOT_CONTAIN_CONTROL_CHARACTERS)
    normalized = re.sub(r"[\s:-]", "", unicodedata.normalize("NFKC", value)).upper()
    if not normalized or not any(character.isdigit() for character in normalized):
        raise ValueError(error_messages.PRINTED_ACCOUNT_DIGITS_REQUIRED)
    return normalized


def account_product_type(value: str) -> str:
    """Validate a descriptive account type without imposing a product catalogue."""
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError(error_messages.INVALID_ACCOUNT_PRODUCT_TYPE)
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(error_messages.ACCOUNT_TYPE_MUST_NOT_CONTAIN_CONTROL_CHARACTERS)
    return " ".join(value.split())


def observation_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(error_messages.AS_OF_DATE_MUST_BE_YYYY_MM_DD) from exc
    if result.isoformat() != value or result > date.today():
        raise ValueError(error_messages.INVALID_OR_FUTURE_ISO_DATE)
    return result
