"""ISO 4217 reference data for statement currency selection."""


import pycountry

from src.log_messages import error as error_messages

ISO_CURRENCY_CODES = tuple(sorted(currency.alpha_3 for currency in pycountry.currencies))
ISO_CURRENCY_REFERENCE = "; ".join(
    f"{code}: {pycountry.currencies.get(alpha_3=code).name}" for code in ISO_CURRENCY_CODES
)


def iso_currency_code(value: str) -> str:
    if value not in ISO_CURRENCY_CODES:
        raise ValueError(error_messages.CURRENCY_MUST_BE_A_VALID_ISO_4217_CODE)
    return value
