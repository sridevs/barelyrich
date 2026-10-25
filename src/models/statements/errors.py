from __future__ import annotations


class DuplicateStatementCurrency(ValueError):
    """More than one distinct balance was returned for a currency."""
