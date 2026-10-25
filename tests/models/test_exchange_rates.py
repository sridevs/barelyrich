from datetime import date, timedelta
from decimal import Decimal

from src.models.portfolio.exchange_rates import ExchangeRates


DAY = date(2026, 1, 10)


def test_identity_conversion_needs_no_external_rates():
    assert ExchangeRates({}, DAY).conversion("SGD", "SGD") == (Decimal(1), DAY)


def test_inr_is_always_identity_even_if_a_stored_rate_is_present():
    rates = ExchangeRates({"INR": (Decimal(2), DAY), "SGD": (Decimal(60), DAY)}, DAY)
    assert rates.conversion("SGD", "INR") == (Decimal(60), DAY)


def test_cross_conversion_uses_oldest_of_both_fx_dates():
    old = DAY - timedelta(days=8)
    rates = ExchangeRates({
        "USD": (Decimal(80), DAY), "SGD": (Decimal(60), old),
    }, DAY)
    assert rates.conversion("USD", "SGD") == (Decimal(80) / 60, old)


def test_missing_source_or_display_currency_suppresses_conversion():
    rates = ExchangeRates({"USD": (Decimal(80), DAY)}, DAY)
    assert rates.conversion("USD", "SGD") == (None, None)
    assert rates.conversion("SGD", "INR") == (None, None)
