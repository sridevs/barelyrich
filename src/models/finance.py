"""Pure financial arithmetic helpers."""

from decimal import Decimal

def convert(amount, rate):
    """Rate is units of quote currency per one base-currency unit."""
    return Decimal(str(amount)) * Decimal(str(rate))

def net_worth(total_assets_inr, total_liabilities_inr):
    return Decimal(str(total_assets_inr)) - Decimal(str(total_liabilities_inr))

def apply_signed_events(opening_balance, events):
    total = Decimal(str(opening_balance))
    for signed_amount in events:
        total += Decimal(str(signed_amount))
    return total
