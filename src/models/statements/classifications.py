from __future__ import annotations

BALANCE_ROLES = (
    "closing_balance", "current_balance", "opening_balance", "transaction_amount",
    "available_balance", "credit_limit", "interest", "converted_equivalent", "other",
)

IMPORTABLE_BALANCE_ROLES = frozenset({"closing_balance", "current_balance"})

ACCOUNT_SCOPES = ("single_account", "aggregate", "unknown")

DATE_ROLES = (
    "statement_date", "period_end", "balance_date", "period_start", "transaction_date", "other",
)

IMPORTABLE_DATE_ROLES = frozenset({"statement_date", "period_end", "balance_date"})


def _readable_role(role: str) -> str:
    return role.replace("_", " ")
